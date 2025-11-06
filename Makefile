.PHONY: help install dev test run clean lint format

help:
	@echo "CouchDB JWT Proxy - uv commands"
	@echo ""
	@echo "Setup & Installation:"
	@echo "  make install       Install dependencies"
	@echo "  make dev          Install with dev dependencies"
	@echo ""
	@echo "Running:"
	@echo "  make run          Run the proxy server"
	@echo "  make dev-run      Run with auto-reload"
	@echo ""
	@echo "Testing:"
	@echo "  make test         Run all tests"
	@echo "  make test-cov     Run tests with coverage report"
	@echo "  make test-watch   Run tests in watch mode"
	@echo ""
	@echo "Utilities:"
	@echo "  make clean        Remove __pycache__ and .pytest_cache"
	@echo "  make env-setup    Create .env file from .env.example"
	@echo ""

install:
	uv sync

dev:
	uv sync --all-extras

run:
	uv run python main.py

dev-run:
	uv run uvicorn main:app --reload --port 5984

test:
	uv run pytest test_main.py -v

test-cov:
	uv run pytest test_main.py -v --cov=main --cov-report=html --cov-report=term-missing
	@echo "Coverage report: htmlcov/index.html"

test-watch:
	uv run pytest test_main.py -v --looponfail

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name htmlcov -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name .coverage -delete 2>/dev/null || true
	find . -type d -name .uv -exec rm -rf {} + 2>/dev/null || true

env-setup:
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo ".env file created. Please update with your settings."; \
	else \
		echo ".env file already exists."; \
	fi

format:
	uv run black main.py test_main.py
	uv run isort main.py test_main.py

lint:
	uv run flake8 main.py test_main.py
	uv run black --check main.py test_main.py
	uv run isort --check-only main.py test_main.py
