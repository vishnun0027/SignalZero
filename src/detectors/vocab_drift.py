import re
import json
import logging
import datetime
from typing import Any
from sqlalchemy.orm import Session
from src.database import get_redis
from src.models import Signal, Paper

logger = logging.getLogger("SignalZero.Detector.VocabDrift")

# Fallback drift detector in case River ADWIN is unavailable
try:
    from river.drift import ADWIN
    HAS_RIVER = True
    logger.info("River ADWIN drift detector imported successfully.")
except ImportError:
    HAS_RIVER = False
    logger.warning("River package not available. Using pure-Python z-score drift detector.")

class PurePythonDriftDetector:
    """Fallback drift detector that flags statistically significant upwards spikes in term frequency."""
    def __init__(self, window_size: int = 14, threshold_multiplier: float = 2.5):
        self.history: list[float] = []
        self.window_size = window_size
        self.threshold_multiplier = threshold_multiplier

    def update(self, val: float) -> bool:
        self.history.append(val)
        if len(self.history) > self.window_size:
            self.history.pop(0)
        
        # Need at least 2 days of history to detect drift
        if len(self.history) < 2:
            return False
            
        # Look at history excluding current value
        prior = self.history[:-1]
        mean = sum(prior) / len(prior)
        variance = sum((x - mean) ** 2 for x in prior) / len(prior)
        std = variance ** 0.5
        
        # If standard deviation is 0, check if current is significantly higher than mean
        if std == 0:
            return val > mean + 1.0
            
        z_score = (val - mean) / std
        # Only flag positive drift (acceleration of term usage)
        return z_score > self.threshold_multiplier

# Stopwords to filter out non-technical/common words
STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are", "arent", "as", "at",
    "be", "because", "been", "before", "being", "below", "between", "both", "but", "by", "cant", "cannot", "could",
    "did", "didnt", "do", "does", "doesnt", "doing", "dont", "down", "during", "each", "few", "for", "from", "further",
    "had", "hadnt", "has", "hasnt", "have", "havent", "having", "he", "hed", "hell", "hes", "her", "here", "heres",
    "hers", "herself", "him", "himself", "his", "how", "hows", "i", "id", "ill", "im", "ive", "if", "in", "into", "is",
    "isnt", "it", "its", "itself", "lets", "me", "more", "most", "mustnt", "my", "myself", "no", "nor", "not", "of", "off",
    "on", "once", "only", "or", "other", "ought", "our", "ours", "ourselves", "out", "over", "own", "same", "shant", "she",
    "shed", "shell", "shes", "should", "shouldnt", "so", "some", "such", "than", "that", "thats", "the", "their", "theirs",
    "them", "themselves", "then", "there", "theres", "these", "they", "theyd", "theyll", "theyre", "theyve", "this",
    "those", "through", "to", "too", "under", "until", "up", "very", "was", "wasnt", "we", "wed", "well", "were", "weve",
    "werent", "what", "whats", "when", "whens", "where", "wheres", "which", "while", "who", "whos", "whom", "why", "whys",
    "with", "wont", "would", "wouldnt", "you", "youd", "youll", "youre", "youve", "your", "yours", "yourself", "yourselves",
    # Research-specific generic terms to filter noise
    "paper", "method", "proposed", "propose", "results", "approach", "model", "models", "algorithm", "dataset", "task",
    "performance", "state", "art", "accuracy", "experimental", "experiments", "evaluation", "framework", "system"
}

def clean_and_tokenize(text: str) -> list[str]:
    """Cleans abstracts, removes punctuation, lowercase conversion, and splits words."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    tokens = text.split()
    return [t for t in tokens if t not in STOPWORDS and len(t) > 2]

def extract_ngrams(abstracts: list[str], n_values: list[int] = [1, 2, 3]) -> dict[str, int]:
    """Extracts cleaned unigrams, bigrams, and trigrams from a batch of abstracts."""
    ngram_counts: dict[str, int] = {}
    for abstract in abstracts:
        tokens = clean_and_tokenize(abstract)
        for n in n_values:
            for i in range(len(tokens) - n + 1):
                ngram = " ".join(tokens[i : i + n])
                # Filter out n-grams containing numeric symbols or specific invalid strings
                if not re.search(r"\d", ngram):
                    ngram_counts[ngram] = ngram_counts.get(ngram, 0) + 1
    return ngram_counts

def run_vocab_emergence_detector(db: Session, lookback_days: int = 14) -> list[dict]:
    """Extracts recent term frequencies, feeds them to ADWIN/Z-Score, and flags emergent terms."""
    logger.info("Running Vocabulary Emergence Detector...")
    redis_client = get_redis()
    
    # Retrieve abstracts published in the last lookback_days
    cutoff_date = datetime.date.today() - datetime.timedelta(days=lookback_days)
    recent_papers = db.query(Paper).filter(Paper.published_date >= cutoff_date).all()
    
    if not recent_papers:
        logger.warning("No papers in database to extract terms. Skipping detector.")
        return []
        
    abstracts = [str(p.summary) for p in recent_papers]
    ngrams = extract_ngrams(abstracts, n_values=[1, 2, 3])
    
    # Filter for technical neologisms: term must appear multiple times to be a candidate
    # NOTE: Threshold is 2 for early phase (small dataset). Raise to 5+ once 1000+ papers are ingested.
    candidates = {term: count for term, count in ngrams.items() if count >= 2}
    logger.info(f"Extracted {len(candidates)} candidate technical neologisms.")
    
    results = []
    today_str = str(datetime.date.today())
    
    for term, count in candidates.items():
        # Redis key pattern for vocabulary histories: vocab_freq:{term}
        redis_key = f"vocab_freq:{term}"
        
        # Get historical frequencies from Redis
        try:
            history_data = redis_client.get(redis_key)
            if history_data:
                history = json.loads(history_data)
            else:
                history = []
        except Exception:
            history = []
            
        # Append today's term frequency
        # Standardize term frequency as percentage of total abstract word count
        total_tokens = sum(len(clean_and_tokenize(a)) for a in abstracts)
        rel_freq = (count / total_tokens) * 10000 if total_tokens > 0 else 0  # frequency per 10k words
        
        # Check if we already recorded a value for today
        if not history or history[-1]["date"] != today_str:
            history.append({"date": today_str, "val": rel_freq})
            # Keep last 30 days
            if len(history) > 30:
                history.pop(0)
            # Store back to Redis
            try:
                redis_client.set(redis_key, json.dumps(history))
            except Exception:
                pass

        # Run drift detection
        drift_detected = False
        vals = [h["val"] for h in history]
        
        detector: Any
        if HAS_RIVER:
            detector = ADWIN()
            for v in vals:
                detector.update(v)
            # River's ADWIN drift is true when distribution changes
            drift_detected = detector.drift_detected
        else:
            detector = PurePythonDriftDetector()
            for v in vals:
                drift_detected = detector.update(v)

        # Signal conditions:
        # 1. Drift detected (statistically significant shift in frequency distribution)
        # 2. Latest value is above historical average (positive drift)
        # 3. Growth rate is high (e.g. current frequency is > 2x the historical mean)
        if drift_detected and len(vals) >= 2:
            mean_val = sum(vals[:-1]) / len(vals[:-1]) if len(vals) > 1 else 0
            if rel_freq > mean_val * 1.8:
                confidence = min(0.99, 0.5 + (rel_freq - mean_val) / (mean_val + 1e-5) * 0.1)
                
                trigger_details = {
                    "term": term,
                    "count": count,
                    "frequency_history": history,
                    "mean_prior": mean_val,
                    "current_rel_freq": rel_freq
                }
                
                results.append({
                    "type": "vocab_drift",
                    "term": term,
                    "confidence": confidence,
                    "trigger_details": trigger_details
                })
                
                # Prevent duplicate signals for the same term in the last 7 days
                cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=7)
                existing_signal = db.query(Signal).filter(
                    Signal.type == "vocab_drift",
                    Signal.trigger_details.like(f'%"{term}"%'),
                    Signal.created_at >= cutoff
                ).first()
                
                if not existing_signal:
                    signal = Signal(
                        type="vocab_drift",
                        confidence=confidence,
                        trigger_details=json.dumps(trigger_details),
                        status="emerging"
                    )
                    db.add(signal)
                    db.commit()
                    logger.info(f"Logged emergent vocabulary term: '{term}' (confidence: {confidence:.2f})")
                    
    return results
