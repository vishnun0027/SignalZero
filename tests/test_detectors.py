import json
import datetime
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.database import Base, InMemoryRedis, InMemoryNeo4j
from src.models import Paper, PaperEmbedding
from src.detectors.cross_field import run_cross_field_detector
from src.detectors.vocab_drift import extract_ngrams
from src.detectors.convergent import run_convergent_discovery_detector

TEST_DATABASE_URL = "sqlite:///:memory:"

@pytest.fixture(name="db_session")
def fixture_db_session():
    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    
    # Initialize in-memory database connections for the tests
    # Force mock DB state
    from src import database
    database.redis_client = InMemoryRedis()
    database.neo4j_driver = InMemoryNeo4j()
    
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)

def test_cross_field_detector_mock(db_session):
    """Verifies cross-field citation detector returns signals using the InMemoryNeo4j graph mock."""
    signals = run_cross_field_detector(db_session)
    # The default mock returns 2 papers: Attention Is All You Need, Denoising Diffusion
    assert len(signals) == 2
    assert any(s["type"] == "cross_field" for s in signals)
    assert any("Attention" in s["trigger_details"]["title"] for s in signals)

def test_vocab_ngram_extraction():
    """Tests cleanup, tokenization, and n-gram count extractor."""
    abstracts = [
        "We propose instruction tuning for large language models.",
        "Instruction tuning improves zero-shot performance on various tasks."
    ]
    ngrams = extract_ngrams(abstracts, n_values=[1, 2])
    # Verify n-grams are extracted
    assert "instruction tuning" in ngrams
    assert ngrams["instruction tuning"] == 2
    # Standard stopwords should be filtered out
    assert "we" not in ngrams
    assert "for" not in ngrams

def test_convergent_discovery_clustering(db_session):
    """Tests convergent discovery detector by inserting three papers with similar embeddings
    and independent authorship groups.
    """
    # Create 3 independent papers
    p1 = Paper(
        arxiv_id="2101.00001", title="Method A for Low Rank Adaptation",
        summary="We introduce a low rank adaptation method to adapt weights in large transformers...",
        published_date=datetime.date.today(), authors="Alice Smith, Bob Jones",
        primary_category="cs.LG", all_categories="cs.LG"
    )
    p2 = Paper(
        arxiv_id="2101.00002", title="Parameter Efficient Tuning via Low Rank Adaptors",
        summary="A low rank adaptation technique is proposed to train large language models efficiently...",
        published_date=datetime.date.today(), authors="Charlie Brown",
        primary_category="cs.CL", all_categories="cs.CL"
    )
    p3 = Paper(
        arxiv_id="2101.00003", title="Low Rank Adapters for Transformer Networks",
        summary="Adapting transformers using low rank matrices achieves high efficiency and speed...",
        published_date=datetime.date.today(), authors="Diana Prince, Arthur Curry",
        primary_category="cs.AI", all_categories="cs.AI"
    )
    db_session.add_all([p1, p2, p3])
    db_session.flush()
    
    # Insert near-identical embeddings (all-ones vectors to guarantee cosine similarity = 1.0)
    emb_vec = [1.0] * 384
    db_session.add(PaperEmbedding(paper_id=p1.arxiv_id, embedding=json.dumps(emb_vec)))
    db_session.add(PaperEmbedding(paper_id=p2.arxiv_id, embedding=json.dumps(emb_vec)))
    db_session.add(PaperEmbedding(paper_id=p3.arxiv_id, embedding=json.dumps(emb_vec)))
    db_session.commit()
    
    # Run the detector
    signals = run_convergent_discovery_detector(db_session)
    assert len(signals) >= 1
    assert signals[0]["type"] == "convergent"
    assert signals[0]["trigger_details"]["cluster_size"] == 3
