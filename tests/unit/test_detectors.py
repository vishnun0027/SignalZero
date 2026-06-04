import datetime
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from signalzero.core.detectors.convergent import run_convergent_discovery_detector
from signalzero.core.detectors.cross_field import (
    classify_citation_intent,
    compute_relative_zscore,
    run_cross_field_detector,
)
from signalzero.core.detectors.vocab_drift import extract_ngrams
from signalzero.models.models import CrossFieldBaseline, Paper, PaperEmbedding
from signalzero.services.database import Base, InMemoryNeo4j, InMemoryRedis

TEST_DATABASE_URL = "sqlite:///:memory:"

@pytest.fixture(name="db_session")
def fixture_db_session():
    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()

    # Initialize in-memory database connections for the tests
    # Force mock DB state
    from signalzero.services import database
    database.redis_client = InMemoryRedis()
    database.neo4j_driver = InMemoryNeo4j()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)

def test_cross_field_detector_mock(db_session):
    """Verifies cross-field citation detector v2 returns signals with influential
    metadata, intent classification, and Z-score using InMemoryNeo4j graph mock.
    """
    signals = run_cross_field_detector(db_session)
    # The default mock returns 2 papers: Attention Is All You Need, Denoising Diffusion
    assert len(signals) == 2
    assert any(s["type"] == "cross_field" for s in signals)
    assert any("Attention" in s["trigger_details"]["title"] for s in signals)

    # v2: Verify new fields are present in trigger_details
    for signal in signals:
        td = signal["trigger_details"]
        assert "influential_field_spread" in td
        assert "methodology_ratio" in td
        assert "z_score" in td
        assert "origin_field" in td
        assert "influential_count" in td
        assert "effective_spread" in td

    # v2: Verify confidence is computed (not zero or None)
    for signal in signals:
        assert signal["confidence"] > 0.0
        assert signal["confidence"] <= 0.99


def test_citation_intent_classifier():
    """Tests the keyword heuristic classifier for citation context intent."""
    # Methodology-indicating contexts
    assert classify_citation_intent(
        "We adopt the transformer architecture from Vaswani et al."
    ) == "methodology"
    assert classify_citation_intent(
        "We use the diffusion framework for image generation"
    ) == "methodology"
    assert classify_citation_intent(
        "Our model is based on the attention mechanism from this paper"
    ) == "methodology"
    assert classify_citation_intent(
        "We fine-tune the pretrained encoder following their approach"
    ) == "methodology"
    assert classify_citation_intent(
        "We extend the original architecture with a novel decoder"
    ) == "methodology"

    # Background-indicating contexts
    assert classify_citation_intent(
        "Previous work on attention has shown improvements in NLP tasks"
    ) == "background"
    assert classify_citation_intent(
        "Related work on generative models has demonstrated promising results"
    ) == "background"
    assert classify_citation_intent(
        "A comprehensive survey of transformer architectures was presented"
    ) == "background"
    assert classify_citation_intent(
        "Existing methods have shown that pre-training is effective"
    ) == "background"

    # Unknown / empty contexts
    assert classify_citation_intent("") == "unknown"
    assert classify_citation_intent(
        "The paper presents interesting results on benchmark X"
    ) == "unknown"


def test_relative_zscore_with_baseline(db_session):
    """Tests Z-score computation with a stored baseline."""
    # Insert a baseline for cs.CL with mean=2.0, stddev=0.8
    baseline = CrossFieldBaseline(
        origin_field="cs.CL",
        avg_field_spread=2.0,
        stddev_field_spread=0.8,
        paper_count=50,
        computed_at=datetime.datetime.now(datetime.UTC)
    )
    db_session.add(baseline)
    db_session.commit()

    # A paper with field_spread=4 in cs.CL should have Z = (4-2)/0.8 = 2.5
    z = compute_relative_zscore(4.0, "cs.CL", db_session)
    assert abs(z - 2.5) < 0.01

    # A paper with field_spread=2 should have Z = (2-2)/0.8 = 0.0
    z = compute_relative_zscore(2.0, "cs.CL", db_session)
    assert abs(z - 0.0) < 0.01

    # A paper with field_spread=1 should have negative Z
    z = compute_relative_zscore(1.0, "cs.CL", db_session)
    assert z < 0


def test_relative_zscore_without_baseline(db_session):
    """Tests Z-score fallback when no baseline exists for the field."""
    # No baseline for "q-bio" — should use conservative default (mean=1.5, stddev=1.0)
    z = compute_relative_zscore(4.0, "q-bio", db_session)
    assert abs(z - 2.5) < 0.01  # (4-1.5)/1.0 = 2.5


def test_cross_field_confidence_ordering(db_session):
    """Verifies that the Transformer paper (broader cross-field reach, more influential
    citations, more methodology contexts) gets higher confidence than the Diffusion paper.
    """
    signals = run_cross_field_detector(db_session)
    assert len(signals) == 2

    transformer_signal = next(s for s in signals if "Attention" in s["trigger_details"]["title"])
    diffusion_signal = next(s for s in signals if "Diffusion" in s["trigger_details"]["title"])

    # Transformer should score higher — more fields, more influential citations,
    # higher methodology ratio in its mock contexts
    assert transformer_signal["confidence"] >= diffusion_signal["confidence"]


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
