import logging

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from signalzero.utils.config import settings

logger = logging.getLogger("SignalZero.Database")

class Base(DeclarativeBase):
    pass

# --- PostgreSQL / SQLAlchemy Connection Setup ---
engine = None
SessionLocal = None

def init_postgres():
    global engine, SessionLocal
    db_url = settings.DATABASE_URL

    # Enable pgvector if postgres is used, else fallback gracefully
    connect_args = {}
    if db_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}

    try:
        engine = create_engine(db_url, connect_args=connect_args)
        # Test connection
        with engine.connect() as conn:
            if not db_url.startswith("sqlite"):
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
                conn.commit()
                logger.info("Successfully connected to PostgreSQL and verified pgvector extension.")
            else:
                logger.info("Successfully initialized SQLite fallback database.")
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    except Exception as e:
        logger.error(f"Failed to connect to PostgreSQL at {db_url}: {e}")
        logger.info("Falling back to local SQLite database.")
        fallback_url = "sqlite:///signalzero_fallback.db"
        engine = create_engine(fallback_url, connect_args={"check_same_thread": False})
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    if SessionLocal is None:
        init_postgres()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_db_session():
    """Helper to return a database session, auto-initializing if needed."""
    global SessionLocal
    if SessionLocal is None:
        init_postgres()
    return SessionLocal()


# --- Neo4j / AuraDB Connection Setup & Fallback ---
class InMemoryNeo4j:
    """Mock in-memory Neo4j graph database for local testing when AuraDB is unavailable."""
    def __init__(self):
        self.nodes = {}  # id -> {labels, properties}
        self.edges = []  # list of {from, to, type, properties}
        logger.info("Initialized InMemoryNeo4j graph database mock.")

    def execute_query(self, query: str, parameters: dict | None = None):
        logger.info(f"InMemoryNeo4j executing mock query: {query.strip().splitlines()[0]}...")
        # Cross-field detector v2 query mock
        if "CITES" in query or "citing:Paper" in query:
            # Baseline computation query (returns aggregated per-field stats)
            if "avg(field_spread)" in query or "stDev" in query:
                return [
                    {
                        "origin_field": "cs.CL",
                        "mean_spread": 2.0,
                        "std_spread": 0.8,
                        "paper_count": 50
                    },
                    {
                        "origin_field": "cs.CV",
                        "mean_spread": 1.8,
                        "std_spread": 0.6,
                        "paper_count": 40
                    },
                    {
                        "origin_field": "cs.LG",
                        "mean_spread": 2.2,
                        "std_spread": 0.9,
                        "paper_count": 60
                    }
                ], None, None

            # Cross-field detector v2 query: includes influential metadata and contexts
            return [
                {
                    "title": "Attention Is All You Need",
                    "arxiv_id": "1706.03762",
                    "published_date": "2017-06-12",
                    "origin_field": "cs.CL",
                    "all_citing_fields": ["cs.CL", "cs.CV", "cs.SD", "q-bio"],
                    "influential_citing_fields": ["cs.CV", "q-bio"],
                    "field_spread": 4,
                    "influential_field_spread": 2,
                    "total_citations": 35,
                    "influential_count": 8,
                    "citation_contexts": [
                        "We adopt the transformer architecture from Vaswani et al.",
                        "Following the approach of the attention mechanism proposed in this work",
                        "Previous work on attention has shown improvements in NLP tasks"
                    ]
                },
                {
                    "title": "Denoising Diffusion Probabilistic Models",
                    "arxiv_id": "2006.11239",
                    "published_date": "2020-06-19",
                    "origin_field": "cs.LG",
                    "all_citing_fields": ["cs.LG", "cs.CV", "stat.ML"],
                    "influential_citing_fields": ["cs.CV"],
                    "field_spread": 3,
                    "influential_field_spread": 1,
                    "total_citations": 12,
                    "influential_count": 3,
                    "citation_contexts": [
                        "We use the diffusion framework for image generation",
                        "Related work on generative models has demonstrated"
                    ]
                }
            ], None, None
        return [], None, None

    def close(self):
        pass

neo4j_driver = None

def get_neo4j():
    global neo4j_driver
    if neo4j_driver is not None:
        return neo4j_driver

    try:
        from neo4j import GraphDatabase
        # Check if user has updated default credentials
        if settings.NEO4J_PASSWORD == "neo4j_password" and "localhost" in settings.NEO4J_URI:
            logger.warning("Using default Neo4j credentials on localhost. Attempting local connection.")

        neo4j_driver = GraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD)
        )
        # Test connection
        neo4j_driver.verify_connectivity()
        logger.info("Successfully connected to Neo4j database.")
    except Exception as e:
        logger.error(f"Failed to connect to Neo4j: {e}. Falling back to InMemoryNeo4j.")
        neo4j_driver = InMemoryNeo4j()

    return neo4j_driver


# --- Redis / Upstash Connection Setup & Fallback ---
class InMemoryRedis:
    """Mock in-memory Redis key-value store for local testing."""
    def __init__(self):
        self.store = {}
        logger.info("Initialized InMemoryRedis mock.")

    def get(self, key: str):
        val = self.store.get(key)
        return val.decode("utf-8") if isinstance(val, bytes) else val

    def set(self, key: str, value: str, ex=None):
        self.store[key] = value
        return True

    def incr(self, key: str):
        val = self.store.get(key, 0)
        try:
            val = int(val) + 1
        except ValueError:
            val = 1
        self.store[key] = val
        return val

    def keys(self, pattern: str):
        import fnmatch
        # Simple glob matching
        return [k for k in self.store if fnmatch.fnmatch(k, pattern)]

    def ping(self):
        return True

redis_client = None

def get_redis():
    global redis_client
    if redis_client is not None:
        return redis_client

    try:
        import redis
        redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        redis_client.ping()
        logger.info("Successfully connected to Redis.")
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}. Falling back to InMemoryRedis.")
        redis_client = InMemoryRedis()

    return redis_client


def prune_historical_data(db_session, retention_days: int) -> int:
    """Prunes papers and Neo4j nodes published older than retention_days.
    Returns the number of SQL papers pruned.
    """
    import datetime
    cutoff_date = datetime.date.today() - datetime.timedelta(days=retention_days)
    logger.info(f"Starting historical data pruning (retention: {retention_days} days, cutoff: {cutoff_date})...")

    # 1. Prune Neo4j citation graph nodes
    try:
        driver = get_neo4j()
        if driver is not None:
            cutoff_date_str = str(cutoff_date)
            # Cypher query: detach and delete old papers
            neo4j_query = """
            MATCH (p:Paper)
            WHERE p.published_date IS NOT NULL AND p.published_date < $cutoff_date
            DETACH DELETE p
            """
            driver.execute_query(neo4j_query, {"cutoff_date": cutoff_date_str})
            logger.info("Successfully pruned old nodes from Neo4j citation graph.")
    except Exception as e:
        logger.error(f"Error pruning Neo4j citation graph: {e}")

    # 2. Prune Relational SQL database (Papers & Embeddings)
    # Since PaperEmbedding table has ON DELETE CASCADE on paper_id (pointing to papers.arxiv_id),
    # deleting the Paper row will cascade delete the PaperEmbedding row.
    pruned_count = 0
    try:
        from signalzero.models.models import Paper

        # Query papers to delete
        papers_to_prune = db_session.query(Paper).filter(Paper.published_date < cutoff_date).all()
        pruned_count = len(papers_to_prune)
        if pruned_count > 0:
            for paper in papers_to_prune:
                db_session.delete(paper)
            db_session.commit()
            logger.info(f"Successfully pruned {pruned_count} historical papers and their embeddings from SQL database.")
        else:
            logger.info("No SQL papers found older than cutoff date. Nothing to prune.")
    except Exception as e:
        db_session.rollback()
        logger.error(f"Error pruning SQL database papers: {e}")

    return pruned_count
