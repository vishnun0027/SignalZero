import json
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from signalzero.services.database import Base, InMemoryRedis, InMemoryNeo4j
from signalzero.models.models import Signal
from signalzero.core.agent.graph import analyze_signal_with_agent

TEST_DATABASE_URL = "sqlite:///:memory:"

@pytest.fixture(name="db_session")
def fixture_db_session():
    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    
    # Force mock DB state
    from signalzero.services import database
    database.redis_client = InMemoryRedis()
    database.neo4j_driver = InMemoryNeo4j()
    
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)

def test_langgraph_agent_execution(db_session):
    """Verifies that the LangGraph research agent compiles, runs through all nodes,
    generates a brief, and commits the brief and updated status back to the database.
    """
    # 1. Insert a mock Cross-Field citation signal
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
    
    # Retrieve to get database generated ID
    signal_id = signal.id
    assert signal_id is not None
    
    # 2. Run agent analysis
    success = analyze_signal_with_agent(db_session, signal_id)
    assert success is True
    
    # 3. Verify modifications in DB
    refetched = db_session.query(Signal).filter(Signal.id == signal_id).first()
    assert refetched.brief is not None
    assert "Core Novelty" in refetched.brief
    assert refetched.status in ["growing", "emerging", "false_positive"]
