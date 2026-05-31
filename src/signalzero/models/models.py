import datetime

from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from signalzero.services.database import Base
from signalzero.utils.config import settings

# Conditional imports for pgvector based on availability and DB backend
try:
    from pgvector.sqlalchemy import Vector
    HAS_PGVECTOR = True
except ImportError:
    HAS_PGVECTOR = False

# Use Vector type if pgvector is available and we're not on SQLite, else fall back to JSON
if HAS_PGVECTOR and not settings.DATABASE_URL.startswith("sqlite"):
    EmbeddingType = Vector(384)  # sentence-transformers/all-MiniLM-L6-v2 produces 384-dim embeddings
else:
    from sqlalchemy import JSON
    EmbeddingType = JSON

class Paper(Base):
    __tablename__ = "papers"

    id = Column(Integer, primary_key=True, index=True)
    arxiv_id = Column(String(50), unique=True, index=True, nullable=False)
    title = Column(String(255), nullable=False)
    summary = Column(Text, nullable=False)  # The abstract
    published_date = Column(Date, index=True, nullable=False)
    authors = Column(Text, nullable=False)  # Stored as comma-separated or JSON string
    primary_category = Column(String(50), index=True, nullable=False)
    all_categories = Column(String(255), nullable=False)
    semantic_scholar_id = Column(String(100), nullable=True)
    citation_count = Column(Integer, default=0)
    reference_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.UTC))

    # Relationships
    embedding_relation = relationship("PaperEmbedding", back_populates="paper", uselist=False, cascade="all, delete-orphan")

class PaperEmbedding(Base):
    __tablename__ = "paper_embeddings"

    id = Column(Integer, primary_key=True, index=True)
    paper_id = Column(String(50), ForeignKey("papers.arxiv_id", ondelete="CASCADE"), unique=True, nullable=False)
    embedding = Column(EmbeddingType, nullable=False)

    # Relationships
    paper = relationship("Paper", back_populates="embedding_relation")

class Signal(Base):
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(String(50), index=True, nullable=False)  # 'cross_field', 'vocab_drift', 'convergent'
    confidence = Column(Float, nullable=False)
    trigger_details = Column(Text, nullable=False)  # JSON string detailing the specific metrics triggering this
    brief = Column(Text, nullable=True)  # LLM-generated brief
    status = Column(String(50), index=True, default="emerging")  # 'emerging', 'growing', 'mainstream', 'false_positive'
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.UTC))
    updated_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.UTC), onupdate=lambda: datetime.datetime.now(datetime.UTC))
