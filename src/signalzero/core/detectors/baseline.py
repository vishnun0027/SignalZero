"""Cross-field baseline computation module.

Computes and stores rolling per-field statistics for adaptive cross-field anomaly detection.
This enables the detector to measure whether a paper's field spread is genuinely anomalous
relative to current norms, rather than using static absolute thresholds.
"""
import datetime
import logging

from sqlalchemy.orm import Session

from signalzero.models.models import CrossFieldBaseline
from signalzero.services.database import get_neo4j

logger = logging.getLogger("SignalZero.Detector.Baseline")


def compute_cross_field_baselines(db: Session) -> int:
    """Queries Neo4j for all papers grouped by origin field, computes mean and stddev
    of field_spread, and upserts results into the CrossFieldBaseline table.

    Returns the number of fields updated.
    """
    driver = get_neo4j()
    if driver is None:
        logger.warning("Neo4j driver is offline. Skipping baseline computation.")
        return 0

    logger.info("Computing adaptive cross-field baselines...")

    # Query: for each origin field, compute the average and stddev of field_spread
    # across all papers published in the baseline window
    query = """
    MATCH (citing:Paper)-[:CITES]->(p:Paper)
    WHERE p.published_date IS NOT NULL AND p.primary_field IS NOT NULL
    WITH p, p.primary_field AS origin_field,
         count(DISTINCT citing.primary_field) AS field_spread
    WITH origin_field,
         avg(field_spread) AS mean_spread,
         stDev(field_spread) AS std_spread,
         count(p) AS paper_count
    WHERE paper_count >= 5
    RETURN origin_field, mean_spread, std_spread, paper_count
    ORDER BY paper_count DESC
    """

    updated_count = 0
    try:
        records, _, _ = driver.execute_query(query, {})
        now = datetime.datetime.now(datetime.UTC)

        for record in records:
            origin_field = record.get("origin_field")
            mean_spread = record.get("mean_spread", 1.0)
            std_spread = record.get("std_spread", 0.5)
            paper_count = record.get("paper_count", 0)

            if not origin_field:
                continue

            # Ensure stddev is at least 0.1 to avoid division-by-zero in Z-score
            std_spread = max(0.1, std_spread or 0.1)

            # Upsert baseline record
            existing = db.query(CrossFieldBaseline).filter(
                CrossFieldBaseline.origin_field == origin_field
            ).first()

            if existing:
                existing.avg_field_spread = mean_spread  # type: ignore[assignment]
                existing.stddev_field_spread = std_spread  # type: ignore[assignment]
                existing.paper_count = paper_count  # type: ignore[assignment]
                existing.computed_at = now  # type: ignore[assignment]
            else:
                baseline = CrossFieldBaseline(
                    origin_field=origin_field,
                    avg_field_spread=mean_spread,
                    stddev_field_spread=std_spread,
                    paper_count=paper_count,
                    computed_at=now
                )
                db.add(baseline)

            updated_count += 1

        db.commit()
        logger.info(f"Updated cross-field baselines for {updated_count} origin fields.")

    except Exception as e:
        db.rollback()
        logger.error(f"Error computing cross-field baselines: {e}")

    return updated_count
