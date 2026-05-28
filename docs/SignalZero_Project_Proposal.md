# SignalZero: Weak Signal Intelligence for Emerging Technologies
### Project Proposal & Development Plan — Version 1.0
**Author:** Vishnu N | **Date:** May 2026 | **Domain:** AI/ML + Scientometrics + Graph Intelligence

---

## Executive Summary

SignalZero is a domain-focused technology intelligence system that detects **emerging technologies 3–6 months before they enter mainstream discourse** by monitoring weak signals across scientific literature, citation graphs, and technical communities. Unlike tools that surface what is already trending (news aggregators, Google Trends, TechPulse-style systems), SignalZero monitors what has *not yet trended* — sparse, cross-domain, early-stage signals that historically precede major breakthroughs.

The system focuses initially on the **AI/ML domain**, monitoring arXiv preprints, Semantic Scholar citation graphs, and GitHub repositories daily. It detects three classes of weak signal: cross-field citation anomalies, new vocabulary cluster formation, and convergent discovery patterns. Output is a weekly *Emerging Signals Digest* delivered via Slack, with a live web dashboard showing signal velocity and concept lineage graphs.

The project is designed as a solo 12-week build requiring zero cloud infrastructure cost, a standard development laptop, and entirely free data APIs. It acquires four skills currently rare among AI/ML engineers: scientometrics, citation graph analysis, streaming NLP pipelines, and technology forecasting algorithms.

---

## Problem Statement

### The Technology Intelligence Gap

Every organisation that builds on emerging technology faces the same problem: by the time a breakthrough is visible on mainstream channels (tech blogs, Twitter/X, conference talks), it is already 12–18 months old. The decision window — when early adopters gain a structural advantage — has already closed.

Current tools fail in a predictable way:

| Tool | What It Does | Critical Failure |
|------|--------------|-----------------|
| Google Trends | Tracks search volume | Only measures what is already mainstream |
| TechPulse AI / news aggregators | Summarises trending articles | Reports what is already known |
| Google Scholar Alerts | Notifies on keyword matches | Requires you to already know the keyword |
| Gartner Hype Cycle | Categorises technology maturity | Annual report, always 12+ months behind |
| arXiv RSS feeds | Delivers new papers | Raw firehose — no signal extraction |

The gap is not in data availability — arXiv publishes 200,000+ papers per year, Semantic Scholar tracks 200M+ papers with full citation graphs, and all of this is freely accessible. The gap is in **signal extraction**: identifying which 0.1% of papers represent genuine paradigm shifts before the other 99.9% are aware of them.

### The Weak Signal Phenomenon

A weak signal is defined in technology forecasting literature as an early, faint, and ambiguous indicator of a future development — present in data but below the threshold of mainstream attention. Three patterns historically precede major AI/ML breakthroughs:

**Pattern 1 — Cross-Field Citation Anomaly**
A paper published in field A is cited by researchers in fields B, C, and D within its first 6 months. This cross-domain citation pattern indicates that the idea is solving a problem broader than its origin domain. The transformer architecture paper (2017) was cited by NLP, computer vision, speech recognition, and protein structure researchers within 8 months — a detectable cross-field anomaly.

**Pattern 2 — Vocabulary Emergence**
A new term appears in arXiv abstracts with near-zero frequency, then doubles in usage over 60 days, then accelerates. The term "diffusion model" showed this exact pattern in 2020–2021, detectable 9 months before DALL-E made it a mainstream concept.

**Pattern 3 — Convergent Discovery**
Three or more independent research groups publish papers on the same novel concept within a 90-day window, with no shared authors or institutional affiliation. Convergent discovery indicates the idea has reached the natural threshold of discovery — multiple groups found it simultaneously, meaning the foundational conditions are now widely met.

SignalZero detects all three patterns algorithmically, in real time, across the AI/ML literature.

---

## System Architecture

### High-Level Design

```
[Data Sources]
arXiv API + Semantic Scholar API + GitHub API
          │
          ▼
[Daily Ingestion Pipeline]
Fetch new papers → extract metadata, abstracts,
citations, referenced repos
          │
          ▼
[Embedding Layer]
SPECTER2 (Semantic Scholar's paper embeddings)
or sentence-transformers/all-MiniLM-L6-v2
Store in pgvector with paper_id, date, field tags
          │
          ▼
[Signal Detection Engine — 3 detectors running in parallel]
│
├── [Detector 1: Cross-Field Citation Monitor]
│   Neo4j citation graph
│   Daily: detect papers cited across ≥3 distinct arXiv fields
│   Score = (unique fields citing) × (citation velocity)
│
├── [Detector 2: Vocabulary Emergence Monitor]
│   Track n-gram frequency in abstracts by week
│   ADWIN drift detection on term frequency time series
│   Alert when new term crosses emergence threshold
│
└── [Detector 3: Convergent Discovery Monitor]
    Cluster new papers by semantic similarity daily
    Flag clusters of ≥3 papers from independent groups
    on same novel concept within 90-day window
          │
          ▼
[LangGraph Research Agent]
For each detected signal:
→ Retrieve related papers from pgvector
→ Generate "Why This Matters" brief (Groq/Llama)
→ Score signal confidence (0.0–1.0)
→ Assign domain tags and potential impact areas
          │
          ▼
[Signal Store — PostgreSQL]
All signals with scores, dates, briefs, status
(emerging / growing / mainstream / false positive)
          │
          ▼
[Output Layer]
├── Weekly Digest → Slack / Email
├── Live Dashboard → FastAPI + React
└── Neo4j Concept Lineage Graph → Visual explorer
```

### Component Detail

#### Component 1 — Daily Ingestion Pipeline

```python
# Runs daily via cron / GitHub Actions
import arxiv
import requests

def ingest_daily_papers():
    # Fetch yesterday's AI/ML papers from arXiv
    client = arxiv.Client()
    search = arxiv.Search(
        query="cat:cs.AI OR cat:cs.LG OR cat:cs.CL",
        max_results=500,
        sort_by=arxiv.SortCriterion.SubmittedDate
    )
    papers = list(client.results(search))

    for paper in papers:
        # Fetch citation data from Semantic Scholar (free, no key needed)
        s2_data = requests.get(
            f"https://api.semanticscholar.org/graph/v1/paper/arXiv:{paper.get_short_id()}",
            params={"fields": "citations,references,fieldsOfStudy,tldr"}
        ).json()

        # Embed abstract and store in pgvector
        embed_and_store(paper, s2_data)

        # Update Neo4j citation graph
        update_citation_graph(paper, s2_data)
```

Semantic Scholar API requires no API key for basic access (100 requests per 5 minutes free tier, 1,000 requests per 5 minutes with free API key registration) — sufficient for 500 papers/day.

#### Component 2 — Cross-Field Citation Monitor (Neo4j)

```cypher
// Find papers cited across 3+ distinct fields in last 90 days
MATCH (p:Paper)-[:CITED_BY]->(citing:Paper)
WHERE p.published_date > date() - duration({days: 90})
WITH p, collect(DISTINCT citing.primary_field) AS citing_fields
WHERE size(citing_fields) >= 3
RETURN p.title, p.arxiv_id, citing_fields,
       size(citing_fields) AS field_spread
ORDER BY field_spread DESC
LIMIT 20
```

This single Cypher query is the core of the cross-field detector — impossible to write cleanly in SQL but natural in Neo4j.

#### Component 3 — Vocabulary Emergence Monitor

```python
from river.drift import ADWIN  # Streaming drift detection

# Track term frequencies as streaming time series
# ADWIN detects when frequency distribution shifts
term_detectors = {}  # term → ADWIN instance

def check_vocabulary_emergence(abstracts: list[str]):
    ngrams = extract_ngrams(abstracts, n=[1, 2, 3])

    for term, count in ngrams.items():
        if term not in term_detectors:
            term_detectors[term] = ADWIN()

        # ADWIN detects statistically significant frequency increase
        drift_detected = term_detectors[term].update(count)

        if drift_detected and is_novel_term(term):
            emit_signal(SignalType.VOCABULARY_EMERGENCE, term, count)
```

ADWIN (Adaptive Windowing) is the same drift detection algorithm used in PulseAI for system metrics — here applied to term frequency time series instead of CPU/memory metrics. The conceptual transfer is direct.

#### Component 4 — LangGraph Research Agent

```python
from langgraph.graph import StateGraph

# Agent runs for each detected signal to generate brief
def create_signal_analysis_agent():
    graph = StateGraph(SignalState)

    graph.add_node("retrieve_context", retrieve_related_papers)
    graph.add_node("analyze_impact", generate_impact_analysis)
    graph.add_node("score_confidence", calculate_signal_confidence)
    graph.add_node("write_brief", generate_signal_brief)
    graph.add_node("validate", validate_not_false_positive)

    # Cyclic: if validation fails, loop back to re-analysis
    graph.add_conditional_edges(
        "validate",
        lambda s: "publish" if s.confidence > 0.6 else "analyze_impact"
    )

    return graph.compile()
```

---

## Data Sources & APIs

### Primary Sources

| Source | Data Provided | API Type | Cost |
|--------|--------------|----------|------|
| arXiv API | Paper metadata, abstracts, categories, daily RSS | REST + OAI-PMH | Free, unlimited |
| Semantic Scholar API | Citations, references, field classifications, TLDR summaries, SPECTER2 embeddings | REST | Free (no key: 100 req/5min; free key: 1000 req/5min) |
| GitHub API | Repository stars, forks, topics, linked papers | REST | Free (5000 req/hour) |
| Unpaywall API | Open access paper full text | REST | Free |

### Secondary Sources (Phase 2)

| Source | Data Provided | API Type | Cost |
|--------|--------------|----------|------|
| Google Patents API | Patent filings by IPC classification | REST | Free (basic) |
| PubMed API | Biomedical papers (for cross-domain detection) | REST | Free |
| GDELT Project | Global news signals | REST | Free |
| HackerNews API | Technical community early discussion | REST | Free |

### Storage Requirements

| Layer | Technology | Estimated Size |
|-------|-----------|---------------|
| Paper embeddings (1 year, AI domain) | pgvector (Supabase free tier) | ~2 GB |
| Citation graph | Neo4j AuraDB (free tier, 200K nodes) | ~1 GB |
| Signal store | PostgreSQL | ~500 MB |
| Term frequency time series | Redis (Upstash free tier) | ~256 MB |
| **Total** | | **~4 GB — fits on laptop** |

**Monthly infrastructure cost: ₹0** — all components have free tiers sufficient for a portfolio-scale deployment.

---

## Signal Detection: Worked Example

### Historical Validation — Detecting Transformers Early (2017)

The following shows what SignalZero would have detected had it existed in late 2017:

```
DATE: December 2017

SIGNAL ALERT — CROSS-FIELD CITATION ANOMALY
Paper: "Attention Is All You Need" (Vaswani et al., 2017)
Published: June 2017 (cs.CL — Computational Linguistics)

Citation pattern after 6 months:
  cs.CL  (NLP):          47 citations  ← expected
  cs.CV  (Vision):       12 citations  ← ANOMALY
  cs.SD  (Sound):         8 citations  ← ANOMALY
  q-bio  (Biology):       3 citations  ← ANOMALY

Field spread score: 4 distinct domains
Cross-field velocity: 23 citations/month outside origin field

CONFIDENCE: 0.84

WHY THIS MATTERS (Agent Brief):
"An NLP architecture paper is being adopted by computer
vision and biology researchers 6 months after publication.
Cross-domain adoption at this velocity indicates a
general-purpose mechanism, not a domain-specific trick.
Watch for: vision transformers, protein structure
applications, audio processing variants."

STATUS: EMERGING → (became mainstream: April 2020, ViT paper)
LEAD TIME: 28 months
```

This is exactly the output SignalZero would generate — a structured alert, a confidence score, and an actionable brief, 28 months before Vision Transformers went mainstream.

---

## Technology Stack

| Layer | Technology | Version | Purpose |
|-------|-----------|---------|---------|
| Agent Framework | LangGraph | Latest | Cyclic signal analysis agent |
| Graph Database | Neo4j (AuraDB free) | 5.x | Citation graph, concept lineage |
| Vector Store | pgvector via Supabase | — | Paper semantic embeddings |
| Time Series / Cache | Redis (Upstash free) | — | Term frequency streams, ADWIN state |
| Relational DB | PostgreSQL | 16 | Signal store, paper metadata |
| Drift Detection | River (ADWIN, KSWIN) | 0.21+ | Vocabulary emergence detection |
| Embedding Model | SPECTER2 / MiniLM-L6 | — | Paper-level semantic embeddings |
| LLM Inference | Groq (Llama-3.3-70b) | — | Signal brief generation |
| API Framework | FastAPI + Pydantic | 0.115+ | Backend REST API |
| Frontend | React + TypeScript | 18+ | Live dashboard |
| Graph Visualisation | Sigma.js / D3.js | — | Interactive citation graph explorer |
| Dependency Management | uv | Latest | Python package management |
| Containerisation | Docker Compose | — | Local orchestration |
| Scheduling | APScheduler / GitHub Actions | — | Daily ingestion cron |
| Language | Python 3.12+ | 3.12 | Primary development language |

---

## New Skills Acquired

| Skill Domain | Specific Technology | Current Gap | Career Value |
|---|---|---|---|
| Scientometrics | Citation velocity, h-index variants, field spread scoring | Not in standard ML curriculum | Opens academic research tooling market |
| Citation graph analysis | Neo4j Cypher, graph algorithms (PageRank, betweenness) | New domain entirely | Rare intersection of graph DB + NLP |
| Streaming NLP | River ADWIN/KSWIN on text features | Know batch ML, not streaming | High demand in real-time ML systems |
| Technology forecasting | Weak signal theory, emergence thresholds | New domain | Strategy consulting, VC tooling |
| Scientific data pipelines | Semantic Scholar API, arXiv OAI-PMH, patent APIs | Know general APIs | Academic / research tooling niche |
| Graph visualisation | Sigma.js, D3.js force graphs | Backend-heavy, weak on viz | Full-stack data product capability |

---

## Project Plan

### Overview

| Phase | Duration | Focus | Deliverable |
|-------|----------|-------|-------------|
| Phase 1 | Weeks 1–2 | Foundation & data pipeline | Working arXiv + S2 ingestion |
| Phase 2 | Weeks 3–4 | Citation graph + Neo4j | Cross-field detector live |
| Phase 3 | Weeks 5–6 | Vocabulary emergence | ADWIN detector live |
| Phase 4 | Weeks 7–8 | LangGraph agent + briefs | Full signal pipeline end-to-end |
| Phase 5 | Weeks 9–10 | Dashboard + digest | React UI + Slack delivery |
| Phase 6 | Weeks 11–12 | Validation + polish | Historical backtest + public launch |

---

### Phase 1 — Foundation & Data Pipeline (Weeks 1–2)

**Goal:** Working daily ingestion of AI/ML papers with metadata and embedding storage.

**Tasks:**
- [ ] Set up project structure with `uv`, Docker Compose, PostgreSQL, Redis
- [ ] Implement arXiv daily fetch (arxiv Python library — OAI-PMH for bulk, REST for real-time)
- [ ] Implement Semantic Scholar citation enrichment (free API, no key required)
- [ ] Set up pgvector on Supabase free tier
- [ ] Embed paper abstracts with `all-MiniLM-L6-v2` and store in pgvector
- [ ] Build paper deduplication (arXiv ID as primary key)
- [ ] Validate: 300–500 AI/ML papers ingested daily with citations

**Milestone:** A daily cron job ingests yesterday's arXiv AI/ML papers, enriches with Semantic Scholar citation data, embeds abstracts, and stores in pgvector. Verifiable by querying the DB and seeing fresh entries each morning.

---

### Phase 2 — Citation Graph & Cross-Field Detector (Weeks 3–4)

**Goal:** Neo4j citation graph live with cross-field anomaly detection running.

**Tasks:**
- [ ] Set up Neo4j AuraDB free tier (200K nodes free — sufficient for 1-year AI domain)
- [ ] Design graph schema: `(:Paper)-[:CITES]->(:Paper)`, `(:Paper)-[:BELONGS_TO]->(:Field)`
- [ ] Write ingestion script: paper nodes + citation edges + field classification from Semantic Scholar
- [ ] Implement Cypher query for cross-field citation detection (papers cited in 3+ distinct fields)
- [ ] Build citation velocity scorer: citations per week, acceleration, field spread score
- [ ] Write unit tests: verify "Attention Is All You Need" would score high on cross-field metric
- [ ] Log all detected signals to PostgreSQL signal store with confidence scores

**Milestone:** Run the cross-field detector on historical data (2017–2020). Verify it surfaces transformer, BERT, and diffusion model papers with high confidence scores before their mainstream peak.

---

### Phase 3 — Vocabulary Emergence Detector (Weeks 5–6)

**Goal:** Real-time term frequency monitoring with ADWIN drift detection on arXiv abstracts.

**Tasks:**
- [ ] Implement n-gram extraction from daily abstract batch (unigrams + bigrams + trigrams)
- [ ] Set up River ADWIN instance per tracked term (persisted in Redis)
- [ ] Build novel term filter: suppress known dictionary words, focus on technical neologisms
- [ ] Implement emergence threshold: alert when new term doubles in 30-day window
- [ ] Add false positive filters: suppress terms that appear in only one paper (one author coining a term ≠ emergence)
- [ ] Backtest: verify "diffusion model", "instruction tuning", "chain of thought", "LoRA" all detected 4–8 months before mainstream
- [ ] Log vocabulary signals to signal store with term trajectory data

**Milestone:** Detector runs on live arXiv feed and surfaces 3–5 genuinely new technical terms per week with documented emergence trajectories.

---

### Phase 4 — LangGraph Research Agent & Signal Briefs (Weeks 7–8)

**Goal:** Automated "Why This Matters" brief generation for each detected signal.

**Tasks:**
- [ ] Design LangGraph agent state: signal_type, paper_ids, retrieved_context, brief, confidence, validation_status
- [ ] Implement context retrieval node: pgvector semantic search for related prior papers
- [ ] Implement impact analysis node: LLM generates structured brief (what, why, potential applications, watch list)
- [ ] Implement confidence scoring node: combines citation metrics, vocabulary frequency, convergence score
- [ ] Implement validation node: checks brief against known false positives, rejects low-confidence signals
- [ ] Add cyclic re-analysis: if confidence < 0.6, agent loops back with broader context retrieval
- [ ] Test end-to-end: signal detected → brief generated → stored with score

**Milestone:** For any signal detected in Phase 2 or 3, the agent generates a structured 200-word brief within 90 seconds. Brief quality validated manually against 10 historical signals.

---

### Phase 5 — Dashboard & Digest Delivery (Weeks 9–10)

**Goal:** Live web dashboard and weekly Slack digest delivering signals to users.

**Tasks:**
- [ ] Build FastAPI backend: `/signals` (paginated), `/signals/{id}`, `/graph/{paper_id}`, `/stats`
- [ ] Build React dashboard with three views:
  - **Live Feed:** Incoming signals sorted by confidence score with brief preview
  - **Signal Detail:** Full brief, paper links, citation graph mini-view, trajectory chart
  - **Concept Lineage Explorer:** Sigma.js interactive graph — papers as nodes, citations as edges, signals highlighted
- [ ] Implement Slack webhook delivery: weekly digest of top 5 signals with confidence scores and briefs
- [ ] Add domain filter: user selects sub-domains (NLP / CV / RL / Systems / Theory) to personalise feed
- [ ] Add false positive feedback loop: user marks signal as false positive → logged → improves future scoring

**Milestone:** Dashboard live at localhost. Weekly digest delivered to Slack with top 5 signals, each with a confidence score, one-paragraph brief, and link to the triggering paper.

---

### Phase 6 — Validation, Backtest & Public Launch (Weeks 11–12)

**Goal:** Validate system accuracy with historical data and launch publicly on GitHub.

**Tasks:**
- [ ] Run full historical backtest on 2016–2023 AI/ML data
- [ ] Measure precision: what % of signals flagged were genuinely significant (validated against actual adoption curves)?
- [ ] Measure lead time: for true positives, how many months before mainstream did SignalZero detect them?
- [ ] Document known limitations honestly (false positive rate, domain-specificity, citation lag)
- [ ] Write technical blog post: *"I built a system that detects AI breakthroughs before they have a name — here's how it works and how accurate it is"*
- [ ] Deploy to free tier (Railway for FastAPI, Vercel for React, Supabase pgvector, Neo4j AuraDB)
- [ ] Publish on GitHub with full documentation, architecture diagrams, and backtest results
- [ ] Submit to Hacker News Show HN and relevant ML subreddits

**Milestone:** Public GitHub repository with documented backtest results showing lead time and precision metrics. Live demo accessible at public URL.

---

## Risk Assessment & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| High false positive rate | High | Medium | Add human feedback loop; start with conservative thresholds |
| Semantic Scholar API rate limits | Medium | Low | Free API key gives 1000 req/5min — sufficient; cache aggressively |
| Neo4j AuraDB free tier node limit | Low | Medium | 200K nodes covers ~3 years of AI/ML papers; prune old nodes |
| Citation lag (papers take weeks to accumulate citations) | High | Medium | Use vocabulary emergence + convergent discovery as early detectors; citations as confirmation |
| LLM brief quality inconsistency | Medium | Low | Structured output with Pydantic validation; human review before digest |
| Domain coverage too narrow | Low | Low | Start narrow by design; Phase 2+ expansion is straightforward |

---

## Deployment Architecture

### Zero-Cost Production Stack

| Service | Provider | Free Tier | Used For |
|---------|----------|-----------|---------|
| pgvector | Supabase | 500 MB storage | Paper embeddings |
| Graph DB | Neo4j AuraDB | 200K nodes, 400K relationships | Citation graph |
| Backend hosting | Railway | 500 hrs/month | FastAPI + cron jobs |
| Frontend | Vercel | Unlimited (static) | React dashboard |
| LLM inference | Groq | 14,400 req/day | Signal brief generation |
| Redis | Upstash | 10K commands/day | Term frequency streams |
| PostgreSQL | Supabase | 500 MB storage | Signal store, metadata |
| **Monthly cost** | | | **₹0** |

---

## Success Metrics

The project is evaluated against three honest metrics:

| Metric | Target | How Measured |
|--------|--------|-------------|
| **Precision** | > 40% of flagged signals are genuinely significant | Manual review of 50 randomly sampled signals vs. actual adoption curves |
| **Lead time** | Median 4+ months before mainstream detection | Compare signal date to date of first major tech blog/conference coverage |
| **Coverage** | Detects 6 of 10 major AI advances from 2020–2023 in backtest | Historical validation against known breakthrough timeline |

A 40% precision target is realistic and honest — even DARPA-funded systems in this domain report significant noise. The value is in the 40% that are real, not in eliminating the 60% that are not.

---

## Why This Project Matters

SignalZero is not a productivity tool or a chat interface. It is a **scientific instrument** — a telescope pointed at the frontier of human knowledge, built to detect faint light from ideas that have not yet arrived.

For a portfolio, it demonstrates capabilities that are rare among AI/ML engineers: citation graph analysis, streaming NLP, scientometrics, and technology forecasting. For a career, it opens doors into research intelligence at VC firms, strategic technology scouting at tech companies, academic research tooling, and government science policy — all domains where ML engineers are rarely found.

The most important outcome is not the tool itself. It is the deep understanding of how scientific knowledge propagates, how ideas cross domain boundaries, and how breakthroughs look in their earliest, most fragile moments — before the world has words for them.

---

*SignalZero — Built to find the next big thing while it is still three papers and a GitHub repository.*
