import logging
import os
import random
import time

import requests
from sqlalchemy.orm import Session

from signalzero.models.models import Paper, PaperEmbedding
from signalzero.services.database import get_neo4j, get_redis

logger = logging.getLogger("SignalZero.Ingestion")

# Try to import sentence-transformers for local embeddings
try:
    from sentence_transformers import SentenceTransformer
    embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
    logger.info("SentenceTransformer (all-MiniLM-L6-v2) loaded successfully.")
except Exception as e:
    embedding_model = None
    logger.warning(f"SentenceTransformer not available ({e}). Using mock embeddings.")

def get_embedding(text: str) -> list[float]:
    """Generates 384-dimensional embedding using MiniLM or mock random vector fallback."""
    if embedding_model is not None:
        try:
            emb = embedding_model.encode(text)
            return emb.tolist()
        except Exception as e:
            logger.error(f"Error generating embedding: {e}. Falling back to mock vector.")

    # Mock fallback: 384 floats normalized
    vec = [random.uniform(-0.1, 0.1) for _ in range(384)]
    norm = sum(x*x for x in vec) ** 0.5
    return [x/norm for x in vec]

def fetch_arxiv_papers(limit: int = 50) -> list[dict]:
    """Fetches recent papers from arXiv REST API based on configured query."""
    import arxiv

    from signalzero.utils.config import settings
    logger.info(f"Querying arXiv for up to {limit} recent papers with query: {settings.ARXIV_QUERY}")
    # arXiv client v4.0.0+ is more sensitive to rate limits.
    # We increase delay_seconds and use a robust retry strategy.
    client = arxiv.Client(delay_seconds=5.0, num_retries=5)
    search = arxiv.Search(
        query=settings.ARXIV_QUERY,
        max_results=limit,
        sort_by=arxiv.SortCriterion.SubmittedDate
    )

    results = []
    try:
        # arXiv client yields papers. We attempt to fetch them with exponential backoff.
        max_retries = 5
        for attempt in range(max_retries):
            try:
                # Re-fetch generator on each retry if needed
                papers_generator = client.results(search)
                # Eagerly convert to list to trigger API requests and catch errors here
                papers_list = list(papers_generator)
                break
            except Exception as e:
                err_str = str(e)
                # If we hit 429 or other connection issues, wait and retry
                if "429" in err_str or "too many requests" in err_str.lower() or attempt < max_retries - 1:
                    wait_time = (5 ** attempt) + random.uniform(5.0, 10.0)
                    logger.warning(f"arXiv API issue ({err_str}). Retrying in {wait_time:.2f} seconds... (Attempt {attempt+1}/{max_retries})")
                    time.sleep(wait_time)
                    if attempt == max_retries - 1:
                        logger.error(f"Failed to fetch arXiv papers after {max_retries} attempts.")
                        raise e
                else:
                    raise e

        for paper in papers_list:
            authors_str = ", ".join(author.name for author in paper.authors)
            results.append({
                "arxiv_id": paper.get_short_id(),
                "title": paper.title,
                "summary": paper.summary,
                "published_date": paper.published.date(),
                "authors": authors_str,
                "primary_category": paper.primary_category,
                "all_categories": ", ".join(paper.categories)
            })
    except Exception as e:
        logger.error(f"Error fetching from arXiv API: {e}")

    logger.info(f"Fetched {len(results)} papers from arXiv.")
    return results

def enrich_with_semantic_scholar(arxiv_id: str) -> dict:
    """Enriches paper with citation metrics and field information from Semantic Scholar."""
    s2_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
    if not s2_key:
        logger.info(f"Skipping Semantic Scholar enrichment for {arxiv_id} (no API key).")
        return {
            "citationCount": 0,
            "referenceCount": 0,
            "citations": [],
            "references": [],
            "s2FieldsOfStudy": [],
            "tldr": None
        }

    url = f"https://api.semanticscholar.org/graph/v1/paper/arXiv:{arxiv_id}"
    params = {"fields": "citationCount,referenceCount,citations,references,s2FieldsOfStudy,tldr"}

    # Check Redis cache first to avoid API limits
    redis_client = get_redis()
    cache_key = f"s2_cache:{arxiv_id}"
    try:
        import json
        cached = redis_client.get(cache_key)
        if cached:
            logger.info(f"Semantic Scholar cache hit for arXiv ID: {arxiv_id}")
            return json.loads(cached)
    except Exception as e:
        logger.warning(f"Failed to query Redis cache: {e}")

    # No cache, request API with retries
    logger.info(f"Requesting Semantic Scholar API for arXiv ID: {arxiv_id}")
    max_retries = 3
    for attempt in range(max_retries):
        try:
            headers = {}
            s2_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
            if s2_key:
                headers["x-api-key"] = s2_key
                time.sleep(0.5)  # Fast if we have a key
            else:
                # 100 req / 5 mins -> 3.0 sec per request to avoid limit
                time.sleep(3.1)

            res = requests.get(url, params=params, headers=headers, timeout=15)
            if res.status_code == 200:
                data = res.json()
                try:
                    redis_client.set(cache_key, json.dumps(data), ex=604800)
                except Exception as e:
                    logger.warning(f"Failed to write to Redis cache: {e}")
                return data
            elif res.status_code == 429:
                logger.warning(f"Semantic Scholar API Rate Limit hit (attempt {attempt+1}/{max_retries}). Sleeping 60s.")
                time.sleep(60.0)
            else:
                logger.warning(f"Semantic Scholar returned status {res.status_code} for arXiv:{arxiv_id}")
                break  # Don't retry on 404, 500, etc.
        except Exception as e:
            logger.error(f"Error fetching from Semantic Scholar: {e}")
            time.sleep(5.0)

    return {
        "citationCount": 0,
        "referenceCount": 0,
        "citations": [],
        "references": [],
        "s2FieldsOfStudy": [],
        "tldr": None
    }

def update_neo4j_citation_graph(paper_data: dict, s2_data: dict):
    """Inserts nodes and CITES relations in Neo4j citation graph."""
    driver = get_neo4j()
    if driver is None:
        return

    arxiv_id = paper_data["arxiv_id"]
    title = paper_data["title"]
    pub_date = str(paper_data["published_date"])
    primary_field = paper_data["primary_category"]

    # Merge paper node
    merge_query = """
    MERGE (p:Paper {arxiv_id: $arxiv_id})
    SET p.title = $title, p.published_date = $pub_date, p.primary_field = $primary_field
    """
    params = {
        "arxiv_id": arxiv_id,
        "title": title,
        "pub_date": pub_date,
        "primary_field": primary_field
    }

    try:
        driver.execute_query(merge_query, params)

        # Add outbound CITES references if they exist
        references = s2_data.get("references", [])
        if references:
            logger.info(f"Adding {len(references)} CITES links in Neo4j for paper {arxiv_id}")
            for ref in references:
                ref_arxiv_id = ref.get("externalIds", {}).get("ArXiv")
                if ref_arxiv_id:
                    ref_title = ref.get("title", "Unknown Ref")
                    ref_field = ref.get("s2FieldsOfStudy", [{"category": "cs.LG"}])[0].get("category", "cs.LG") if ref.get("s2FieldsOfStudy") else "cs.LG"

                    ref_query = """
                    MERGE (ref:Paper {arxiv_id: $ref_arxiv_id})
                    ON CREATE SET ref.title = $ref_title, ref.primary_field = $ref_field
                    WITH ref
                    MATCH (p:Paper {arxiv_id: $arxiv_id})
                    MERGE (p)-[:CITES]->(ref)
                    """
                    driver.execute_query(ref_query, {
                        "arxiv_id": arxiv_id,
                        "ref_arxiv_id": ref_arxiv_id,
                        "ref_title": ref_title,
                        "ref_field": ref_field
                    })
    except Exception as e:
        logger.error(f"Error updating Neo4j citation graph: {e}")

def ingest_daily_papers(db: Session, limit: int = 20):
    """Runs the daily pipeline: fetch, enrich, embed, store."""
    logger.info("Starting Daily Ingestion Pipeline...")
    raw_papers = fetch_arxiv_papers(limit=limit)

    ingested_count = 0
    for p_data in raw_papers:
        arxiv_id = p_data["arxiv_id"]

        # Check if already exists in SQL database
        existing = db.query(Paper).filter(Paper.arxiv_id == arxiv_id).first()

        # Enrich with Semantic Scholar metrics
        s2_data = enrich_with_semantic_scholar(arxiv_id)

        if existing:
            logger.info(f"Paper {arxiv_id} already exists. Updating metrics.")
            existing.citation_count = s2_data.get("citation_count", existing.citation_count)
            existing.reference_count = s2_data.get("reference_count", existing.reference_count)
            db.commit()
            # Update graph anyway to catch new citation links
            update_neo4j_citation_graph(p_data, s2_data)
            continue

        # Build Paper Object
        paper = Paper(
            arxiv_id=arxiv_id,
            title=p_data["title"],
            summary=p_data["summary"],
            published_date=p_data["published_date"],
            authors=p_data["authors"],
            primary_category=p_data["primary_category"],
            all_categories=p_data["all_categories"],
            semantic_scholar_id=s2_data.get("paperId"),
            citation_count=s2_data.get("citationCount", 0),
            reference_count=s2_data.get("referenceCount", 0)
        )

        db.add(paper)
        db.flush()  # gets id

        # Embed abstract and store vector
        embedding = get_embedding(p_data["summary"])
        paper_emb = PaperEmbedding(
            paper_id=arxiv_id,
            embedding=embedding
        )
        db.add(paper_emb)
        db.commit()

        # Update Neo4j citation graph
        update_neo4j_citation_graph(p_data, s2_data)

        ingested_count += 1
        logger.info(f"Ingested & indexed paper: {p_data['title']} (arxiv:{arxiv_id})")

    logger.info(f"Daily Ingestion Pipeline finished. Ingested {ingested_count} new papers.")

    # Execute data retention pruning
    try:
        from signalzero.services.database import prune_historical_data
        from signalzero.utils.config import settings
        prune_historical_data(db, settings.DATA_RETENTION_DAYS)
    except Exception as prune_err:
        logger.error(f"Error executing post-ingestion database pruning: {prune_err}")

    return ingested_count
