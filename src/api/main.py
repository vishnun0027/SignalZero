import json
import logging
import uvicorn
from fastapi import FastAPI, Depends, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from src.config import settings
from src.database import get_db, init_postgres, get_neo4j
from src.models import Signal, Paper
from src.ingestion import ingest_daily_papers
from src.detectors.cross_field import run_cross_field_detector
from src.detectors.vocab_drift import run_vocab_emergence_detector
from src.detectors.convergent import run_convergent_discovery_detector
from src.agent.graph import analyze_signal_with_agent

# Initialize logging and database tables
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SignalZero.API")

# Create database tables if they do not exist
init_postgres()
from src.database import engine, Base  # noqa: E402
try:
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables initialized successfully.")
except Exception as e:
    logger.error(f"Error creating database tables: {e}")

app = FastAPI(
    title="SignalZero API",
    description="Weak Signal Intelligence for Emerging AI/ML Technologies",
    version="1.0.0"
)

# CORS Policy - strictly allow localhost domains for testing, no wildcard (*) origins
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Custom Middleware to add Security Headers (Clickjacking protection, XSS protection, No-sniff)
@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'self';"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response

@app.get("/api/health")
def health_check():
    return {"status": "healthy", "env": settings.ENV}

@app.get("/api/signals")
def get_signals(
    status: str = Query(None, description="Filter signals by status (emerging, growing, false_positive)"),
    type: str = Query(None, description="Filter signals by type (cross_field, vocab_drift, convergent)"),
    db: Session = Depends(get_db)
):
    """Retrieves detected weak signals, sorted by date and confidence."""
    query = db.query(Signal)
    if status:
        query = query.filter(Signal.status == status)
    if type:
        query = query.filter(Signal.type == type)
    
    query = query.order_by(Signal.created_at.desc())
    signals = query.all()
    
    # Parse trigger_details JSON for ease of consumption by frontend
    result = []
    for s in signals:
        try:
            details = json.loads(str(s.trigger_details))
        except Exception:
            details = s.trigger_details
            
        result.append({
            "id": s.id,
            "type": s.type,
            "confidence": s.confidence,
            "trigger_details": details,
            "brief": s.brief,
            "status": s.status,
            "created_at": s.created_at,
            "updated_at": s.updated_at
        })
    return result

@app.get("/api/signals/{signal_id}")
def get_signal_detail(signal_id: int, db: Session = Depends(get_db)):
    """Retrieves a single signal in detail."""
    signal = db.query(Signal).filter(Signal.id == signal_id).first()
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found.")
        
    try:
        details = json.loads(str(signal.trigger_details))
    except Exception:
        details = signal.trigger_details
        
    return {
        "id": signal.id,
        "type": signal.type,
        "confidence": signal.confidence,
        "trigger_details": details,
        "brief": signal.brief,
        "status": signal.status,
        "created_at": signal.created_at,
        "updated_at": signal.updated_at
    }

@app.get("/api/graph/{arxiv_id}")
def get_citation_graph(arxiv_id: str):
    """Retrieves citation graph context for visual lineage visualization."""
    driver = get_neo4j()
    if driver is None:
        raise HTTPException(status_code=503, detail="Neo4j graph database offline.")
        
    # Query to fetch immediate citing and cited papers (up to 2 steps)
    query = """
    MATCH (p:Paper {arxiv_id: $arxiv_id})
    OPTIONAL MATCH (citing:Paper)-[r1:CITES]->(p)
    OPTIONAL MATCH (p)-[r2:CITES]->(cited:Paper)
    RETURN p.title AS center_title, p.arxiv_id AS center_id, p.primary_field AS center_field,
           collect(DISTINCT {arxiv_id: citing.arxiv_id, title: citing.title, field: citing.primary_field, type: 'citing'}) AS citing_list,
           collect(DISTINCT {arxiv_id: cited.arxiv_id, title: cited.title, field: cited.primary_field, type: 'cited'}) AS cited_list
    """
    
    nodes = []
    links = []
    seen_nodes = set()
    
    try:
        records, _, _ = driver.execute_query(query, {"arxiv_id": arxiv_id})
        if not records:
            return {"nodes": [], "links": []}
            
        record = records[0]
        center_id = record.get("center_id")
        center_title = record.get("center_title") or "Selected Paper"
        center_field = record.get("center_field") or "cs.LG"
        
        # Add center node
        if center_id:
            nodes.append({"id": center_id, "label": center_title, "group": center_field, "val": 15})
            seen_nodes.add(center_id)
            
            # Process citing papers
            for item in record.get("citing_list", []):
                cid = item.get("arxiv_id")
                if cid and cid not in seen_nodes:
                    nodes.append({"id": cid, "label": item.get("title") or "Citing Paper", "group": item.get("field") or "cs.LG", "val": 10})
                    seen_nodes.add(cid)
                if cid:
                    links.append({"source": cid, "target": center_id, "type": "CITES"})
                    
            # Process cited papers
            for item in record.get("cited_list", []):
                cid = item.get("arxiv_id")
                if cid and cid not in seen_nodes:
                    nodes.append({"id": cid, "label": item.get("title") or "Cited Paper", "group": item.get("field") or "cs.LG", "val": 10})
                    seen_nodes.add(cid)
                if cid:
                    links.append({"source": center_id, "target": cid, "type": "CITES"})
                    
    except Exception as e:
        logger.error(f"Error querying Neo4j for graph visualization: {e}")
        # Build local mock response if in InMemoryNeo4j mode
        if "InMemoryNeo4j" in str(type(driver)):
            nodes = [
                {"id": arxiv_id, "label": "Attention Is All You Need", "group": "cs.CL", "val": 15},
                {"id": "citing_1", "label": "ViT: Vision Transformers", "group": "cs.CV", "val": 10},
                {"id": "citing_2", "label": "BERT: Pre-training", "group": "cs.CL", "val": 10},
                {"id": "cited_1", "label": "Sequence to Sequence", "group": "cs.CL", "val": 8}
            ]
            links = [
                {"source": "citing_1", "target": arxiv_id, "type": "CITES"},
                {"source": "citing_2", "target": arxiv_id, "type": "CITES"},
                {"source": arxiv_id, "target": "cited_1", "type": "CITES"}
            ]
            
    return {"nodes": nodes, "links": links}

@app.get("/api/stats")
def get_stats(db: Session = Depends(get_db)):
    """Computes high-level database metrics for dashboard statistics cards."""
    total_papers = db.query(Paper).count()
    total_signals = db.query(Signal).count()
    emerging = db.query(Signal).filter(Signal.status == "emerging").count()
    growing = db.query(Signal).filter(Signal.status == "growing").count()
    fp = db.query(Signal).filter(Signal.status == "false_positive").count()
    
    # Fetch counts by detector type
    cross_field_count = db.query(Signal).filter(Signal.type == "cross_field").count()
    vocab_drift_count = db.query(Signal).filter(Signal.type == "vocab_drift").count()
    convergent_count = db.query(Signal).filter(Signal.type == "convergent").count()
    
    return {
        "total_papers": total_papers,
        "total_signals": total_signals,
        "by_status": {
            "emerging": emerging,
            "growing": growing,
            "false_positive": fp
        },
        "by_type": {
            "cross_field": cross_field_count,
            "vocab_drift": vocab_drift_count,
            "convergent": convergent_count
        }
    }

def run_detection_pipeline_sync(db: Session):
    """Synchronous pipeline runner: triggers detectors and processes alerts with LangGraph."""
    logger.info("Manual trigger: Starting detectors & agent analysis...")
    # 1. Run detectors (which auto-commit new signals)
    run_cross_field_detector(db)
    run_vocab_emergence_detector(db)
    run_convergent_discovery_detector(db)
    
    # 2. Query all unanalyzed signals in database (brief is null) and run LangGraph agent
    unanalyzed = db.query(Signal).filter(Signal.brief.is_(None)).all()
    logger.info(f"Found {len(unanalyzed)} unanalyzed signals. Running LangGraph research agent...")
    
    for s in unanalyzed:
        analyze_signal_with_agent(db, int(s.id))

@app.post("/api/detect")
def trigger_detection(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Triggers signal detectors and LangGraph research agent workflows in background."""
    background_tasks.add_task(run_detection_pipeline_sync, db)
    return {"message": "Detection and LangGraph agent workflow triggered in background."}

@app.post("/api/ingest")
def trigger_ingestion(limit: int = 10, db: Session = Depends(get_db)):
    """Manually triggers arXiv/Semantic Scholar paper ingestion."""
    count = ingest_daily_papers(db, limit=limit)
    return {"message": f"Successfully ingested {count} papers."}

@app.post("/api/digest")
def trigger_digest(db: Session = Depends(get_db)):
    """Manually triggers weekly digest compilation and notification dispatch."""
    from src.notifications import compile_and_send_weekly_digest
    success = compile_and_send_weekly_digest(db)
    if success:
        return {"message": "Weekly digest compiled and sent successfully."}
    else:
        return {"message": "Weekly digest process completed, but no notification was dispatched (no active signals found)."}

if __name__ == "__main__":
    # Standard compliance: bind FastAPI strictly to 127.0.0.1 for development/testing
    uvicorn.run("src.api.main:app", host=settings.HOST, port=settings.PORT, reload=True)
