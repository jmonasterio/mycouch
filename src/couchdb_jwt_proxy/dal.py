"""
CouchDB Data Access Layer (DAL) with Memory Fallback

Provides a unified interface for accessing CouchDB with automatic backend selection:
- CouchBackend: Real HTTP-based access to CouchDB
- MemoryBackend: In-memory emulation for test isolation

Auto-detects test environment and switches to memory backend for unit tests.
"""

import os
import sys
import json
import asyncio
import threading
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Union
from urllib.parse import urlparse
import uuid
import time
import httpx
import logging

logger = logging.getLogger(__name__)


def _is_test_env() -> bool:
    """Auto-detect if we're running in a test environment."""
    return "pytest" in sys.modules or os.getenv("DAL_BACKEND") == "memory"


class BaseBackend(ABC):
    """Abstract base class for DAL backends."""

    @abstractmethod
    async def handle_request(self, path: str, method: str, payload: Optional[Dict] = None, params: Optional[Dict] = None) -> Any:
        """
        Handle a CouchDB-like request.

        Args:
            path: The CouchDB endpoint path (e.g., "/_find")
            method: HTTP method ("GET", "POST", "PUT", "DELETE")
            payload: Optional request payload for POST/PUT requests
            params: Optional query parameters

        Returns:
            Response data mimicking CouchDB format
        """
        pass


class MemoryBackend(BaseBackend):
    """In-memory CouchDB emulator for testing."""

    def __init__(self):
        self._docs: Dict[str, Dict] = {}  # Regular documents
        self._local_docs: Dict[str, Dict] = {}  # _local documents
        self._changes: List[Dict] = []  # Change feed
        self._seq = 0  # Sequence counter
        self._lock = asyncio.Lock()  # Async lock for thread safety in async context

    def _get_doc_id(self, doc: Dict) -> str:
        """Extract document ID, generate if needed."""
        if "_id" not in doc:
            doc["_id"] = str(uuid.uuid4())
        return doc["_id"]

    def _get_rev(self, doc: Dict) -> str:
        """Generate a revision string."""
        return f"{int(time.time())}-{uuid.uuid4().hex[:8]}"

    def _increment_seq(self) -> int:
        """Increment and return sequence number."""
        self._seq += 1
        return self._seq

    def _add_change(self, doc_id: str, doc: Dict, deleted: bool = False):
        """Add entry to change feed."""
        change = {
            "seq": self._increment_seq(),
            "id": doc_id,
            "changes": [{"rev": doc.get("_rev", "1-")}],
            "deleted": deleted
        }
        self._changes.append(change)

    async def handle_request(self, path: str, method: str, payload: Optional[Dict] = None, params: Optional[Dict] = None) -> Any:
        """Handle CouchDB-like requests in memory."""
        async with self._lock:
            # Parse path
            path = path.strip('/')
            parts = path.split('/')

            if not parts or parts == ['']:
                # Root path "/"
                if method == "GET":
                    return {
                        "couchdb": "Welcome",
                        "version": "3.3.3",
                        "features": ["scheduler"],
                        "vendor": {"name": "The Apache Software Foundation"}
                    }

            # Handle global endpoints
            if parts[0] == "_session":
                # Session information
                if method == "GET":
                    return {
                        "ok": True,
                        "userCtx": {"name": None, "roles": ["_admin"]},
                        "info": {"authentication_handlers": ["default"], "authenticated": "default"}
                    }
                elif method == "POST":
                    return {"ok": True}
                return {"error": "method_not_allowed", "reason": "Method not allowed"}

            # For all other endpoints, assume first part is db_name
            # We'll ignore the actual db_name for memory backend simplicity (single shared state)
            # unless we want to implement multi-db support.
            # For now, flattening is sufficient for existing tests.
            if len(parts) < 1:
                 return {"error": "bad_request", "reason": "Invalid path"}
            
            # db_name = parts[0]
            # Shift parts to handle the rest of the path
            parts = parts[1:]

            if not parts:
                # GET /db_name
                if method == "GET":
                    return {
                        "db_name": "memory_db",
                        "doc_count": len(self._docs),
                        "doc_del_count": 0,
                        "update_seq": self._seq,
                        "disk_size": 0,
                        "data_size": 0,
                        "instance_start_time": "0"
                    }
                elif method == "PUT":
                    # Create DB - no-op for memory backend
                    return {"ok": True}
                elif method == "DELETE":
                    # Delete DB - clear data
                    self._docs.clear()
                    self._local_docs.clear()
                    self._changes.clear()
                    self._seq = 0
                    return {"ok": True}

            elif parts[0] == "_local":
                # _local documents
                if len(parts) == 2:
                    doc_id = parts[1]

                    if method == "GET":
                        if doc_id in self._local_docs:
                            return self._local_docs[doc_id]
                        return {"error": "not_found", "reason": "deleted"}

                    elif method == "PUT":
                        if not payload:
                            return {"error": "bad_request", "reason": "missing body"}
                        self._local_docs[doc_id] = payload
                        return {"ok": True, "id": f"_local/{doc_id}", "_rev": "1-"}

                    elif method == "DELETE":
                        if doc_id in self._local_docs:
                            del self._local_docs[doc_id]
                            return {"ok": True}
                        return {"error": "not_found", "reason": "missing"}

            elif parts[0] == "_all_docs":
                # List all documents
                if method == "GET":
                    rows = []
                    for doc_id, doc in self._docs.items():
                        rows.append({
                            "id": doc_id,
                            "key": doc_id,
                            "value": {"rev": doc.get("_rev", "1-")}
                        })
                    return {"total_rows": len(rows), "offset": 0, "rows": rows}

            elif parts[0] == "_find":
                # Mango-like query
                if method == "POST" and payload:
                    selector = payload.get("selector", {})
                    limit = payload.get("limit", None)

                    logger.info(f"MemoryBackend _find: selector={selector}, docs_count={len(self._docs)}")
                    docs = []
                    for doc in self._docs.values():
                        if self._matches_selector(doc, selector):
                            docs.append(doc.copy())
                            if limit and len(docs) >= limit:
                                break
                    logger.info(f"MemoryBackend _find: found {len(docs)} docs")
                    return {"docs": docs, "bookmark": "memory_bookmark"}

            elif parts[0] == "_bulk_docs":
                # Bulk document operations
                if method == "POST" and payload and "docs" in payload:
                    results = []
                    for doc in payload["docs"]:
                        doc_id = self._get_doc_id(doc)
                        doc["_rev"] = self._get_rev(doc)
                        self._docs[doc_id] = doc.copy()
                        self._add_change(doc_id, doc)
                        results.append({"ok": True, "id": doc_id, "rev": doc["_rev"]})
                    return results

            elif parts[0] == "_changes":
                # Change feed
                if method == "GET":
                    return {
                        "last_seq": self._seq,
                        "results": self._changes.copy(),
                        "pending": 0
                    }
                elif method == "POST" and payload:
                    # Handle _changes POST with filter options
                    return {
                        "last_seq": self._seq,
                        "results": self._changes.copy(),
                        "pending": 0
                    }

            elif parts[0] == "_revs_diff":
                # Revision differences
                if method == "POST" and payload:
                    # For memory backend, assume all docs are missing
                    missing = {}
                    for doc_id in payload.keys():
                        if doc_id in self._docs:
                            rev = self._docs[doc_id].get("_rev", "1-")
                            missing[doc_id] = {"missing": [rev]}
                        else:
                            missing[doc_id] = {"missing": []}
                    return missing

            elif parts[0] == "_bulk_get":
                # Bulk document retrieval
                if method == "POST" and payload and "docs" in payload:
                    results = []
                    for doc_spec in payload["docs"]:
                        doc_id = doc_spec.get("id")
                        if doc_id and doc_id in self._docs:
                            results.append({"ok": self._docs[doc_id].copy()})
                        elif doc_id:
                            results.append({"missing": doc_id})
                    return {"results": results}

            elif parts[0].startswith('_'):
                # Special underscore endpoints that we don't implement
                return {"error": "not_implemented", "reason": f"Endpoint {path} with method {method} not implemented in memory backend"}
            else:
                # Regular document operations
                if len(parts) == 1:
                    doc_id = parts[0]

                    if method == "GET":
                        if doc_id in self._docs:
                            return self._docs[doc_id]
                        return {"error": "not_found", "reason": "deleted"}

                    elif method == "PUT":
                        if not payload:
                            return {"error": "bad_request", "reason": "missing body"}

                        doc = payload.copy()
                        doc["_id"] = doc_id
                        doc["_rev"] = self._get_rev(doc)
                        self._docs[doc_id] = doc
                        self._add_change(doc_id, doc)
                        logger.info(f"MemoryBackend PUT: stored doc {doc_id}, total docs: {len(self._docs)}")
                        return {"ok": True, "id": doc_id, "_rev": doc["_rev"]}

                    elif method == "DELETE":
                        if doc_id in self._docs:
                            self._add_change(doc_id, self._docs[doc_id], deleted=True)
                            del self._docs[doc_id]
                            return {"ok": True}
                        return {"error": "not_found", "reason": "missing"}

    def _matches_selector(self, doc: Dict, selector: Dict) -> bool:
        """Check if a document matches a Mango selector."""
        if not selector:
            return True

        for key, condition in selector.items():
            # Handle top-level logical operators
            if key == "$or":
                if not isinstance(condition, list):
                    return False
                # Match if ANY of the conditions in the list match
                match_any = False
                for sub_selector in condition:
                    if self._matches_selector(doc, sub_selector):
                        match_any = True
                        break
                if not match_any:
                    return False
                continue
            
            elif key == "$and":
                if not isinstance(condition, list):
                    return False
                # Match if ALL of the conditions in the list match
                for sub_selector in condition:
                    if not self._matches_selector(doc, sub_selector):
                        return False
                continue

            # Handle field matching
            if key not in doc:
                return False

            doc_value = doc[key]

            if isinstance(condition, dict):
                # Handle Mango operators like $eq, $gt, etc.
                for op, value in condition.items():
                    if op == "$eq" and doc_value != value:
                        return False
                    elif op == "$gt" and not (doc_value > value):
                        return False
                    elif op == "$gte" and not (doc_value >= value):
                        return False
                    elif op == "$lt" and not (doc_value < value):
                        return False
                    elif op == "$lte" and not (doc_value <= value):
                        return False
                    elif op == "$ne" and doc_value == value:
                        return False
                    elif op == "$in" and doc_value not in value:
                        return False
            elif doc_value != condition:
                return False

        return True


class CouchBackend(BaseBackend):
    """Real CouchDB HTTP backend."""

    def __init__(self, base_url: str, username: Optional[str] = None, password: Optional[str] = None):
        self.base_url = base_url.rstrip('/')
        self.auth = (username, password) if username and password else None
        # Use AsyncClient for async operations
        self._client = httpx.AsyncClient(auth=self.auth, timeout=30.0)

    async def handle_request(self, path: str, method: str, payload: Optional[Dict] = None, params: Optional[Dict] = None) -> Any:
        """Forward requests to real CouchDB."""
        url = f"{self.base_url}/{path.lstrip('/')}"

        try:
            if method.upper() == "GET":
                response = await self._client.get(url, params=params)
            elif method.upper() == "POST":
                response = await self._client.post(url, json=payload, params=params)
            elif method.upper() == "PUT":
                response = await self._client.put(url, json=payload, params=params)
            elif method.upper() == "DELETE":
                response = await self._client.delete(url, params=params)
            else:
                return {"error": "bad_request", "reason": f"Unsupported method: {method}"}

            response.raise_for_status()

            # Return JSON response or empty dict for 204/empty responses
            try:
                return response.json() if response.content else {}
            except json.JSONDecodeError:
                return {"ok": True} if response.status_code < 400 else {"error": "response_not_json"}

        except httpx.HTTPStatusError as e:
            try:
                return e.response.json()
            except (json.JSONDecodeError, AttributeError):
                return {"error": "http_error", "reason": str(e)}
        except Exception as e:
            return {"error": "connection_error", "reason": str(e)}

    async def close(self):
        """Close the async client."""
        await self._client.aclose()


class CouchDAL:
    """Main Data Access Layer with automatic backend selection."""

    def __init__(self, backend: Optional[str] = None, **kwargs):
        """
        Initialize the DAL with specified or auto-detected backend.

        Args:
            backend: 'couch', 'memory', or None for auto-detection
            **kwargs: Backend-specific configuration (CouchDB URL, credentials, etc.)
        """
        if backend is None:
            backend = "memory" if _is_test_env() else "couch"

        self.backend = self._get_backend(backend, **kwargs)

    def _get_backend(self, backend: str, **kwargs) -> BaseBackend:
        """Create and return the appropriate backend instance."""
        if backend == "memory":
            return MemoryBackend()
        elif backend == "couch":
            base_url = kwargs.get("base_url", "http://localhost:5984")
            username = kwargs.get("username")
            password = kwargs.get("password")
            return CouchBackend(base_url, username, password)
        else:
            raise ValueError(f"Unknown backend: {backend}")

    async def get(self, path: str, method: str, payload: Optional[Dict] = None, params: Optional[Dict] = None) -> Any:
        """
        Execute a CouchDB request.

        Args:
            path: CouchDB endpoint path (e.g., "/_find", "/mydoc")
            method: HTTP method ("GET", "POST", "PUT", "DELETE")
            payload: Optional request payload for POST/PUT requests
            params: Optional query parameters

        Returns:
            Response data from the backend
        """
        return await self.backend.handle_request(path, method, payload, params)

    async def close(self):
        """Close backend resources if needed."""
        if hasattr(self.backend, 'close'):
            await self.backend.close()


# Convenience factory function
def create_dal(backend: Optional[str] = None, **kwargs) -> CouchDAL:
    """Create a CouchDAL instance with optional backend specification."""
    return CouchDAL(backend, **kwargs)