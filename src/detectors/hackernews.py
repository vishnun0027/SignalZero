import json
import logging
import datetime
import requests
import time
from sqlalchemy.orm import Session
from src.database import get_redis
from src.models import Signal, Paper

logger = logging.getLogger("SignalZero.Detector.HackerNews")

def run_hn_detector(db: Session, lookback_days: int = 14) -> list[dict]:
    """Scans HackerNews Algolia search API for mentions of recently ingested arXiv papers.
    Flags papers gaining community points or comments as emerging community signals.
    """
    logger.info("Running HackerNews Community Signal Detector...")
    redis_client = get_redis()
    
    # 1. Fetch papers published in the last lookback_days
    cutoff_date = datetime.date.today() - datetime.timedelta(days=lookback_days)
    recent_papers = db.query(Paper).filter(Paper.published_date >= cutoff_date).all()
    
    if not recent_papers:
        logger.warning("No papers in the lookback window to scan. Skipping HN detector.")
        return []
        
    logger.info(f"Scanning HackerNews for {len(recent_papers)} recent papers...")
    
    results = []
    
    for paper in recent_papers:
        arxiv_id = paper.arxiv_id
        
        # Check cache first to avoid slamming the Algolia API
        cache_key = f"hn_search_cache:{arxiv_id}"
        cached = None
        try:
            cached = redis_client.get(cache_key)
        except Exception as cache_err:
            logger.warning(f"Failed to query Redis cache: {cache_err}")
            
        if cached:
            # We skip querying if we already checked today and found nothing
            if cached == "not_found":
                continue
            try:
                hn_data = json.loads(cached)
            except Exception:
                hn_data = None
        else:
            # Not cached, query Algolia HN API
            url = "https://hn.algolia.com/api/v1/search"
            params = {"query": arxiv_id, "tags": "story"}
            
            try:
                # Politeness sleep to avoid spamming Algolia API
                time.sleep(0.5)
                res = requests.get(url, params=params, timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    hits = data.get("hits", [])
                    if hits:
                        # Pick story with highest points
                        top_hit = max(hits, key=lambda h: h.get("points", 0) or 0)
                        hn_data = {
                            "story_id": top_hit.get("objectID"),
                            "title": top_hit.get("title"),
                            "points": top_hit.get("points", 0) or 0,
                            "comments": top_hit.get("num_comments", 0) or 0,
                            "url": f"https://news.ycombinator.com/item?id={top_hit.get('objectID')}",
                            "created_at": top_hit.get("created_at")
                        }
                        # Cache for 1 day
                        try:
                            redis_client.set(cache_key, json.dumps(hn_data), ex=86400)
                        except Exception:
                            pass
                    else:
                        hn_data = None
                        # Cache negative result for 4 hours
                        try:
                            redis_client.set(cache_key, "not_found", ex=14400)
                        except Exception:
                            pass
                else:
                    logger.warning(f"HackerNews Algolia API returned status {res.status_code} for arxiv:{arxiv_id}")
                    hn_data = None
            except Exception as api_err:
                logger.error(f"Error querying HackerNews Algolia API: {api_err}")
                hn_data = None
                
        # If paper has traction on HN, log a signal
        if hn_data:
            points = hn_data.get("points", 0)
            comments = hn_data.get("comments", 0)
            
            # Traction Threshold: points >= 15 or comments >= 10
            if points >= 15 or comments >= 10:
                # Compute confidence score: base 0.4 + scaling with points/comments
                confidence = min(0.99, 0.4 + (points / 150.0) * 0.4 + (comments / 100.0) * 0.2)
                
                trigger_details = {
                    "arxiv_id": arxiv_id,
                    "paper_title": paper.title,
                    "hn_title": hn_data.get("title"),
                    "hn_url": hn_data.get("url"),
                    "points": points,
                    "comments": comments,
                    "hn_created_at": hn_data.get("created_at")
                }
                
                results.append({
                    "type": "hn_community",
                    "arxiv_id": arxiv_id,
                    "confidence": confidence,
                    "trigger_details": trigger_details
                })
                
                # Prevent duplicate signals in the last 14 days
                cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=14)
                existing_signal = db.query(Signal).filter(
                    Signal.type == "hn_community",
                    Signal.trigger_details.like(f'%"{arxiv_id}"%'),
                    Signal.created_at >= cutoff
                ).first()
                
                if not existing_signal:
                    signal = Signal(
                        type="hn_community",
                        confidence=confidence,
                        trigger_details=json.dumps(trigger_details),
                        status="emerging"
                    )
                    db.add(signal)
                    db.commit()
                    logger.info(f"Logged new HackerNews community signal for paper: '{paper.title}' (points: {points}, comments: {comments})")
                    
    return results
