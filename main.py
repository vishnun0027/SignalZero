import logging
from src.database import get_db, init_postgres
from src.ingestion import ingest_daily_papers
from src.detectors.vocab_drift import run_vocab_emergence_detector
from src.detectors.cross_field import run_cross_field_detector
from src.detectors.convergent import run_convergent_discovery_detector
from src.detectors.hackernews import run_hn_detector
from src.agent.graph import analyze_signal_with_agent
from src.models import Signal

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("SignalZero.Main")

def run_pipeline():
    logger.info("Initializing Database Connections...")
    init_postgres()
    db_generator = get_db()
    db = next(db_generator)
    
    try:
        logger.info("--- Step 1: Ingesting Daily Papers ---")
        ingest_daily_papers(db, limit=10) # Set to 10 for a fast first run
        
        logger.info("--- Step 2: Running Signal Detectors ---")
        logger.info("Running Vocab Drift Detector...")
        run_vocab_emergence_detector(db)
        
        logger.info("Running Cross Field Detector...")
        run_cross_field_detector(db)
        
        logger.info("Running Convergent Discovery Detector...")
        run_convergent_discovery_detector(db)
        
        logger.info("Running HackerNews Community Detector...")
        run_hn_detector(db)
        
        logger.info("--- Step 3: Triggering AI Agent on Emerging Signals ---")
        # Fetch signals that need analysis (status='emerging' but no brief generated yet)
        unprocessed_signals = db.query(Signal).filter(Signal.status == "emerging", Signal.brief.is_(None)).all()
        
        if not unprocessed_signals:
            logger.info("No new emerging signals require agent analysis.")
        else:
            logger.info(f"Found {len(unprocessed_signals)} signals requiring analysis.")
            for signal in unprocessed_signals:
                try:
                    analyze_signal_with_agent(db, signal.id)
                except Exception as e:
                    logger.error(f"Failed to analyze signal {signal.id}: {e}")
                    
        logger.info("--- Pipeline Completed Successfully ---")
        
    finally:
        db.close()

if __name__ == "__main__":
    run_pipeline()
