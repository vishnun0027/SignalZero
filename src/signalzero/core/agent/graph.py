import json
import logging
from typing import TypedDict, Dict, Any
from langgraph.graph import StateGraph, END
from sqlalchemy.orm import Session
from signalzero.core.agent.llm import call_llm
from signalzero.models.models import Signal, Paper

logger = logging.getLogger("SignalZero.Agent.Graph")

# Define the LangGraph State
class AgentSignalState(TypedDict):
    signal_id: int
    signal_type: str
    trigger_details: Dict[str, Any]
    retrieved_context: str
    confidence: float
    brief: str
    validation_status: str
    attempts: int

# --- Node 1: Retrieve Context ---
def retrieve_context_node(state: AgentSignalState) -> Dict[str, Any]:
    """Retrieves paper text and relevant historical context from SQL/pgvector database."""
    logger.info(f"LangGraph Agent [retrieve_context] starting for Signal ID: {state['signal_id']}")
    trigger_details = state["trigger_details"]
    signal_type = state["signal_type"]
    
    # We will build a context string containing abstract text and citation counts
    context_parts = []
    
    # Needs a database session to read papers.
    # Since we can't easily pass the DB session in the stateless Graph state directly (as it might not serialize),
    # we can open a temporary connection or pass it in a global/thread-local variable, or fetch inside the node
    # by importing get_db_session. To be safe, we open a temporary session from get_db_session.
    from signalzero.services.database import get_db_session
    db = get_db_session()
    try:
        if signal_type == "cross_field":
            arxiv_id = trigger_details.get("arxiv_id")
            paper = db.query(Paper).filter(Paper.arxiv_id == arxiv_id).first()
            if paper:
                context_parts.append(f"Primary Paper: {paper.title} (arxiv:{paper.arxiv_id})")
                context_parts.append(f"Abstract: {paper.summary}")
                context_parts.append(f"Citing Fields: {', '.join(trigger_details.get('citing_fields', []))}")
                context_parts.append(f"Total Citations: {trigger_details.get('total_citations', 0)}")
                
        elif signal_type == "vocab_drift":
            term = trigger_details.get("term")
            context_parts.append(f"Emergent Technical Term: '{term}'")
            context_parts.append(f"Current Daily Frequency: {trigger_details.get('current_rel_freq', 0):.4f}")
            context_parts.append(f"Historical Mean: {trigger_details.get('mean_prior', 0):.4f}")
            
            # Find a few recent papers containing this term to show examples of usage
            papers = db.query(Paper).filter(
                (Paper.summary.like(f"% {term} %")) | (Paper.title.like(f"% {term} %"))
            ).limit(3).all()
            if papers:
                context_parts.append("Sample papers using this term:")
                for p in papers:
                    context_parts.append(f"- {p.title} (Abstract snippet: {p.summary[:150]}...)")
                    
        elif signal_type == "convergent":
            papers_info = trigger_details.get("papers", [])
            context_parts.append("Convergent Research Group (Papers exploring similar concepts independently):")
            for p_info in papers_info:
                pid = p_info.get("arxiv_id")
                paper = db.query(Paper).filter(Paper.arxiv_id == pid).first()
                if paper:
                    context_parts.append(f"- {paper.title} (by {paper.authors})")
                    context_parts.append(f"  Abstract: {paper.summary}\n")
    except Exception as e:
        logger.error(f"Error retrieving context in LangGraph node: {e}")
    finally:
        db.close()
        
    retrieved_context = "\n".join(context_parts) if context_parts else "No context retrieved."
    return {"retrieved_context": retrieved_context}

# --- Node 2: Analyze Impact ---
def analyze_impact_node(state: AgentSignalState) -> Dict[str, Any]:
    """Generates the 'Why This Matters' structured brief using the LLM."""
    logger.info("LangGraph Agent [analyze_impact] generating briefing...")
    signal_type = state["signal_type"]
    context = state["retrieved_context"]
    
    system_prompt = """You are SignalZero Research Agent, a scientometrics and emerging technology forecasting AI.
Your job is to analyze weak signal indicators in scientific literature and generate a concise, professional, and actionable 'Why This Matters' brief.
Analyze the provided papers/terms. Determine:
1. Core Novelty: what new technical idea is introduced.
2. Cross-domain value / Why it matters: why NLP, CV, biology or systems researchers are adopting it.
3. Potential applications.
4. Watch list: what to look for in the next 90 days.
Write in a clean, executive style. Keep it under 250 words."""

    user_prompt = f"""Signal Type: {signal_type}
Retrieved Context:
{context}

Please generate the briefing now."""
    
    brief = call_llm(system_prompt, user_prompt)
    return {"brief": brief}

# --- Node 3: Score Confidence ---
def score_confidence_node(state: AgentSignalState) -> Dict[str, Any]:
    """Calculates final signal confidence score based on analysis and initial metrics."""
    logger.info("LangGraph Agent [score_confidence] evaluating signal...")
    initial_conf = state["confidence"]
    brief = state["brief"]
    
    # Adjustment: if the brief generated is very short or fallback was triggered, keep initial.
    # Otherwise, check if LLM response indicates low novelty or high noise
    adjusted_conf = initial_conf
    lower_brief = brief.lower()
    if "incremental" in lower_brief or "marginal" in lower_brief or "minor" in lower_brief:
        adjusted_conf = max(0.1, initial_conf - 0.15)
        logger.info(f"Reducing confidence due to incremental/marginal keywords. New score: {adjusted_conf:.2f}")
    elif "breakthrough" in lower_brief or "paradigm shift" in lower_brief or "novel" in lower_brief:
        adjusted_conf = min(0.99, initial_conf + 0.1)
        logger.info(f"Increasing confidence due to novelty markers. New score: {adjusted_conf:.2f}")
        
    return {"confidence": adjusted_conf}

# --- Node 4: Validate ---
def validate_node(state: AgentSignalState) -> Dict[str, Any]:
    """Validates the signal and determines if it should be published or re-analyzed."""
    logger.info("LangGraph Agent [validate] verifying signal criteria...")
    confidence = state["confidence"]
    attempts = state["attempts"]
    
    # If confidence is high enough, we publish.
    # If confidence is low, and we have attempts remaining, we loop back to re-analyze.
    # Otherwise, we publish as-is but with low confidence/status.
    if confidence >= 0.55:
        status = "publish"
    elif attempts < 1:
        status = "re_analyze"
    else:
        status = "publish"  # Publish anyway but mark as low confidence/status
        
    return {"validation_status": status, "attempts": attempts + 1}

# --- Assemble the Graph ---
def create_signal_analysis_agent():
    workflow = StateGraph(AgentSignalState)
    
    # Add nodes
    workflow.add_node("retrieve_context", retrieve_context_node)
    workflow.add_node("analyze_impact", analyze_impact_node)
    workflow.add_node("score_confidence", score_confidence_node)
    workflow.add_node("validate", validate_node)
    
    # Setup execution flow
    workflow.set_entry_point("retrieve_context")
    workflow.add_edge("retrieve_context", "analyze_impact")
    workflow.add_edge("analyze_impact", "score_confidence")
    workflow.add_edge("score_confidence", "validate")
    
    # Conditional loop logic
    workflow.add_conditional_edges(
        "validate",
        lambda state: "publish" if state["validation_status"] == "publish" else "re_analyze",
        {
            "publish": END,
            "re_analyze": "analyze_impact"  # loops back to analyze_impact
        }
    )
    
    return workflow.compile()

# Thread-safe compiled agent graph cache
_compiled_agent = None

def get_signal_agent():
    global _compiled_agent
    if _compiled_agent is None:
        _compiled_agent = create_signal_analysis_agent()
    return _compiled_agent

def analyze_signal_with_agent(db: Session, signal_id: int) -> bool:
    """Entry point to process a detected signal using the LangGraph agent workflow."""
    signal = db.query(Signal).filter(Signal.id == signal_id).first()
    if not signal:
        logger.error(f"Signal ID {signal_id} not found in database.")
        return False
        
    logger.info(f"Starting LangGraph analysis for Signal ID {signal_id} ({signal.type})...")
    
    # Build initial state
    initial_state: AgentSignalState = {
        "signal_id": int(signal.id),
        "signal_type": str(signal.type),
        "trigger_details": json.loads(str(signal.trigger_details)),
        "retrieved_context": "",
        "confidence": float(signal.confidence) if signal.confidence is not None else 0.0,
        "brief": "",
        "validation_status": "",
        "attempts": 0
    }
    
    agent = get_signal_agent()
    try:
        # Run state graph synchronously
        final_state = agent.invoke(initial_state)
        
        # Save results back to database
        signal.brief = final_state.get("brief")  # type: ignore[assignment]
        signal.confidence = final_state.get("confidence", signal.confidence)  # type: ignore[assignment]
        
        # Classify final status based on confidence
        conf = float(signal.confidence) if signal.confidence is not None else 0.0
        if conf >= 0.8:
            signal.status = "growing"  # type: ignore[assignment]
        elif conf >= 0.55:
            signal.status = "emerging"  # type: ignore[assignment]
        else:
            signal.status = "false_positive"  # type: ignore[assignment]
            
        db.commit()
        logger.info(f"LangGraph analysis complete for Signal ID {signal_id}. Status set to: {signal.status}")
        
        # Dispatch notifications if signal is classified as emerging or growing (confidence >= 0.55)
        if signal.status in ["growing", "emerging"]:
            try:
                from signalzero.services.notifications import dispatch_notifications
                dispatch_notifications(
                    signal_type=str(signal.type),
                    confidence=float(signal.confidence) if signal.confidence is not None else 0.0,
                    trigger_details=final_state.get("trigger_details"),
                    brief=str(signal.brief)
                )
            except Exception as notify_err:
                logger.error(f"Error dispatching notification for signal {signal_id}: {notify_err}")
                
        return True
    except Exception as e:
        logger.error(f"Error running LangGraph agent for Signal {signal_id}: {e}")
        raise e
