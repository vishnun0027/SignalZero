.PHONY: lint test run

lint:
	uv run ruff check .

test:
	uv run pytest tests/unit/ -v

run:
	uv run python scripts/main.py
