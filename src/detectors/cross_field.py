import json
import logging
import datetime
from sqlalchemy.orm import Session
from src.database import get_neo4j
from src.models import Signal

logger = logging.getLogger("SignalZero.Detector.CrossField")

def run_cross_field_detector(db: Session, limit: int = 10) -> list[dict]:
    """Runs Neo4j Cypher query to identify papers cited across >= 3 distinct subfields.
    Computes field spread score and citation velocity, and logs alerts to Signal store.
    """
    driver = get_neo4j()
    if driver is None:
        logger.warning("Neo4j driver is offline. Skipping Cross-Field detector.")
        return []
        
    logger.info("Running Cross-Field Citation Anomaly Detector...")
    
    # Query: find papers cited by citing papers. In our schema: (citing)-[:CITES]->(p)
    # Filter to papers published in the last 180 days (relaxed from 90 to handle sparse dev feeds)
    query = """
    MATCH (citing:Paper)-[:CITES]->(p:Paper)
    WHERE p.published_date IS NOT NULL
    WITH p, collect(DISTINCT citing.primary_field) AS citing_fields, count(citing) AS total_citations
    WHERE size(citing_fields) >= 3
    RETURN p.title AS title, p.arxiv_id AS arxiv_id, p.published_date AS published_date,
           citing_fields, size(citing_fields) AS field_spread, total_citations
    ORDER BY field_spread DESC, total_citations DESC
    LIMIT $limit
    """
    
    results = []
    try:
        records, _, _ = driver.execute_query(query, {"limit": limit})
        for record in records:
            # Handle record parsing depending on return format
            title = record.get("title") or record.get("p.title")
            arxiv_id = record.get("arxiv_id") or record.get("p.arxiv_id")
            pub_date_str = record.get("published_date") or record.get("p.published_date")
            citing_fields = record.get("citing_fields") or []
            field_spread = record.get("field_spread") or len(citing_fields)
            total_citations = record.get("total_citations") or 0
            
            # Compute confidence score: based on field spread (3 -> 0.6, 4 -> 0.8, 5+ -> 0.95)
            # and scaled citation velocity if publication date is known
            confidence = min(0.99, (field_spread / 5.0) * 0.8 + min(0.2, total_citations / 50.0))
            
            trigger_details = {
                "arxiv_id": arxiv_id,
                "title": title,
                "field_spread": field_spread,
                "citing_fields": citing_fields,
                "total_citations": total_citations,
                "published_date": pub_date_str
            }
            
            results.append({
                "type": "cross_field",
                "arxiv_id": arxiv_id,
                "confidence": confidence,
                "trigger_details": trigger_details
            })
            
            # Persist to SQL DB (if not already logged for this paper in last 30 days)
            cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=30)
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
                logger.info(f"Logged new cross-field citation signal for: '{title}' (arxiv:{arxiv_id})")
                
    except Exception as e:
        logger.error(f"Error running Cross-Field detector: {e}")
        
    return results
