import logging

from signalzero.services.database import get_db, init_postgres
from signalzero.services.notifications import compile_and_send_weekly_digest

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("SignalZero.WeeklyDigestRunner")

def run():
    logger.info("Initializing database session...")
    init_postgres()
    db_generator = get_db()
    db = next(db_generator)
    try:
        logger.info("Starting Weekly Digest Compilation...")
        success = compile_and_send_weekly_digest(db)
        if success:
            logger.info("Weekly digest compiled and sent successfully.")
        else:
            logger.info("Weekly digest compilation complete (no notification dispatched).")
    except Exception as e:
        logger.error(f"Error running weekly digest: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    run()
