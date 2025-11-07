# Project Structure

Standard Python project layout for CouchDB JWT Proxy.

```
mycouch/
├── src/
│   └── couchdb_jwt_proxy/              # Main package
│       ├── __init__.py
│       └── main.py                     # FastAPI application
│
├── tests/
│   ├── __init__.py
│   └── test_main.py                    # Unit tests
│
├── scripts/                            # Utility scripts
│   ├── generate_secret.py              # Generate secure JWT secret
│   ├── generate_jwt.py                 # Generate test tokens
│   └── run_local_couchdb.sh            # Docker CouchDB startup
│
├── docs/                               # Documentation
│   ├── README.md                       # Documentation index
│   ├── GETTING_STARTED.md              # Quick start guide
│   ├── CLERK_SETUP.md                  # Clerk JWT configuration
│   ├── LINUX_DEPLOYMENT_PROXY.md       # Server deployment
│   ├── GITHUB_ACTIONS_DEPLOY.md        # CI/CD setup
│   ├── SECURITY_CHECKLIST.md           # Security requirements
│   ├── TENANT_DETERMINATION.md         # Tenant isolation
│   ├── DEBUGGING.md                    # Troubleshooting
│   └── ... (more documentation)
│
├── prd/                                # Product Requirements
│   ├── README.md                       # PRD index
│   ├── PRD.md                          # Main requirements
│   ├── PRD-jwt-proxy.md                # JWT strategy
│   └── prd-tenant-creation.md          # Multi-tenant model
│
├── .github/
│   └── workflows/
│       └── deploy-proxy.yml            # GitHub Actions workflow
│
├── .env                                # Environment (in .gitignore)
├── .env.example                        # Environment template
├── .gitignore
├── pyproject.toml                      # Project metadata & dependencies
├── README.md                           # Main documentation
├── CLAUDE.md                           # Development context
└── PROJECT_STRUCTURE.md                # This file
```

## Directory Descriptions

### `src/couchdb_jwt_proxy/`
Main application package. Contains the FastAPI proxy application.

**Current structure (Phase 1):**
- `main.py` - Single-file FastAPI application

**Future structure (Phase 2 - optional modularization):**
```
src/couchdb_jwt_proxy/
├── main.py
├── auth/
│   ├── __init__.py
│   ├── jwt_validation.py     # JWT verification logic
│   ├── clerk.py              # Clerk JWT (RS256)
│   └── custom.py             # Custom JWT (HS256)
├── proxy/
│   ├── __init__.py
│   └── forward.py            # CouchDB forwarding
└── tenant/
    ├── __init__.py
    └── isolation.py          # Tenant filtering
```

### `tests/`
Unit and integration tests using pytest.

**Contents:**
- `test_main.py` - Tests for FastAPI routes and JWT validation
- Future: Split into `test_auth.py`, `test_proxy.py`, `test_tenant.py`

### `scripts/`
Utility scripts for development and operations.

**Planned contents:**
- `run_local_couchdb.sh` - Docker CouchDB startup

### `docs/`
Comprehensive documentation for setup, deployment, and development.

**Contents:**
- Setup guides (GETTING_STARTED.md, DOCKER_SETUP.md)
- Configuration guides (CLERK_SETUP.md, TENANT_MODE.md)
- Deployment guides (LINUX_DEPLOYMENT_PROXY.md, GITHUB_ACTIONS_DEPLOY.md)
- Development guides (DEBUGGING.md, INTEGRATION_PLAN.md)
- Security documentation (SECURITY_CHECKLIST.md, SECURITY_AUDIT_SUMMARY.md)
- Feature documentation (TENANT_DETERMINATION.md)

### `prd/`
Product Requirements Documents describing vision and design.

**Contents:**
- PRD.md - Overall product vision
- PRD-jwt-proxy.md - JWT authentication strategy
- prd-tenant-creation.md - Multi-tenant CouchDB model

### `.github/workflows/`
GitHub Actions CI/CD configuration.

**Contents:**
- `deploy-proxy.yml` - Automated deployment workflow

## Running the Project

### Development
```bash
# Install dependencies
uv sync --all-extras

# Run tests
uv run pytest tests/ -v

# Start proxy
uv run uvicorn src.couchdb_jwt_proxy.main:app --reload --port 5985
```

### Production
```bash
# Install dependencies
uv sync

# Start proxy
uv run uvicorn src.couchdb_jwt_proxy.main:app --host 0.0.0.0 --port 5985
```

## Import Paths

After reorganization, imports follow standard Python conventions:

```python
# Import from main application
from src.couchdb_jwt_proxy.main import app, create_jwt_token

# Run tests
pytest tests/

# Test coverage
pytest tests/ --cov=src.couchdb_jwt_proxy
```

## Migration Guide

If you were using the old flat structure:

**Old:**
```bash
python main.py
pytest test_main.py -v
```

**New:**
```bash
uv run uvicorn src.couchdb_jwt_proxy.main:app
uv run pytest tests/ -v
```

## Future Modularization

As the project grows, consider modularizing `main.py`:

1. **Phase 1** (Current): Single `main.py` file
2. **Phase 2**: Split into `auth/`, `proxy/`, `tenant/` modules
3. **Phase 3**: Add CLI commands via Click or Typer
4. **Phase 4**: Add package to PyPI

## Standards Followed

- **Python**: PEP 420 namespace packages, standard directory layout
- **Testing**: pytest in `tests/` directory, coverage reporting
- **Documentation**: Markdown in `docs/` directory
- **Configuration**: Standard `pyproject.toml` for metadata
- **Project Metadata**: `src/` layout with package in `couchdb_jwt_proxy/`

## Related Files

- `README.md` - Main user documentation
- `CLAUDE.md` - Development context
- `pyproject.toml` - Updated to reference new paths
- `.gitignore` - Already excludes `.env` and config files
