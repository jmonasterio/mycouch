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
	PYTHONPATH=src uv run python -m couchdb_jwt_proxy.main

dev-run:
	PYTHONPATH=src uv run uvicorn couchdb_jwt_proxy.main:app --reload --port 5985

test:
	uv run pytest tests -v

test-cov:
	uv run pytest tests -v --cov=couchdb_jwt_proxy --cov-report=html --cov-report=term-missing
	@echo "Coverage report: htmlcov/index.html"

test-watch:
	uv run pytest tests -v --looponfail

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
	uv run black src/couchdb_jwt_proxy tests
	uv run isort src/couchdb_jwt_proxy tests

lint:
	uv run flake8 src/couchdb_jwt_proxy tests
	uv run black --check src/couchdb_jwt_proxy tests
	uv run isort --check-only src/couchdb_jwt_proxy tests
