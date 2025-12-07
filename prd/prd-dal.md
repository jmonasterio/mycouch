Product Requirements Document (PRD)
Project: CouchDB DAL with Memory Fallback for Unit Tests

Author: [Your name]
Date: 2025-11-11
Status: Draft

1. Overview

We maintain a lightweight Python proxy in front of CouchDB that supports a specific subset of endpoints (e.g., _find, _bulk_docs, _changes, etc.).
During unit tests, we want to avoid depending on Dockerized CouchDB instances. Instead, the proxy should transparently use an in-memory database that mimics CouchDB’s behavior for the supported API subset.

This component will be a DAL (Data Access Layer) that:

Abstracts all database operations.

Supports two backends:

CouchDBBackend: real HTTP-based access to CouchDB.

MemoryBackend: in-memory emulation for test isolation.

Auto-selects the backend at runtime (e.g., detects pytest or test env variable).

2. Goals & Non-Goals
Goals

Enable unit tests to run without a live CouchDB instance.

Provide a drop-in replacement that adheres to the same endpoint contracts as the proxy.

Keep behavior deterministic and fast.

Allow switching backend via environment variable or auto-detection.

Support the following minimal API surface:

/_local/ (GET, PUT, DELETE)

/_all_docs

/_find

/_bulk_docs

/_changes

/_revs_diff

/_bulk_get

/_session

/ (GET for metadata)

Non-Goals

Not aiming to replicate full CouchDB semantics (e.g., revision trees, attachments, views).

Not intended for performance benchmarking.

Not for multi-process consistency testing.

3. Functional Requirements
Endpoint	Method	Expected Memory Behavior
/_local/{id}	GET	Return doc if exists in local_docs dict
/_local/{id}	PUT	Store or update local checkpoint doc
/_local/{id}	DELETE	Remove from local_docs
/_all_docs	GET	Return list of doc IDs + basic info
/_find	POST	Support basic Mango-like queries over stored docs
/_bulk_docs	POST	Insert/update multiple docs at once
/_changes	GET/POST	Return change sequence (append-only counter)
/_revs_diff	POST	Return missing revisions for given doc IDs
/_bulk_get	POST	Retrieve docs by ID (optionally revision)
/_session	GET/POST	Return dummy authenticated session info
/	GET	Return mock DB metadata (doc count, sizes, etc.)
4. Architecture
4.1 DAL Structure
class CouchDAL:
    def __init__(self, backend: Optional[str] = None):
        # backend = 'couch' | 'memory' | None (auto-detect)
        if backend is None:
            backend = "memory" if _is_test_env() else "couch"
        self.backend = _get_backend(backend)

    def get(self, path, method, payload=None):
        return self.backend.handle_request(path, method, payload)

4.2 Backend Abstractions
class BaseBackend(ABC):
    @abstractmethod
    def handle_request(self, path, method, payload): ...

CouchBackend

Performs real HTTP requests to CouchDB.

Reuses existing proxy auth/config.

MemoryBackend

Uses Python dicts for:

docs: normal documents.

local_docs: _local/* docs.

changes: list of change entries.

Implements JSON-based semantics for supported endpoints.

Increments a seq counter on every mutation.

Provides thread-safe access using threading.Lock().

5. Auto-Detection Logic
Priority order

If env var DAL_BACKEND=memory, always use memory.

If pytest is detected ("pytest" in sys.modules), use memory.

Otherwise, use real CouchDB.

def _is_test_env():
    import os, sys
    return "pytest" in sys.modules or os.getenv("DAL_BACKEND") == "memory"

6. Testing Strategy

Unit tests use the memory backend by default.

Integration tests may set DAL_BACKEND=couch to hit a live CouchDB instance.

Mock and snapshot tests verify parity across both modes.

Key invariants:

/_bulk_docs followed by /_all_docs must return the same set of docs in both modes.

Change feed order and _seq must be deterministic.

7. Performance and Scalability

Memory mode limited to a few thousand docs per test.

No persistence — cleared between tests or via fixture teardown.

Thread safety required for concurrent requests in proxy tests.

8. Example Usage
# dal.py
dal = CouchDAL()  # auto selects backend

response = dal.get("/_find", "POST", {"selector": {"type": "task"}})

# test_dal.py (pytest)
from dal import CouchDAL

def test_insert_and_query():
    dal = CouchDAL()
    dal.get("/_bulk_docs", "POST", {"docs": [{"_id": "a", "type": "task"}]})
    res = dal.get("/_find", "POST", {"selector": {"type": "task"}})
    assert len(res["docs"]) == 1

9. Future Enhancements

Optional persistence via SQLite for integration testing.

Support _design docs and views.

Partial conflict/revision emulation.

Metrics hooks to measure DAL coverage.