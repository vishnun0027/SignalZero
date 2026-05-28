import logging
from signalzero.utils.config import settings
from signalzero.services.database import init_postgres, get_db, get_neo4j

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("VerifyConnections")

def check_postgresql():
    logger.info("=== Testing Supabase PostgreSQL Connection ===")
    if settings.DATABASE_URL == "sqlite:///signalzero.db":
        logger.warning("DATABASE_URL is set to SQLite default. Please configure it in your .env file.")
        return False
        
    try:
        from sqlalchemy import text
        # Initialize
        init_postgres()
        # Get session
        db_generator = get_db()
        db = next(db_generator)
        
        # Test connection
        res = db.execute(text("SELECT 1;")).fetchone()
        logger.info(f"Successfully connected to database! Query result: {res[0]}")
        
        # Test pgvector extension
        try:
            vector_check = db.execute(text("SELECT extname FROM pg_extension WHERE extname = 'vector';")).fetchone()
            if vector_check:
                logger.info("pgvector extension is ENABLED on Supabase.")
            else:
                logger.warning("pgvector extension is NOT enabled. Attempting to enable it...")
                db.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
                db.commit()
                logger.info("pgvector extension enabled successfully!")
        except Exception as vec_err:
            logger.error(f"Failed to check/enable pgvector: {vec_err}")
            logger.warning("Make sure your database user has permission to install extensions (or enable it in Supabase UI).")
            
        return True
    except Exception as e:
        logger.error(f"PostgreSQL connection failed: {e}")
        return False

def check_neo4j():
    logger.info("=== Testing Neo4j Aura Connection ===")
    if "localhost" in settings.NEO4J_URI and settings.NEO4J_PASSWORD == "neo4j_password":
        logger.warning("NEO4J_URI/PASSWORD are set to local defaults. Please configure them in your .env file.")
        return False
        
    try:
        driver = get_neo4j()
        if "InMemoryNeo4j" in str(type(driver)):
            logger.error("Failed to connect to Neo4j database (fallback to InMemoryNeo4j occurred).")
            return False
            
        # Test query
        records, _, _ = driver.execute_query("RETURN 1 AS val;")
        logger.info(f"Successfully connected to Neo4j! Query result: {records[0]['val']}")
        
        # Check if vector search / indices can be queried
        logger.info("Verifying Neo4j connectivity check passed.")
        return True
    except Exception as e:
        logger.error(f"Neo4j connection failed: {e}")
        return False

def check_redis():
    logger.info("=== Testing Redis Connection ===")
    if not settings.REDIS_URL or "localhost" in settings.REDIS_URL:
        logger.warning("REDIS_URL is not configured or using localhost. Testing local connection.")
        
    try:
        from signalzero.services.database import get_redis
        client = get_redis()
        if "InMemoryRedis" in str(type(client)):
            logger.error("Failed to connect to Redis (fallback to InMemoryRedis occurred).")
            return False
            
        ping_res = client.ping()
        logger.info(f"Successfully connected to Redis! Ping response: {ping_res}")
        return True
    except Exception as e:
        logger.error(f"Redis connection failed: {e}")
        return False

def main():
    print("\n" + "="*50)
    print("SignalZero Connection Tester")
    print("="*50 + "\n")
    
    postgres_ok = check_postgresql()
    print()
    neo4j_ok = check_neo4j()
    print()
    redis_ok = check_redis()
    
    print("\n" + "="*50)
    if postgres_ok and neo4j_ok and redis_ok:
        print("SUCCESS: All databases (Supabase, Neo4j, Redis) are connected and ready!")
    else:
        print("WARNING: Some connections failed. Please check the logs above and update .env.")
    print("="*50 + "\n")

if __name__ == "__main__":
    main()
