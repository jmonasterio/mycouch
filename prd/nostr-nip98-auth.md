# PRD: Replace Clerk with Nostr NIP-98 Auth

**Status:** Draft  
**Scope:** MyCouch (proxy backend) + couch-sitter (PWA frontend)  
**Replaces:** Clerk RS256 JWT auth  
**With:** Nostr NIP-98 HTTP Auth (secp256k1 Schnorr) + server-issued session tokens

---

## Problem

MyCouch uses Clerk as its identity provider. This creates:
- Hard dependency on a commercial SaaS (Clerk) for every authenticated request
- Clerk-specific claims (`sub`, `azp`, `iss`) baked into every layer of both codebases
- `ClerkService` managing session metadata externally in Clerk's `public_metadata`
- Vendor lock-in with no portable user identity

**Goal:** Replace Clerk with Nostr NIP-98 HTTP Auth. The Nostr `pubkey` (hex secp256k1) becomes the stable user identifier. No central issuer. No SDK dependency. Verification is pure cryptography.

---

## What NIP-98 Is

A client signs an ephemeral kind-27235 Nostr event scoped to the exact URL + HTTP method, then base64-encodes the JSON and sends it as:

```
Authorization: Nostr <base64(JSON event)>
```

The server verifies:
1. `kind == 27235`
2. `created_at` within ±60 seconds of server time (replay protection)
3. `u` tag == absolute request URL (including query params)
4. `method` tag == HTTP method
5. Nostr event signature (secp256k1 Schnorr over SHA256 of canonical event serialization)
6. (Optional) `payload` tag == SHA256 hex of request body — enforced on POST/PUT/PATCH

Identity = `pubkey` field (32-byte hex secp256k1). This replaces Clerk's `sub`.

---

## Resolved Decisions

| Question | Decision |
|---|---|
| Existing user data | **Clean break** — wipe dev data; no migration script |
| Profile data (email/name) | **Not supported** — use pubkey as sole identity |
| Invite identifiers | **Pubkey replaces email** — invitations reference npub/hex pubkey |
| Crypto library | **`coincurve`** — leaner than pynostr; we implement the ~20-line event serialization ourselves |
| applicationId / azp replacement | **`APPLICATION_ID` env var** — single deployment = single app |
| nostr-universal integration | **Relative import** from sibling repo (`../nostr-universal/nostr-universal.js`) — not vendored; update import if published to npm |
| Per-request signing | **Session token exchange** — NIP-98 used once to authenticate; server issues a short-lived Bearer token for all subsequent requests |

---

## Identity Model After Migration

```
Nostr pubkey (hex, 64 chars)
  → SHA256 → user_{hash}   (CouchDB doc ID — same format as today, different input)
```

The `sub` field in user documents stores the raw Nostr pubkey hex instead of the Clerk user ID.

---

## Auth Flow

NIP-98 is the front door only. The client signs **once** to get a session token, then uses that Bearer token for everything — including PouchDB sync. This is structurally identical to the old Clerk flow; only the front door changes.

```
Client                             MyCouch
  |                                   |
  |-- POST /auth/session ------------->|  ← NIP-98 signed event, once
  |   Authorization: Nostr <b64>       |    verify pubkey sig
  |                                   |    ensure_user_exists(pubkey)
  |<-- { token, expires_in } ---------|  ← short-lived Bearer token (HMAC, server secret)
  |                                   |
  |-- PouchDB sync ------------------->|  ← Bearer <token>, reused for session lifetime
  |   Authorization: Bearer <token>    |
  |-- API calls ---------------------->|
  |   Authorization: Bearer <token>    |
```

**Session token details:**
- Issued by MyCouch (HMAC-SHA256, `SESSION_SECRET` env var)
- Contains: `pubkey`, `user_id`, `issued_at`, `expires_at`
- TTL: configurable, default 8 hours (`SESSION_TTL_SECONDS`)
- Stateless — no server-side session store; token is self-contained, verified on each request
- Revocation: not supported in v1; TTL is the bound

**`/auth/session` endpoint (new):**
- `POST /auth/session` — NIP-98 auth; returns `{ token, pubkey, expires_in }`
- `DELETE /auth/session` — Bearer auth; no-op server-side (stateless), returns 200; reserved for future revocation

---

## Backend: MyCouch

### Files to Delete

| File | Reason |
|---|---|
| `src/couchdb_jwt_proxy/clerk_service.py` | Entire Clerk SDK wrapper — dead |
| `tests/test_clerk_service.py` | Tests for deleted module |
| `tests/test_service_integration.py` | Clerk+CouchSitter integration tests — dead |
| `tests/test_legacy_app.py` | Tests APPLICATIONS dict loading which is removed |

### Files to Rewrite

**`src/couchdb_jwt_proxy/auth.py`** — NIP-98 verifier + session token issuance/verification

```python
def verify_nip98(
    authorization: str,       # "Nostr <base64>"
    url: str,                 # absolute request URL
    method: str,              # HTTP method
    body: bytes = b"",        # request body (for payload tag check)
    time_tolerance: int = 60  # seconds
) -> str:                     # returns pubkey hex; raises HTTPException(401) on failure

def issue_session_token(pubkey: str, user_id: str) -> dict:
    # Returns { token: str, expires_in: int }
    # HMAC-SHA256, encodes pubkey + user_id + exp as JSON payload

def verify_session_token(authorization: str) -> dict:
    # Strips "Bearer ", verifies HMAC, checks expiry
    # Returns { pubkey, user_id }; raises HTTPException(401) on failure
```

NIP-98 verification using `coincurve`:
- Decode base64 → parse JSON
- Validate `kind == 27235`, `created_at` within tolerance, `u` tag, `method` tag
- Compute canonical event hash: `SHA256(JSON([0, pubkey, created_at, kind, tags, content]))`
- Assert computed hash == `id` field
- Verify Schnorr sig (BIP-340) via `coincurve`
- On POST/PUT/PATCH: if `payload` tag present, verify `SHA256(body) == payload`

**`src/couchdb_jwt_proxy/auth_middleware.py`** — verify Bearer session token

```python
async def get_current_user(request: Request, authorization: Optional[str] = Header(None)):
    payload = verify_session_token(authorization)  # raises 401 on failure
    return {
        "user_id": payload["user_id"],
        "sub": payload["pubkey"],
        "email": None,
        "name": None,
        "issuer": "nostr",
        "azp": None,
    }
```

Remove: `clerk_service` global, `set_clerk_service()`, all ClerkService imports.

**`src/couchdb_jwt_proxy/main.py`** — strip Clerk, add `/auth/session`

Remove:
- `CLERK_ISSUER_URL`, `CLERK_SECRET_KEY` env var reads
- `APPLICATIONS` dict and `load_all_apps()` startup call
- JWKS client cache (`_jwks_clients`, `get_jwks_client`, `decode_token_unsafe`)
- `verify_clerk_jwt` function and all call sites
- `ClerkService` construction and `set_clerk_service()` call
- `clerk_service` module import

Add:
- `APPLICATION_ID = os.getenv("APPLICATION_ID", "roady")`
- `SESSION_SECRET = os.getenv("SESSION_SECRET")` — fail fast on startup if missing
- `SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", str(8 * 3600)))`
- `NIP98_TIME_TOLERANCE = int(os.getenv("NIP98_TIME_TOLERANCE", "60"))`
- `POST /auth/session` — verifies NIP-98, calls `ensure_user_exists(pubkey)`, returns session token
- `DELETE /auth/session` — returns 200 (no-op)

### Files with Targeted Changes

**`src/couchdb_jwt_proxy/couch_sitter_service.py`**
- Rename `_hash_sub(sub)` → `_hash_pubkey(pubkey)`; update all callers
- Remove `clerkSecretKey` and `issuer` fields from app document schema
- Remove `load_all_apps()` Clerk-specific fields
- `ensure_user_exists(pubkey, ...)` — `email` and `name` params become optional, default `None`

**`src/couchdb_jwt_proxy/tenant_routes.py`**
- Remove `azp` extraction and app ID derivation
- Replace with `APPLICATION_ID` from config
- `email` / `name` optional throughout

**`pyproject.toml`**
- Add: `coincurve`
- Remove: `clerk-backend-api` (if present as direct dep)

**`.env.example`**
- Remove: `CLERK_ISSUER_URL`, `CLERK_SECRET_KEY`
- Add: `APPLICATION_ID=roady`, `SESSION_SECRET=<random 32 bytes hex>`, `SESSION_TTL_SECONDS=28800`, `NIP98_TIME_TOLERANCE=60`

### Tests

**Delete:**
- `tests/test_clerk_service.py`
- `tests/test_service_integration.py`
- `tests/test_legacy_app.py`

**Rewrite:**

| File | Change |
|---|---|
| `tests/test_main.py` | Replace `mock_clerk_jwt_payload` fixtures with mock session token payloads; mock `verify_session_token` not `verify_clerk_jwt`; update error string assertions |
| `tests/test_jwt_fallback_fix.py` | Rename → `test_tenant_extraction.py`; replace JWKS/Clerk mocks; discovery chain logic unchanged |
| `tests/test_jwt_template_validation.py` | Replace Clerk mocks; test session token validation |
| `tests/test_jwt_token_leakage_fix.py` | Update mock target to `verify_session_token` |
| `tests/test_admin_tenant_protection.py` | Update mock target only |

**New:** `tests/test_nip98_auth.py`
- Unit tests for `verify_nip98` with real secp256k1 test vectors (generate with `coincurve`)
- Test each check independently: kind, timestamp, URL mismatch, method mismatch, bad sig, payload hash
- Unit tests for `issue_session_token` / `verify_session_token`: roundtrip, expiry, tampered token

---

## Frontend: couch-sitter

### Clerk Surface Area

| Location | Clerk Usage |
|---|---|
| `index.html` ~22-27 | CDN script tag loads `clerk.browser.js` with publishable key |
| `index.html` ~30-95 | `Clerk.load()` auth gate, `mountUserButton`, `mountSignIn` |
| `index.html` ~199-222 | Application form: `clerkIssuerId` + `clerkSecretKey` inputs |
| `index.html` ~267-272 | Application card: `clerkIssuerId` display |
| `js/db.js` ~7-74 | `clerkReady`, `waitForClerk()`, `isClerkSignedIn()`, `getClerkToken()` |
| `js/db.js` ~79-110 | PouchDB fetch interceptor: `Authorization: Bearer <jwt>` via `getClerkToken()` |
| `js/db.js` ~125-203 | Sync fetch interceptor: same; `waitForClerk(30000)` before sync |
| `js/db.js` ~499-530 | `addApplication()`: saves `clerkIssuerId`/`clerkSecretKey` to app doc |
| `js/app.js` ~37-38 | `newApplication` state: `clerkIssuerId`, `clerkSecretKey` fields |
| `js/app.js` ~197-215 | `resetNewApplication()`, `editApplication()`: populate Clerk fields |
| `js/app.js` ~247-248 | `saveApplication()`: passes Clerk fields to DB layer |
| `js/app.js` ~824 | `loadAuditLogs()`: calls `window.Clerk.session.getToken()` directly |

**`nostr-universal.js`** is a sibling repo (`../nostr-universal/nostr-universal.js`) that provides the complete Nostr auth stack: NIP-07, NIP-46 (remote signer / bunker), local nsec signer, session persistence, QR code generation, and a `NostrLoginFlow` state machine. It is a single zero-dependency ES module. This replaces the raw `nostr-tools` CDN load and the custom login UI that would otherwise need to be written from scratch.

### Auth Flow in the Browser

**Signer sources handled by `nostr-universal`:**
1. **NIP-07 extension** (Alby, nos2x, Flamingo) — extension holds private key, app never sees it
2. **NIP-46 remote signer** (bunker) — signs over relay via QR/URI flow
3. **Local nsec** — dev/fallback only (`allowLocalDev: true`); key held in memory, never persisted

**Login sequence:**
1. Import `NostrAuth` + `NostrLoginFlow` from `nostr-universal.js`
2. `NostrLoginFlow` handles the full state machine: extension check → QR/bunker → connected
3. On `onConnected(pubkey)`: app builds a NIP-98 event for `POST /auth/session` using `auth.sign(event)`
4. App POSTs to `/auth/session` → receives `{ token, expires_in }`
5. Token stored in `sessionStorage`; all subsequent requests use `Authorization: Bearer <token>`

**Session restore on page reload:**
```javascript
const auth = new NostrAuth({ relays: [...] });
const restored = await auth.restoreSession();
if (restored) {
    await refreshSession(); // re-sign /auth/session with restored signer
} else {
    loginFlow.start();
}
```

**Token refresh:** `getToken()` proactively re-signs `/auth/session` via `auth.sign()` when within 30 minutes of expiry. No user interaction needed if signer is available.

### `index.html` Changes

Remove:
- Clerk CDN script tag + publishable key
- `Clerk.load()` block and auth gate
- `Clerk.mountUserButton()` and `Clerk.mountSignIn()` calls
- Raw `nostr-tools` unpkg script tag
- Application form fields: `clerkIssuerId`, `clerkSecretKey` inputs + labels
- Application card: `clerkIssuerId` display

Add:
- `<script type="module">` importing `NostrAuth`, `NostrLoginFlow`, `LoginState`, `encodeNpub` from `../nostr-universal/nostr-universal.js` (or a vendored copy)
- Login overlay wired to `NostrLoginFlow` (extension button, QR section, bunker URI input, connected state) — use `login.html` from nostr-universal as the reference implementation
- User display: truncated npub + "Sign out" (`auth.logoutAll()`)

### `js/db.js` Changes

Replace `clerkReady`, `waitForClerk()`, `isClerkSignedIn()`, `getClerkToken()` with:

```javascript
// Set by login flow after /auth/session exchange
sessionToken: null,
sessionExpires: null,   // Unix timestamp (seconds)
auth: null,             // NostrAuth instance, set during init

async waitForNostr(maxWait = 30000) {
    const start = Date.now();
    while (!this.sessionToken && Date.now() - start < maxWait) {
        await new Promise(r => setTimeout(r, 200));
    }
    return !!this.sessionToken;
},

isSignedIn() {
    return !!this.sessionToken && Math.floor(Date.now() / 1000) < this.sessionExpires;
},

async getToken() {
    if (this.sessionToken && (this.sessionExpires - Math.floor(Date.now() / 1000)) < 1800) {
        await this.refreshSession();
    }
    return this.sessionToken;
},

async refreshSession() {
    // Build NIP-98 event for POST /auth/session, sign via auth.sign()
    const url = new URL('/auth/session', window.location.origin).toString();
    const event = { kind: 27235, created_at: Math.floor(Date.now() / 1000),
                    tags: [['u', url], ['method', 'POST']], content: '' };
    const signed = await this.auth.sign(event);
    const authHeader = 'Nostr ' + btoa(JSON.stringify(signed));
    const resp = await fetch('/auth/session', {
        method: 'POST',
        headers: { Authorization: authHeader }
    });
    if (!resp.ok) throw new Error('Session refresh failed: ' + resp.status);
    const { token, expires_in } = await resp.json();
    this.sessionToken = token;
    this.sessionExpires = Math.floor(Date.now() / 1000) + expires_in;
    sessionStorage.setItem('session_token', token);
    sessionStorage.setItem('session_expires', this.sessionExpires);
},
```

The two fetch interceptors replace `getClerkToken()` with `await this.getToken()` — same call structure, same `Authorization: Bearer <token>` injection. No per-request signing in the hot path.

`addApplication()`: remove `clerkIssuerId`/`clerkSecretKey` fields.  
`setupSync()`: replace `waitForClerk()` with `waitForNostr()`.

### `js/app.js` Changes

- Remove `clerkIssuerId`/`clerkSecretKey` from `newApplication` state, `resetNewApplication()`, `editApplication()`, `saveApplication()`
- Replace `window.Clerk.session.getToken()` in `loadAuditLogs()` with `await DB.getToken()`

### `sw.js` Changes

- `nostr-universal.js` is a local file (vendored or sibling repo path) — no CDN dependency, no SW cache change needed
- Remove the raw `unpkg.com/nostr-tools` entry if it was added

---

## Implementation Order

### Phase 1: Backend
1. Add `coincurve` to `pyproject.toml`; remove `clerk-backend-api`
2. Rewrite `auth.py` — `verify_nip98`, `issue_session_token`, `verify_session_token`
3. Write `tests/test_nip98_auth.py` — unit tests with real key material
4. Rewrite `auth_middleware.py` — wire `verify_session_token`, drop ClerkService
5. Update `main.py` — remove Clerk infra, add `SESSION_SECRET`, add `/auth/session` endpoint
6. Update `couch_sitter_service.py` — rename hash fn, remove Clerk fields, make email/name optional
7. Update `tenant_routes.py` — remove `azp`, wire `APPLICATION_ID`
8. Delete `clerk_service.py`, dead test files
9. Rewrite remaining tests — new fixtures, updated mocks

### Phase 2: Frontend
10. Import `nostr-universal.js` via relative path from sibling repo (`../nostr-universal/nostr-universal.js`) — both repos live side-by-side under the same parent; relative import keeps changes to nostr-universal immediately visible without a copy step. Update the import path if nostr-universal is ever published to npm.
11. Implement Nostr login overlay in `index.html` using `NostrAuth` + `NostrLoginFlow` — use `login.html` from nostr-universal as the reference implementation
12. Wire `onConnected(pubkey)` callback to call `DB.refreshSession()` then show main UI
13. Rewrite `db.js` — `auth` instance (NostrAuth), session token management, `getToken()`, `refreshSession()` using `auth.sign()`
14. Implement `auth.restoreSession()` on page load to skip login UI when session is already saved
15. Clean `app.js` — remove Clerk fields from application model
16. `sw.js` — no changes needed (nostr-universal is a local file)

### Phase 3: Cleanup
17. Update `.env.example` and docs
18. Run full test suite
19. Manual end-to-end: login with Alby extension → `/auth/session` → PouchDB sync → tenant creation
20. Manual end-to-end: login with NIP-46 bunker (QR flow) → same

---

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| `SESSION_SECRET` missing in prod | Medium | Fail fast on startup with explicit error |
| Token stolen from sessionStorage (XSS) | Low | Same risk as any Bearer token; same-origin mitigates scope |
| Users without a Nostr keypair | Medium | `NostrLoginFlow` covers NIP-07 + NIP-46 + local nsec; key generation available via `LocalSigner.generate()` |
| `coincurve` BIP-340 Schnorr support | Low | Verify before writing; `secp256k1` library is fallback |
| nostr-universal breaking changes | Low | It’s new and may shift; relative import means updates are immediate — check nostr-universal changelog before starting Phase 2 |
| NIP-46 relay connectivity | Medium | Bunker flow requires WebSocket relay; relay outage blocks NIP-46 login; NIP-07 users unaffected |
| Token expiry mid-sync | Low | `getToken()` proactively refreshes 30 min before expiry |
