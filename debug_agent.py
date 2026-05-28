import json
import traceback
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.database import Base, InMemoryRedis, InMemoryNeo4j
from src.models import Signal
from src.agent.graph import analyze_signal_with_agent

def debug_run():
    # Setup test SQLite DB
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine)
    db_session = TestingSessionLocal()
    
    # Setup mocks
    import src.database as db
    db.redis_client = InMemoryRedis()
    db.neo4j_driver = InMemoryNeo4j()
    
    trigger_details = {
        "arxiv_id": "1706.03762",
        "title": "Attention Is All You Need",
        "field_spread": 4,
        "citing_fields": ["cs.CL", "cs.CV", "cs.SD", "q-bio"],
        "total_citations": 45,
        "published_date": "2017-06-12"
    }
    
    signal = Signal(
        type="cross_field",
        confidence=0.8,
        trigger_details=json.dumps(trigger_details),
        status="emerging"
    )
    db_session.add(signal)
    db_session.commit()
    
    print("Starting LangGraph agent debug execution...")
    try:
        analyze_signal_with_agent(db_session, signal.id)
        print("Success!")
    except Exception:
        print("\n--- DETECTED EXCEPTION TRACEBACK ---")
        traceback.print_exc()
        print("------------------------------------\n")

if __name__ == "__main__":
    debug_run()
