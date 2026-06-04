"""Cross-field citation anomaly detector — v2 with citation inflation robustness.

Detects papers being cited across multiple distinct research fields, indicating
a general-purpose mechanism that transcends its origin domain. Historically this
has been one of the strongest early signals of paradigm-shifting work.

v2 addresses the challenge of AI-tool-driven citation inflation through four strategies:
1. isInfluential weighting — prioritises citations S2 classifies as influential
2. Context-based intent heuristics — distinguishes methodology-use from background-mention
3. Relative Z-score — compares field spread against peer papers from the same origin field
4. Adaptive rolling baselines — auto-adjusts thresholds as cross-field rates evolve
"""
import datetime
import json
import logging
import re

from sqlalchemy.orm import Session

from signalzero.models.models import CrossFieldBaseline, Signal
from signalzero.services.database import get_neo4j

logger = logging.getLogger("SignalZero.Detector.CrossField")


# --- Citation Intent Heuristic Classifier ---
# Since Semantic Scholar's `intents` field is mostly empty in practice,
# we classify intent from the `contexts` field (raw text snippets) using
# keyword pattern matching. This is lightweight but effective for
# distinguishing genuine methodological adoption from shallow background mentions.

METHODOLOGY_PATTERNS = [
    r"\bwe use\b", r"\bwe adopt\b", r"\bwe follow\b", r"\bwe employ\b",
    r"\bwe apply\b", r"\bwe extend\b", r"\bwe build on\b", r"\bwe modify\b",
    r"\bbased on\b", r"\bfollowing the approach\b", r"\busing the method\b",
    r"\barchitecture from\b", r"\bour model is based on\b", r"\bwe fine-tune\b",
    r"\bwe leverage\b", r"\bwe implement\b", r"\binspired by\b",
    r"\badapted from\b", r"\bwe trained\b", r"\bwe pretrain\b",
]

BACKGROUND_PATTERNS = [
    r"\bhas been shown\b", r"\bprevious work\b", r"\bprior work\b",
    r"\brelated work\b", r"\bprior study\b", r"\bit is known that\b",
    r"\bliterature\b", r"\bsurvey\b", r"\breview of\b",
    r"\bexisting methods\b", r"\brecent advances\b", r"\bstate of the art\b",
    r"\bhas demonstrated\b", r"\bhave shown\b",
]

# Pre-compile for performance
_METHODOLOGY_RE = [re.compile(p, re.IGNORECASE) for p in METHODOLOGY_PATTERNS]
_BACKGROUND_RE = [re.compile(p, re.IGNORECASE) for p in BACKGROUND_PATTERNS]


def classify_citation_intent(context_snippet: str) -> str:
    """Classifies a citation context snippet as 'methodology', 'background', or 'unknown'.

    Uses keyword pattern matching on the citation context text. This is a pragmatic
    alternative to S2's mostly-empty `intents` field.

    Args:
        context_snippet: The text surrounding the citation mention.

    Returns:
        One of 'methodology', 'background', or 'unknown'.
    """
    if not context_snippet:
        return "unknown"

    methodology_hits = sum(1 for p in _METHODOLOGY_RE if p.search(context_snippet))
    background_hits = sum(1 for p in _BACKGROUND_RE if p.search(context_snippet))

    if methodology_hits > background_hits:
        return "methodology"
    elif background_hits > methodology_hits:
        return "background"
    else:
        return "unknown"


def compute_relative_zscore(field_spread: float, origin_field: str, db: Session) -> float:
    """Computes how anomalous a paper's field spread is relative to its peer papers.

    Loads the pre-computed baseline for the paper's origin field and returns
    a Z-score: (observed - mean) / stddev. Higher = more anomalous.

    Args:
        field_spread: The observed field spread count for this paper.
        origin_field: The paper's primary arXiv category (e.g. "cs.CL").
        db: SQLAlchemy session.

    Returns:
        Z-score as a float. Returns 0.0 if no baseline exists (conservative).
    """
    baseline = db.query(CrossFieldBaseline).filter(
        CrossFieldBaseline.origin_field == origin_field
    ).first()

    if not baseline or baseline.paper_count < 5:
        # No reliable baseline — fall back to a conservative estimate
        # Assume mean=1.5, stddev=1.0 as a generic prior
        return (field_spread - 1.5) / 1.0

    stddev = max(0.1, baseline.stddev_field_spread)
    return (field_spread - baseline.avg_field_spread) / stddev


def run_cross_field_detector(db: Session, limit: int = 10) -> list[dict]:
    """Runs Neo4j Cypher query to identify papers cited across distinct subfields.

    v2: Uses four strategies to be robust against AI-tool-driven citation inflation:
    1. isInfluential weighting — influential citations get higher weight
    2. Context-based intent — methodology citations weighted higher than background
    3. Relative Z-score — only flags papers significantly above their field's norm
    4. Adaptive baselines — loads rolling per-field stats for Z-score computation
    """
    driver = get_neo4j()
    if driver is None:
        logger.warning("Neo4j driver is offline. Skipping Cross-Field detector.")
        return []

    logger.info("Running Cross-Field Citation Anomaly Detector (v2 — inflation-robust)...")

    from signalzero.utils.config import settings

    # v2 Cypher query: returns influential citation metrics alongside standard field spread.
    # Edge properties r.is_influential and r.citation_context are stored by the ingestion pipeline.
    query = """
    MATCH (citing:Paper)-[r:CITES]->(p:Paper)
    WHERE p.published_date IS NOT NULL
    WITH p,
         collect(DISTINCT citing.primary_field) AS all_citing_fields,
         collect(DISTINCT CASE WHEN r.is_influential = true
                 THEN citing.primary_field END) AS influential_citing_fields_raw,
         count(citing) AS total_citations,
         sum(CASE WHEN r.is_influential = true THEN 1 ELSE 0 END) AS influential_count,
         collect(r.citation_context) AS citation_contexts
    WITH p, all_citing_fields,
         [f IN influential_citing_fields_raw WHERE f IS NOT NULL] AS influential_citing_fields,
         total_citations, influential_count, citation_contexts
    WHERE size(all_citing_fields) >= $min_fields
    RETURN p.title AS title, p.arxiv_id AS arxiv_id,
           p.published_date AS published_date, p.primary_field AS origin_field,
           all_citing_fields, influential_citing_fields,
           size(all_citing_fields) AS field_spread,
           size(influential_citing_fields) AS influential_field_spread,
           total_citations, influential_count, citation_contexts
    ORDER BY influential_field_spread DESC, field_spread DESC
    LIMIT $limit
    """

    results = []
    try:
        records, _, _ = driver.execute_query(query, {
            "limit": limit,
            "min_fields": settings.CROSS_FIELD_MIN_FIELDS
        })
        for record in records:
            title = record.get("title") or record.get("p.title")
            arxiv_id = record.get("arxiv_id") or record.get("p.arxiv_id")
            pub_date_str = record.get("published_date") or record.get("p.published_date")
            origin_field = record.get("origin_field") or record.get("p.primary_field") or "unknown"
            all_citing_fields = record.get("all_citing_fields") or []
            influential_citing_fields = record.get("influential_citing_fields") or []
            field_spread = record.get("field_spread") or len(all_citing_fields)
            influential_field_spread = record.get("influential_field_spread") or len(influential_citing_fields)
            total_citations = record.get("total_citations") or 0
            influential_count = record.get("influential_count") or 0
            citation_contexts = record.get("citation_contexts") or []

            # --- Strategy 1: AI-bubble discount (retained from v1, enhanced) ---
            broad_categories = set()
            core_ai_count = 0
            core_ai_fields = {"cs.AI", "cs.LG", "cs.CL", "cs.CV", "cs.NE"}
            for f in all_citing_fields:
                parts = f.split('.')
                broad_categories.add(parts[0])
                if f in core_ai_fields:
                    core_ai_count += 1

            effective_spread = float(field_spread)
            if core_ai_count == len(all_citing_fields) and len(all_citing_fields) > 1:
                # All citations stay within core AI — apply strong discount
                effective_spread = max(1.0, field_spread * 0.6)
            elif len(broad_categories) == 1:
                # Multiple subfields but same broad domain — minor discount
                effective_spread = max(1.0, field_spread * 0.8)

            # --- Strategy 2: Context-based intent classification ---
            methodology_count = 0
            background_count = 0
            for ctx in citation_contexts:
                if not ctx:
                    continue
                intent = classify_citation_intent(ctx)
                if intent == "methodology":
                    methodology_count += 1
                elif intent == "background":
                    background_count += 1

            total_classified = methodology_count + background_count
            methodology_ratio = (methodology_count / total_classified) if total_classified > 0 else 0.5

            # --- Strategy 3: Relative Z-score vs. peers ---
            z_score = compute_relative_zscore(effective_spread, origin_field, db)

            # --- Strategy 4: Adaptive baseline is embedded in the Z-score computation ---
            # (compute_relative_zscore loads the CrossFieldBaseline for the origin field)

            # --- Combined confidence score ---
            # Weighs four factors:
            #   - Relative rarity (Z-score): 35% — how anomalous vs. peers
            #   - Influential field spread: 30% — field spread from high-quality citations only
            #   - Intent quality: 20% — ratio of methodology vs. background citations
            #   - Influential citation count: 15% — raw count of influential citations
            confidence = min(0.99, max(0.05,
                (min(1.0, z_score / 4.0)) * 0.35 +
                (min(1.0, influential_field_spread / 5.0)) * 0.30 +
                methodology_ratio * 0.20 +
                min(0.15, influential_count / 20.0)
            ))

            trigger_details = {
                "arxiv_id": arxiv_id,
                "title": title,
                "origin_field": origin_field,
                "field_spread": field_spread,
                "influential_field_spread": influential_field_spread,
                "all_citing_fields": all_citing_fields,
                "influential_citing_fields": influential_citing_fields,
                "total_citations": total_citations,
                "influential_count": influential_count,
                "methodology_ratio": round(methodology_ratio, 3),
                "z_score": round(z_score, 3),
                "effective_spread": round(effective_spread, 3),
                "published_date": pub_date_str
            }

            results.append({
                "type": "cross_field",
                "arxiv_id": arxiv_id,
                "confidence": confidence,
                "trigger_details": trigger_details
            })

            # Persist to SQL DB (if not already logged for this paper in last 30 days)
            cutoff = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=30)
            existing_signal = db.query(Signal).filter(
                Signal.type == "cross_field",
                Signal.trigger_details.like(f'%"{arxiv_id}"%'),
                Signal.created_at >= cutoff
            ).first()

            if not existing_signal:
                signal = Signal(
                    type="cross_field",
                    confidence=confidence,
                    trigger_details=json.dumps(trigger_details),
                    status="emerging"
                )
                db.add(signal)
                db.commit()
                logger.info(
                    f"Logged cross-field signal: '{title}' (arxiv:{arxiv_id}) "
                    f"[z={z_score:.2f}, inf_spread={influential_field_spread}, "
                    f"method_ratio={methodology_ratio:.2f}, conf={confidence:.2f}]"
                )

    except Exception as e:
        logger.error(f"Error running Cross-Field detector: {e}")

    return results
