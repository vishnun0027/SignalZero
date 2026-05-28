# SignalZero: Weak Signal Intelligence for Emerging Technologies

SignalZero is a headless, domain-focused technology forecasting system that detects **emerging AI/ML breakthroughs 3–6 months before they enter mainstream discourse**. By monitoring daily arXiv preprint feeds, Semantic Scholar citation graphs, and technical neologisms, SignalZero algorithmically extracts early indicators of paradigm shifts and generates structured "Why This Matters" briefings using a LangGraph research agent.

The system is designed for **headless operation**, delivering real-time alerts and weekly digests directly to Slack and Discord.

---

## System Architecture

```
[arXiv API] + [Semantic Scholar API]
                 │
                 ▼
     [Daily Ingestion Pipeline]
                 │
        ┌────────┴────────┐
        ▼                 ▼
   [PostgreSQL]       [Neo4j Graph]
   (pgvector metadata) (citation lineage)
        │                 │
        └────────┬────────┘
                 ▼
     [Signal Detection Engine]
     ├── Cross-Field Citation Monitor
     ├── Vocabulary Emergence Detector
     └── Convergent Discovery Clusterer
                 │
                 ▼
    [LangGraph Research Agent] (Groq Llama-3.3)
                 │
                 ▼
         [Digest Engine]
                 │
        ┌────────┴────────┐
        ▼                 ▼
  [Discord Embed]    [Slack mrkdwn]
```

---

## Key Features

1. **Daily Ingestion Pipeline:** Automatic daily ingestion of new preprints in `cs.AI`, `cs.LG`, and `cs.CL`.
2. **Tri-Detector System:**
   * **Cross-Field Citation Monitor:** Detects papers cited across $\ge 3$ distinct arXiv domains via Neo4j Cypher queries.
   * **Vocabulary Emergence Detector:** Monitors term-frequency spikes in abstracts using n-grams and ADWIN drift detection.
   * **Convergent Discovery Clusterer:** Identifies semantic clusters of $\ge 3$ independent research groups working on similar novel concepts using SPECTER/MiniLM embeddings.
3. **LangGraph Research Agent:** Runs a validation loop that retrieves semantic context, scores confidence, and generates executive-level briefs ("Why This Matters") using Groq/OpenAI.
4. **Headless Alerts & Digests:** Direct Slack and Discord webhooks for instant alerts and aggregated weekly digests.
5. **REST API Interface:** FastAPI endpoints for health checks, signal history, graph lineages, and manual pipeline triggers.

---

## Directory Structure

* [main.py](file:///home/vishnu/worklab/SignalZero/main.py) — Daily pipeline orchestration entry point.
* [weekly_digest.py](file:///home/vishnu/worklab/SignalZero/weekly_digest.py) — Compiles and sends the weekly summary report.
* [run_backtest.py](file:///home/vishnu/worklab/SignalZero/run_backtest.py) — Seeds historical data and measures detector metrics.
* [verify_connections.py](file:///home/vishnu/worklab/SignalZero/verify_connections.py) — Validates database and external API integrations.
* `src/` — Package source files:
  * [src/config.py](file:///home/vishnu/worklab/SignalZero/src/config.py) — Pydantic app configuration.
  * [src/database.py](file:///home/vishnu/worklab/SignalZero/src/database.py) — Postgres, Redis, and Neo4j connections.
  * [src/models.py](file:///home/vishnu/worklab/SignalZero/src/models.py) — SQLAlchemy database tables.
  * [src/ingestion.py](file:///home/vishnu/worklab/SignalZero/src/ingestion.py) — arXiv and Semantic Scholar fetches.
  * `src/detectors/` — Algorithmic weak signal monitors ([cross_field.py](file:///home/vishnu/worklab/SignalZero/src/detectors/cross_field.py), [vocab_drift.py](file:///home/vishnu/worklab/SignalZero/src/detectors/vocab_drift.py), [convergent.py](file:///home/vishnu/worklab/SignalZero/src/detectors/convergent.py)).
  * `src/agent/` — LangGraph briefing agent ([graph.py](file:///home/vishnu/worklab/SignalZero/src/agent/graph.py), [llm.py](file:///home/vishnu/worklab/SignalZero/src/agent/llm.py)).
  * [src/notifications.py](file:///home/vishnu/worklab/SignalZero/src/notifications.py) — Webhook dispatch formatting.
  * [src/api/main.py](file:///home/vishnu/worklab/SignalZero/src/api/main.py) — FastAPI REST endpoint router.
* `tests/` — Automated test suites.

---

## Configuration & Environment Variables

Copy the example configuration to initialize your environment:
```bash
cp .env.example .env
```

Configure your credentials in `.env`:
```ini
# Application Mode
ENV=development
HOST=127.0.0.1
PORT=8007

# 1. Supabase/PostgreSQL (with pgvector support)
DATABASE_URL=postgresql://[user]:[password]@[host]:5432/postgres

# 2. Graph Database (Neo4j AuraDB or local)
NEO4J_URI=neo4j+s://[your-aura-id].databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your-neo4j-password

# 3. Cache & Time Series (Upstash Redis or local)
REDIS_URL=redis://localhost:6379

# 4. LLM API Keys (Groq / OpenAI)
GROQ_API_KEY=gsk_xxx
OPENAI_API_KEY=sk-proj-xxx

# 5. Headless Webhooks
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

To verify database and API configurations, run the connection tool:
```bash
uv run python verify_connections.py
```

---

## Usage Instructions

### 1. Running the Pipeline
Trigger a manual daily ingestion, detection, and analysis workflow run:
```bash
uv run python main.py
```

### 2. Launching the REST API
Start the FastAPI local web server:
```bash
uv run python src/api/main.py
```
Interactive API docs will be available at `http://127.0.0.1:8007/docs`.

### 3. Compiling the Weekly Digest
Trigger the compilation of top signals and send the summary digest report to Slack and Discord:
```bash
uv run python weekly_digest.py
```

---

## Production Deployment (Headless)

SignalZero can be configured to run continuously in headless environments using `systemd` timers.

1. **Deploy Service Units:**
   Copy the unit files to `/etc/systemd/system/`:
   ```bash
   sudo cp signalzero.service /etc/systemd/system/
   sudo cp signalzero.timer /etc/systemd/system/
   sudo cp signalzero_digest.service /etc/systemd/system/
   sudo cp signalzero_digest.timer /etc/systemd/system/
   ```

2. **Reload and Enable Timers:**
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now signalzero.timer
   sudo systemctl enable --now signalzero_digest.timer
   ```

3. **Check Pipeline Logs:**
   ```bash
   journalctl -u signalzero.service -n 50 --no-pager
   ```

---

## Testing & Verification

### Run Unit Tests
```bash
uv run pytest
```

### Run Historical Backtest Simulation
SignalZero contains a validation tool that seeds an isolated database with historical breakthrough data (such as Transformers, BERT, and LoRA), mocks citation spreads, and measures detector accuracy metrics:
```bash
uv run python run_backtest.py
```
This script computes and formats detector performance:
* **Precision:** Goal is $\ge 40.0\%$.
* **Recall:** Goal is $\ge 70.0\%$ (capturing known breakthroughs).
* **Estimated Lead Time:** Displays detection offset before concept peaks.
