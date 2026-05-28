# Coding Standards & Best Practices

> **Version:** 1.0.0 · **Language:** Python (adaptable to any stack) · **Package Manager:** `uv` (swap for `pip`, `poetry`, `npm`, etc.)
>
> Copy this file into the root of any project as `CODING_STANDARDS.md`. Update the version and language note at the top as needed.

---

## Table of Contents

1. [Project Structure](#1-project-structure)
2. [Naming Conventions](#2-naming-conventions)
3. [Code Style & Formatting](#3-code-style--formatting)
4. [Type Annotations](#4-type-annotations)
5. [Documentation & Comments](#5-documentation--comments)
6. [Error Handling & Logging](#6-error-handling--logging)
7. [Configuration Management](#7-configuration-management)
8. [Testing Standards](#8-testing-standards)
9. [Git & Version Control](#9-git--version-control)
10. [Dependency Management](#10-dependency-management)
11. [Security Practices](#11-security-practices)
12. [CI/CD Conventions](#12-cicd-conventions)

---

## 1. Project Structure

Every project must follow the `src/` layout. All source code lives inside `src/<package_name>/` — never at the root.

```
project-name/
├── src/
│   └── package_name/
│       ├── __init__.py
│       ├── core/           # Pure domain logic — no I/O, no side effects
│       ├── services/       # External integrations (APIs, DBs, LLMs)
│       ├── models/         # Data models and schemas (e.g., Pydantic)
│       └── utils/          # Shared helpers and utilities
├── config/                 # YAML / TOML configuration files
├── tests/
│   ├── unit/
│   └── integration/
├── scripts/                # One-off runner scripts (never loose at root)
├── docs/                   # Architecture notes, ADRs, proposals
├── .github/
│   └── workflows/          # CI pipelines
├── .env.example            # Always committed — never .env itself
├── .gitignore
├── .python-version         # Pin runtime version (e.g., 3.12)
├── pyproject.toml          # Single source of truth for deps + tooling config
├── Makefile                # Developer shortcuts
└── uv.lock                 # Committed lockfile for reproducible installs
```

### Rules

- **No loose scripts at the project root.** Entry-point runners go in `scripts/`, reusable logic goes in `src/`.
- **One package per repo** for most projects. If you genuinely need multiple, use a monorepo with `packages/` subdirectories.
- **`config/` holds environment-agnostic config** (topic lists, model settings, schedules). Secrets never go here.
- **`docs/` holds architecture decisions** (ADRs), proposals, and design notes — not generated API docs.

---

## 2. Naming Conventions

Consistent naming makes code searchable and self-documenting.

### Python

| Element | Convention | Example |
|---|---|---|
| Module / file | `snake_case` | `news_fetcher.py` |
| Package / directory | `snake_case` | `src/signal_zero/` |
| Class | `PascalCase` | `ArticleSummarizer` |
| Function / method | `snake_case` | `fetch_articles()` |
| Variable | `snake_case` | `article_count` |
| Constant | `UPPER_SNAKE_CASE` | `MAX_RETRIES = 3` |
| Private member | `_leading_underscore` | `_parse_response()` |
| Type alias | `PascalCase` | `ArticleList = list[Article]` |
| Pydantic model | `PascalCase` + noun | `ArticleSchema`, `UserConfig` |

### Files & Directories

- Use `kebab-case` for non-Python config files: `agent-config.yaml`, `prompt-templates.yaml`
- Use `UPPER_SNAKE_CASE` for root-level documentation: `README.md`, `CHANGELOG.md`, `CODING_STANDARDS.md`
- Test files mirror the source path: `src/core/fetcher.py` → `tests/unit/core/test_fetcher.py`

### Avoid

- Ambiguous names: `data`, `info`, `obj`, `tmp`, `x`, `df` (outside of short-lived local scope)
- Abbreviations unless universally understood: use `config` not `cfg`, `response` not `resp`
- Redundant context: inside `class ArticleFetcher`, write `def fetch()` not `def fetch_article()`

---

## 3. Code Style & Formatting

All formatting is automated — no manual style debates.

### Toolchain

| Tool | Purpose | Config location |
|---|---|---|
| `ruff format` | Code formatter (replaces Black) | `pyproject.toml` |
| `ruff check` | Linter (replaces flake8, isort, pyupgrade) | `pyproject.toml` |
| `mypy` | Static type checker | `pyproject.toml` |

### `pyproject.toml` Configuration Block

```toml
[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "B", "C4", "SIM"]
ignore = ["E501"]   # Line length handled by formatter

[tool.ruff.lint.isort]
known-first-party = ["package_name"]

[tool.mypy]
python_version = "3.12"
strict = true
ignore_missing_imports = true
```

### Key Style Rules

- **Line length:** 100 characters max.
- **Imports:** standard library → third-party → local, each group separated by a blank line. `ruff` enforces this automatically.
- **String quotes:** double quotes `"` everywhere (ruff formatter default).
- **Trailing commas:** always add in multi-line function signatures, lists, and dicts. Reduces diffs.
- **No magic numbers:** extract numeric literals into named constants.
- **One logical concept per function.** If a function needs a comment to explain what a block does, that block should be its own function.

---

## 4. Type Annotations

Type annotations are **mandatory** for all function signatures. They are the primary form of documentation.

```python
# ✅ Good
def summarize(articles: list[str], max_tokens: int = 512) -> str:
    ...

# ❌ Bad
def summarize(articles, max_tokens=512):
    ...
```

### Rules

- Annotate all function parameters and return types — no exceptions.
- Use `from __future__ import annotations` at the top of every file for deferred evaluation.
- Use `X | None` over `Optional[X]` (Python 3.10+ syntax).
- Use `list[str]` over `List[str]`, `dict[str, int]` over `Dict[str, int]` (built-in generics).
- Use `TypeAlias` for complex repeated types:
  ```python
  from typing import TypeAlias
  ArticleList: TypeAlias = list[dict[str, str]]
  ```
- Use `Literal` for fixed-value parameters:
  ```python
  def set_mode(mode: Literal["train", "eval", "test"]) -> None: ...
  ```
- Use `Protocol` for structural typing over concrete base classes when the interface matters more than the inheritance.

---

## 5. Documentation & Comments

### Docstrings

Every public module, class, and function gets a docstring. Use Google-style format.

```python
def fetch_articles(query: str, limit: int = 10) -> list[Article]:
    """Fetch articles matching a search query from the configured source.

    Args:
        query: Search terms to match against article titles and bodies.
        limit: Maximum number of articles to return. Defaults to 10.

    Returns:
        A list of Article objects sorted by relevance score, descending.

    Raises:
        APIConnectionError: If the upstream source is unreachable.
        ValueError: If limit is less than 1.
    """
```

### Inline Comments

- Comments explain **why**, not **what**. The code says what; the comment says why.
- Delete commented-out code. Use `git` to recover old code.
- Prefix non-obvious workarounds: `# HACK:`, `# FIXME:`, `# TODO(username):`.

```python
# ✅ Good — explains a non-obvious decision
# Retry with backoff because the upstream API has a 429 rate limit after 5 req/s
time.sleep(2 ** attempt)

# ❌ Bad — restates what the code already says
# Sleep for 2 to the power of attempt seconds
time.sleep(2 ** attempt)
```

### README Requirements

Every repo must have a `README.md` with these sections:

1. **What it does** — one paragraph, plain language
2. **Architecture** — brief diagram or bullet list of components
3. **Setup** — exact commands to get running from zero
4. **Usage** — concrete examples with real inputs/outputs
5. **Environment variables** — table of all vars, whether required, and their purpose

---

## 6. Error Handling & Logging

### Errors

- **Never use bare `except:`** — always catch a specific exception type.
- **Raise early, return late.** Validate inputs at the entry point; don't let bad data propagate deep.
- **Wrap external calls** in try/except. Map third-party exceptions to your own domain exceptions.
- Define a project-level exception hierarchy in `src/package_name/exceptions.py`:

```python
class ProjectBaseError(Exception):
    """Root exception for all project-specific errors."""

class FetchError(ProjectBaseError):
    """Raised when an external data fetch fails."""

class ConfigError(ProjectBaseError):
    """Raised when configuration is invalid or missing."""
```

### Logging

Use the standard `logging` module — never `print()` in production code.

```python
import logging

logger = logging.getLogger(__name__)

# ✅ Good
logger.info("Fetched %d articles from %s", len(articles), source)
logger.error("API request failed: %s", exc, exc_info=True)

# ❌ Bad
print(f"Got {len(articles)} articles")
```

**Log level guide:**

| Level | When to use |
|---|---|
| `DEBUG` | Detailed diagnostic info, only useful during development |
| `INFO` | Normal operation milestones (started, fetched, completed) |
| `WARNING` | Something unexpected but recoverable happened |
| `ERROR` | An operation failed; the system can continue |
| `CRITICAL` | A failure that requires immediate attention / process exit |

Configure logging once at the entry point (`main.py` or `scripts/`), never inside library code.

---

## 7. Configuration Management

### The Rule

**Secrets in environment variables. Settings in config files. Code has neither.**

| Type | Where | Example |
|---|---|---|
| Secrets (API keys, tokens) | `.env` file (gitignored) | `OPENAI_API_KEY`, `DB_PASSWORD` |
| Environment-specific settings | `.env` file | `LOG_LEVEL`, `DEBUG_MODE` |
| Application config | `config/*.yaml` | topics, model names, schedules |
| Hardcoded defaults | `src/.../config.py` | fallback values when env var absent |

### `.env.example`

Always commit a `.env.example` that lists every variable the project needs, with placeholder values and a comment for each:

```bash
# Required — OpenAI API key for summarization
OPENAI_API_KEY=sk-...

# Required — Telegram bot token for delivery
TELEGRAM_BOT_TOKEN=...

# Optional — defaults to INFO
LOG_LEVEL=INFO
```

### Loading Config

Use `pydantic-settings` for typed, validated configuration:

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    openai_api_key: str
    telegram_bot_token: str
    log_level: str = "INFO"

    class Config:
        env_file = ".env"

settings = Settings()
```

---

## 8. Testing Standards

### Framework & Structure

Use `pytest`. Mirror the `src/` layout inside `tests/`:

```
tests/
├── conftest.py          # Shared fixtures
├── unit/
│   └── core/
│       └── test_fetcher.py
└── integration/
    └── test_api_client.py
```

### Rules

- **Unit tests** test one function in isolation — mock all external I/O.
- **Integration tests** test real interactions (DB, API) — use test credentials and teardown fixtures.
- **Every bug fix** ships with a regression test.
- **Test naming:** `test_<function_name>_<scenario>_<expected_outcome>`
  ```python
  def test_fetch_articles_empty_query_raises_value_error(): ...
  def test_summarize_returns_string_under_max_tokens(): ...
  ```
- **AAA pattern** — Arrange, Act, Assert. One assertion concept per test.
- **Target ≥ 80% coverage** for `src/core/`. Use `pytest-cov` to measure.

### `pyproject.toml` Test Config

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "--cov=src --cov-report=term-missing"

[tool.coverage.report]
exclude_lines = ["pragma: no cover", "if TYPE_CHECKING:"]
```

---

## 9. Git & Version Control

### Branching

| Branch | Purpose |
|---|---|
| `main` | Always deployable / production-ready |
| `dev` | Integration branch for ongoing work |
| `feat/<short-description>` | New feature |
| `fix/<short-description>` | Bug fix |
| `chore/<short-description>` | Tooling, deps, config — no logic change |
| `docs/<short-description>` | Documentation only |

### Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<optional scope>): <short imperative summary>

<optional body — explain WHY, not WHAT>
```

**Types:** `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `perf`, `ci`

```
# ✅ Good
feat(fetcher): add retry logic with exponential backoff
fix(digest): prevent duplicate articles in weekly report
chore(deps): upgrade pydantic to 2.7.0

# ❌ Bad
update code
fix bug
wip
```

### Pull Requests

- PRs must pass all CI checks before merge.
- PR title must follow the same Conventional Commits format as commits.
- Keep PRs small and focused — one concern per PR.
- Squash-merge feature branches into `main`/`dev` to keep history clean.

### `.gitignore` Essentials

```gitignore
# Environment
.env
.env.*
!.env.example

# Python
__pycache__/
*.pyc
*.pyo
.pytest_cache/
.mypy_cache/
.ruff_cache/
dist/
*.egg-info/

# Virtual environments
.venv/
venv/

# Editor
.vscode/
.idea/
*.swp

# Logs & data
logs/
*.log
data/raw/
```

---

## 10. Dependency Management

Use **`uv`** as the package and environment manager.

```bash
# Install a new dependency
uv add requests

# Install a dev-only dependency
uv add --dev pytest pytest-cov ruff mypy

# Sync environment from lockfile (reproducible install)
uv sync

# Run a command inside the project environment
uv run python scripts/run_digest.py
```

### Rules

- **Commit `uv.lock`** — this guarantees every developer and CI environment uses identical dependency versions.
- **Pin the Python version** in `.python-version` (e.g., `3.12`).
- **Separate dev dependencies** from runtime dependencies in `pyproject.toml`:
  ```toml
  [project]
  dependencies = ["pydantic", "httpx", "openai"]

  [dependency-groups]
  dev = ["pytest", "pytest-cov", "ruff", "mypy"]
  ```
- Review and update dependencies monthly. Use `uv lock --upgrade` to update the lockfile.
- Remove unused dependencies immediately.

---

## 11. Security Practices

- **Never commit secrets** — not even temporarily. Use `git-secrets` or a pre-commit hook to block it.
- **Rotate any secret that was accidentally committed** — git history is public even after deletion.
- **Validate all external inputs** — treat data from APIs, files, and users as untrusted.
- **Use `httpx` over `requests`** for async-native HTTP — it's more explicit about timeouts.
- **Always set timeouts** on HTTP calls: `httpx.get(url, timeout=10.0)`.
- **Avoid `eval()`, `exec()`, `pickle.loads()`** on untrusted data.
- Keep dependencies updated — outdated packages are the most common vulnerability vector.
- **Use `pydantic` for data validation at trust boundaries** — parse external data into typed models before using it.

---

## 12. CI/CD Conventions

Every project ships with a GitHub Actions workflow at `.github/workflows/ci.yml`.

### Minimum CI Pipeline

```yaml
name: CI

on:
  push:
    branches: [main, dev]
  pull_request:
    branches: [main, dev]

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version-file: .python-version

      - name: Install uv
        uses: astral-sh/setup-uv@v4

      - name: Install dependencies
        run: uv sync --all-groups

      - name: Lint
        run: uv run ruff check .

      - name: Format check
        run: uv run ruff format --check .

      - name: Type check
        run: uv run mypy src/

      - name: Test
        run: uv run pytest
```

### Makefile Shortcuts

Every project includes a `Makefile` so developers don't need to memorize commands:

```makefile
.PHONY: install lint format type-check test run clean

install:
	uv sync --all-groups

lint:
	uv run ruff check .

format:
	uv run ruff format .

type-check:
	uv run mypy src/

test:
	uv run pytest

check: lint type-check test  ## Run all quality checks

run:
	uv run python scripts/main.py

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type d -name .mypy_cache -exec rm -rf {} +
	find . -type d -name .ruff_cache -exec rm -rf {} +
```

---

## Quick Reference Card

| What | Command |
|---|---|
| Install dependencies | `make install` |
| Run all checks | `make check` |
| Auto-fix lint | `uv run ruff check --fix .` |
| Auto-format code | `make format` |
| Run tests | `make test` |
| Run tests with coverage | `uv run pytest --cov=src` |
| Add a dependency | `uv add <package>` |
| Add a dev dependency | `uv add --dev <package>` |

---

*This document is a living standard. Update it when the team adopts new tools, patterns, or conventions. All changes to this file follow the same PR and review process as production code.*
