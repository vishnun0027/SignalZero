import datetime
import json
import logging

import numpy as np
from sqlalchemy.orm import Session

from signalzero.models.models import Paper, PaperEmbedding, Signal

logger = logging.getLogger("SignalZero.Detector.Convergent")

def cosine_similarity(v1, v2):
    """Calculates cosine similarity between two numeric lists/vectors."""
    arr1 = np.array(v1)
    arr2 = np.array(v2)
    norm1 = np.linalg.norm(arr1)
    norm2 = np.linalg.norm(arr2)
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return float(np.dot(arr1, arr2) / (norm1 * norm2))

def check_author_independence(papers: list[Paper]) -> bool:
    """Returns True if there is no author overlap among all papers in the group (indicating independent discovery)."""
    author_sets = []
    for paper in papers:
        # Normalize author names to lower-case set of last names (less sensitive to format details)
        names = []
        for full_name in paper.authors.split(","):
            parts = full_name.strip().lower().split()
            if parts:
                names.append(parts[-1])  # Keep last name
        author_sets.append(set(names))

    # Check pairwise intersection
    for i in range(len(author_sets)):
        for j in range(i + 1, len(author_sets)):
            if author_sets[i].intersection(author_sets[j]):
                return False
    return True


def run_convergent_discovery_detector(db: Session, lookback_days: int | None = None, similarity_threshold: float | None = None) -> list[dict]:
    """Retrieves recent paper embeddings, clusters them by cosine similarity,
    verifies authorship independence, checks for concept novelty, and saves signals.
    """
    from signalzero.utils.config import settings

    if lookback_days is None:
        lookback_days = settings.CONVERGENT_LOOKBACK_DAYS
    if similarity_threshold is None:
        similarity_threshold = settings.CONVERGENT_SIMILARITY_THRESHOLD

    min_cluster_size = settings.CONVERGENT_MIN_CLUSTER_SIZE

    logger.info(f"Running Convergent Discovery Detector (lookback: {lookback_days} days, sim_threshold: {similarity_threshold})...")

    # 1. Fetch recent papers and their embeddings
    cutoff_date = datetime.date.today() - datetime.timedelta(days=lookback_days)
    recent_entries = db.query(Paper, PaperEmbedding).join(
        PaperEmbedding, Paper.arxiv_id == PaperEmbedding.paper_id
    ).filter(Paper.published_date >= cutoff_date).all()

    if len(recent_entries) < min_cluster_size:
        logger.warning(f"Fewer than {min_cluster_size} recent papers found ({len(recent_entries)}). Skipping convergent detector.")
        return []

    logger.info(f"Loaded {len(recent_entries)} recent papers with embeddings for clustering.")

    # 2. Extract lists
    papers = [item[0] for item in recent_entries]
    # Handle DB embeddings (JSON serialized list in SQLite vs List/Object in PostgreSQL)
    embeddings = []
    for item in recent_entries:
        emb = item[1].embedding
        if isinstance(emb, str):
            embeddings.append(json.loads(emb))
        else:
            embeddings.append(list(emb))

    # 3. Simple threshold-based clustering (single linkage / DBSCAN-like)
    n = len(papers)
    adj_matrix = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            sim = cosine_similarity(embeddings[i], embeddings[j])
            if sim >= similarity_threshold:
                adj_matrix[i, j] = 1
                adj_matrix[j, i] = 1

    # Find connected components (clusters)
    visited = set()
    clusters = []

    def dfs(node, current_cluster):
        visited.add(node)
        current_cluster.append(node)
        for neighbor in range(n):
            if adj_matrix[node, neighbor] == 1 and neighbor not in visited:
                dfs(neighbor, current_cluster)

    for i in range(n):
        if i not in visited:
            cluster_indices: list[int] = []
            dfs(i, cluster_indices)
            if len(cluster_indices) >= min_cluster_size:  # Enforce configurable cluster size
                clusters.append([papers[idx] for idx in cluster_indices])

    logger.info(f"Found {len(clusters)} candidate semantic clusters of size >= {min_cluster_size}.")

    results = []
    for cluster in clusters:
        # 4. Check for independent research groups
        if not check_author_independence(cluster):
            logger.info(f"Cluster with papers {[p.arxiv_id for p in cluster]} failed independence check (shared authors).")
            continue

        # 5. Evaluate Novelty
        # Retrieve older papers (prior to cutoff)
        older_entries = db.query(Paper, PaperEmbedding).join(
            PaperEmbedding, Paper.arxiv_id == PaperEmbedding.paper_id
        ).filter(Paper.published_date < cutoff_date).limit(100).all()

        novelty_score = 1.0
        if older_entries:
            # Calculate centroid of cluster
            cluster_embs = []
            for paper in cluster:
                # Find matching embedding in recent_entries
                for r_paper, r_emb in recent_entries:
                    if r_paper.arxiv_id == paper.arxiv_id:
                        emb_val = r_emb.embedding
                        cluster_embs.append(json.loads(emb_val) if isinstance(emb_val, str) else list(emb_val))
                        break
            centroid = np.mean(cluster_embs, axis=0)

            # Find max similarity of centroid to any historical paper
            max_hist_sim = 0.0
            for _o_paper, o_emb in older_entries:
                o_emb_val = o_emb.embedding
                o_emb_list = json.loads(o_emb_val) if isinstance(o_emb_val, str) else list(o_emb_val)
                sim = cosine_similarity(centroid, o_emb_list)
                if sim > max_hist_sim:
                    max_hist_sim = sim

            # Novelty: higher when similarity to historical papers is lower
            novelty_score = max(0.0, 1.0 - max_hist_sim)

        # 6. Score confidence
        # Confidence is higher for larger clusters and higher novelty
        cluster_size_score = min(1.0, len(cluster) / 10.0)  # max score at size 10
        confidence = min(0.99, 0.4 + cluster_size_score * 0.3 + novelty_score * 0.3)

        trigger_details = {
            "papers": [{"arxiv_id": p.arxiv_id, "title": p.title, "authors": p.authors, "published_date": str(p.published_date)} for p in cluster],
            "cluster_size": len(cluster),
            "novelty_score": novelty_score
        }

        results.append({
            "type": "convergent",
            "confidence": confidence,
            "trigger_details": trigger_details
        })

        # Check if already logged (avoid logging same cluster again)
        # Search by checking if any of the triggering papers are already in a convergent signal in last 30 days
        paper_ids = [p.arxiv_id for p in cluster]
        existing_signal = False
        cutoff = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=30)
        for pid in paper_ids:
            check = db.query(Signal).filter(
                Signal.type == "convergent",
                Signal.trigger_details.like(f'%"{pid}"%'),
                Signal.created_at >= cutoff
            ).first()
            if check:
                existing_signal = True
                break

        if not existing_signal:
            signal = Signal(
                type="convergent",
                confidence=confidence,
                trigger_details=json.dumps(trigger_details),
                status="emerging"
            )
            db.add(signal)
            db.commit()
            logger.info(f"Logged new convergent discovery signal of size {len(cluster)} (confidence: {confidence:.2f})")

    return results
