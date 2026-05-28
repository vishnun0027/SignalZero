import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from signalzero.models.models import Paper, PaperEmbedding
from signalzero.services.database import Base
from signalzero.services.ingestion import get_embedding

# Setup a test SQLite database
TEST_DATABASE_URL = "sqlite:///:memory:"

@pytest.fixture(name="db_session")
def fixture_db_session():
    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)

def test_paper_model_creation(db_session):
    """Verifies that we can insert papers and retrieve them from the database."""
    paper = Paper(
        arxiv_id="1706.03762",
        title="Attention Is All You Need",
        summary="The dominant sequence transduction models are based on complex recurrent or convolutional neural networks...",
        published_date=datetime.date(2017, 6, 12),
        authors="Ashish Vaswani, Noam Shazeer, Niki Parmar",
        primary_category="cs.CL",
        all_categories="cs.CL, cs.LG",
        citation_count=45,
        reference_count=12
    )
    db_session.add(paper)
    db_session.commit()

    retrieved = db_session.query(Paper).filter(Paper.arxiv_id == "1706.03762").first()
    assert retrieved is not None
    assert retrieved.title == "Attention Is All You Need"
    assert retrieved.citation_count == 45

def test_paper_embedding_relation(db_session):
    """Verifies that we can attach embeddings to papers and retrieve them via relationship."""
    paper = Paper(
        arxiv_id="2006.11239",
        title="Denoising Diffusion Probabilistic Models",
        summary="We present high quality image synthesis results using diffusion probabilistic models...",
        published_date=datetime.date(2020, 6, 19),
        authors="Jonathan Ho, Ajay Jain, Pieter Abbeel",
        primary_category="cs.LG",
        all_categories="cs.LG, cs.CV, stat.ML",
        citation_count=100,
        reference_count=35
    )
    db_session.add(paper)
    db_session.flush()

    embedding_vec = get_embedding(paper.summary)
    embedding_entry = PaperEmbedding(
        paper_id=paper.arxiv_id,
        embedding=embedding_vec
    )
    db_session.add(embedding_entry)
    db_session.commit()

    retrieved = db_session.query(Paper).filter(Paper.arxiv_id == "2006.11239").first()
    assert retrieved.embedding_relation is not None
    assert len(retrieved.embedding_relation.embedding) == 384
