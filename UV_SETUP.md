# uv Setup Guide

This project uses [uv](https://github.com/astral-sh/uv) - a fast Python package installer and resolver written in Rust.

## Installing uv

### Option 1: Using pip (Recommended)
```bash
pip install uv
```

### Option 2: Using pipx
```bash
pipx install uv
```

### Option 3: Direct Installation
See [uv installation guide](https://github.com/astral-sh/uv#installation)

## Project Structure

```
mycouch/
├── pyproject.toml         # uv project configuration
├── Makefile               # Linux/macOS commands
├── run.ps1               # Windows PowerShell script
├── run.bat               # Windows CMD script
├── main.py               # FastAPI application
├── test_main.py          # Unit tests
├── config/
│   └── api_keys.json     # API key configuration
└── .env.example          # Environment template
```

## Commands

### Installation

```bash
# Install dependencies
uv sync

# Install with development dependencies
uv sync --all-extras
```

### Running the Application

```bash
# Production mode
uv run python main.py

# Development mode (auto-reload)
uv run uvicorn main:app --reload --port 5984
```

### Running Tests

```bash
# Run all tests
uv run pytest test_main.py -v

# Run with coverage
uv run pytest test_main.py -v --cov=main --cov-report=html
```

### Using Make Commands (Linux/macOS)

```bash
# Show all available commands
make help

# Install dependencies
make install
make dev

# Run application
make run
make dev-run

# Run tests
make test
make test-cov

# Cleanup
make clean
make env-setup
```

### Using Scripts (Windows)

**PowerShell:**
```powershell
# Show help
.\run.ps1 help

# Install
.\run.ps1 install
.\run.ps1 dev

# Run
.\run.ps1 run
.\run.ps1 dev-run

# Test
.\run.ps1 test
.\run.ps1 test-cov

# Cleanup
.\run.ps1 clean
.\run.ps1 env-setup
```

**Command Prompt:**
```cmd
# Show help
run.bat help

# Install
run.bat install
run.bat dev

# Run
run.bat run
run.bat dev-run

# Test
run.bat test
run.bat test-cov

# Cleanup
run.bat clean
run.bat env-setup
```

## Configuration Files

### pyproject.toml
Contains all project metadata and dependencies:
- Main dependencies (FastAPI, uvicorn, PyJWT, httpx, etc.)
- Development dependencies (pytest, pytest-asyncio, pytest-cov)
- Tool configurations (pytest, coverage)

### .env.example
Template for environment variables:
```bash
JWT_SECRET=your-super-secret-key-change-this
COUCHDB_INTERNAL_URL=http://localhost:5983
PROXY_PORT=5984
LOG_LEVEL=INFO
```

Copy to `.env` and update with your values:
```bash
cp .env.example .env
```

### .gitignore
Configured to ignore:
- Python cache files (`__pycache__`, `.pyc`)
- Virtual environments (`venv/`, `.venv`)
- Test artifacts (`.pytest_cache`, `htmlcov/`)
- Environment files (`.env`)
- uv lock file (`uv.lock`) - optional, for reproducible installs
- IDE files (`.vscode/`, `.idea/`)

## Quick Start

### 1. Install uv
```bash
pip install uv
```

### 2. Clone or setup project
```bash
cd mycouch
```

### 3. Install dependencies
```bash
uv sync --all-extras
```

### 4. Setup environment
```bash
cp .env.example .env
# Edit .env with your settings
```

### 5. Run tests
```bash
uv run pytest test_main.py -v
```

### 6. Start the proxy
```bash
uv run python main.py
```

Server runs on `http://localhost:5984`

## Benefits of uv

- ⚡ **Fast** - 5-10x faster than pip
- 🔒 **Deterministic** - Reproducible installs with `uv.lock`
- 📦 **Unified** - Single tool for pip, pip-tools, venv
- 🎯 **Project-based** - Easy project management with `pyproject.toml`
- 🚀 **Modern** - Written in Rust, no external dependencies

## Troubleshooting

### "uv: command not found"
Make sure uv is installed:
```bash
pip install uv --upgrade
```

### "ModuleNotFoundError" when running
Make sure dependencies are installed:
```bash
uv sync --all-extras
```

### Tests not running
Install development dependencies:
```bash
uv sync --all-extras
uv run pytest test_main.py -v
```

### Permission denied on scripts (Windows PowerShell)
Allow script execution:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

## Further Reading

- [uv Documentation](https://github.com/astral-sh/uv)
- [pyproject.toml Guide](https://python-poetry.org/docs/pyproject/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
