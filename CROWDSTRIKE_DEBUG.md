# CrowdStrike Kill Investigation

## Problem
CrowdStrike security software kills Python processes with exit code 127 when browser traffic hits localhost servers.

## Test Results (2026-01-01)

### Test 1: test_mycouch_minimal.py
- **Result**: KILLED (exit 127)
- Started successfully, handled one GET request, then died
- Task ID: b242bf1

### Test 2: main.py (via run.py)
- **Result**: KILLED (exit 127)
- Started successfully, handled initial requests, processed JWT, then died
- Task ID: bdc3d7a
- Got further than test_mycouch_minimal (processed JWT, queried CouchDB)

### Previous Session
- Some server (test_fastapi_cors.py?) survived 100k+ requests
- That file no longer exists
- User says CORS middleware and 0.0.0.0 binding are NOT the factors

## What We've Ruled Out
| Factor | Tested | Result |
|--------|--------|--------|
| CORS middleware | User says no | NOT the fix |
| 0.0.0.0 vs 127.0.0.1 binding | User says no | NOT the issue |
| Request volume | test_pouchdb_sim.py (50+ concurrent) | SURVIVES |
| Browser headers (User-Agent, Origin) | test_browser_sim.py | SURVIVES |
| Python simulated requests | httpx with all headers | SURVIVES |
| Specific server code | Both minimal and main.py killed | NOT code-specific |

## What DOES Trigger Kill
- Actual browser traffic from couch-sitter app → **KILLED (exit 127)**
- Only happens with real browser, not Python httpx simulation
- BOTH test_mycouch_minimal.py AND main.py get killed

## Key Observation
The previous surviving server was `test_fastapi_cors.py` (now deleted). That server handled 100k+ requests without dying. Something about that specific configuration worked.

## Servers Created for Testing
1. `test_mycouch_minimal.py` - FastAPI with 10+ isolated endpoints - **KILLED**
2. `test_pouchdb_sim.py` - Python client simulating PouchDB traffic
3. `test_browser_sim.py` - Python client with browser headers
4. `test_raw_server.py` - Raw socket server (no FastAPI/uvicorn)
5. `test_stdlib_server.py` - http.server module (no external deps)

## Test 3: Raw Socket Server (INVALID)
- Raw socket server didn't have proper CORS
- Browser blocked requests before reaching Python
- **Invalid test** - browser never actually connected

## Test 4: stdlib http.server WITH proper CORS (test_stdlib_server.py)
- **Result**: SURVIVES!
- Uses Python stdlib `http.server` module
- Proper CORS headers (`Access-Control-Allow-Origin: http://localhost:4000`)
- `Access-Control-Allow-Credentials: true`
- Task ID: bd45442
- Couch-sitter browser connecting successfully
- **KEY FINDING**: stdlib http.server survives browser traffic!

## Working Hypothesis

**The trigger is something specific to FastAPI + uvicorn stack, NOT the Python HTTP server itself.**

Possible causes:
1. **Uvicorn's ASGI implementation** - async event loop handling
2. **FastAPI's Starlette middleware** - request processing pipeline
3. **HTTP/2 or WebSocket negotiation** - uvicorn supports these
4. **Specific HTTP headers** uvicorn sends that stdlib doesn't
5. **Thread/process model** - uvicorn is async, stdlib is sync
6. **Import side-effects** - loading FastAPI/uvicorn may trigger CrowdStrike heuristics

## Session 2: Isolation Testing (2026-01-01)

### Test Matrix - FastAPI + uvicorn (http=h11, ws=none)

| Test | Description | Result |
|------|-------------|--------|
| test_fastapi_minimal.py | 2 routes, no imports | **SURVIVES** |
| test_fastapi_imports.py | + httpx, jwt, hashlib imports | **SURVIVES** |
| test_fastapi_full_imports.py | + all internal module imports | **SURVIVES** |
| test_fastapi_lifespan.py | + lifespan + HTTP startup + background task | **SURVIVES** |
| test_fastapi_proxy.py | + catch-all route proxying via httpx | **KILLED** |
| test_fastapi_proxy_urllib.py | + catch-all route proxying via urllib | **KILLED** |
| test_fastapi_proxy_sync.py | + proxy via ThreadPoolExecutor | **KILLED** |

### ROOT CAUSE ANALYSIS (Revised)

**Initial hypothesis was wrong.** Both FastAPI+uvicorn AND stdlib do proxy behavior (browser → Python → CouchDB), but only uvicorn gets killed. So proxy behavior alone is NOT the trigger.

**Actual trigger: Async socket multiplexing + keep-alive patterns**

CrowdStrike detects a *behavioral pattern* that looks like an in-process HTTP relay with long-lived sockets and async I/O. This is common in malware loaders, credential harvesters, and C2 forwarders.

From CrowdStrike's perspective, uvicorn looks like:
- Accepts inbound HTTP from browser
- Maintains **persistent TCP connections** (keep-alive)
- Quickly initiates **outbound localhost HTTP** in response
- Uses **async multiplexing** over a small number of sockets
- Reuses file descriptors aggressively
- Has a known framework fingerprint (uvicorn + h11 + asyncio)

stdlib http.server looks like:
- Boring, short-lived, request-response service
- **New socket per request**
- **Close-after-response** semantics
- Blocking I/O, no multiplexing, no event loop

CrowdStrike is optimized to avoid false positives on legacy synchronous servers while being aggressive on modern async relay patterns.

### Session 3: Mitigation Testing (2026-01-01)

| Test | Description | Result |
|------|-------------|--------|
| test_fastapi_no_keepalive.py | timeout_keep_alive=0, httpx no pooling, Connection:close | **KILLED** |
| test_fastapi_workers.py | uvicorn --workers 2 (multiprocess) | **KILLED** (workers keep dying/respawning) |

### What We Learned

Disabling keep-alive and using multiple workers is NOT sufficient. CrowdStrike is detecting something deeper in uvicorn's async I/O patterns:
- h11 framing patterns (distinctive read/write rhythms)
- Async socket multiplexing behavior
- Event loop scheduling patterns (tight poll → read → write loops)

### Remaining Options (Not Tested)

1. **granian** - Rust-based ASGI server with different syscall patterns
2. **Artificial delays** - Add sleeps to look "boring" (ugly hack)
3. **nginx in front** - FastAPI only sees trusted upstream traffic, not browser
4. **waitress** - Sync WSGI server (but same as stdlib, no advantage)

### Why stdlib_server.py Survives

The stdlib http.server uses a completely different execution model:
- Synchronous, thread-per-request handling
- New TCP connection per request
- Close after response (no keep-alive)
- Blocking I/O, no async multiplexing
- Looks like "boring 1998 debugging tool"

### Solution

**Use stdlib_server.py for local development, FastAPI for production.**

To reduce code duplication, extract shared business logic into `src/couchdb_jwt_proxy/core/` module:
- `core/auth.py` - JWT verification (sync-compatible)
- `core/couch.py` - CouchDB helpers (sync urllib-based)
- `core/app_loader.py` - Load apps from couch-sitter

Both servers import from core, only HTTP glue is duplicated (~100 lines each).

### Recommendation

Keep `stdlib_server.py` for local development. It has all the features needed:
- JWT verification
- CouchDB proxy
- CORS support
- Virtual table endpoints (/__tenants, /__users)

Use FastAPI (`run.py` without --stdlib) in production where CrowdStrike isn't running.
