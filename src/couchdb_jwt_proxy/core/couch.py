"""
Synchronous CouchDB helpers using urllib (stdlib).
Used by both FastAPI (via executor) and stdlib server directly.
"""
import json
import base64
import logging
from typing import Dict, Any, Tuple, Optional
from urllib.request import Request as UrlRequest, urlopen
from urllib.error import HTTPError, URLError

from .config import Config

logger = logging.getLogger(__name__)


def get_basic_auth_header() -> str:
    """Get basic auth header for CouchDB."""
    if Config.COUCHDB_USER and Config.COUCHDB_PASSWORD:
        credentials = f"{Config.COUCHDB_USER}:{Config.COUCHDB_PASSWORD}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return f"Basic {encoded}"
    return ""


def couch_request(
    path: str,
    method: str = "GET",
    data: Optional[Dict] = None,
    timeout: int = 30
) -> Tuple[int, Dict]:
    """
    Make a request to CouchDB.

    Args:
        path: CouchDB path (e.g., "/couch-sitter/doc_id")
        method: HTTP method
        data: Optional JSON body
        timeout: Request timeout in seconds

    Returns:
        Tuple of (status_code, response_body_dict)
    """
    url = f"{Config.COUCHDB_INTERNAL_URL}{path}"
    headers = {
        "Authorization": get_basic_auth_header(),
        "Content-Type": "application/json",
    }

    body = json.dumps(data).encode() if data else None

    req = UrlRequest(url, data=body, headers=headers, method=method)

    try:
        with urlopen(req, timeout=timeout) as resp:
            response_body = resp.read().decode()
            return resp.status, json.loads(response_body) if response_body else {}
    except HTTPError as e:
        error_body = e.read().decode() if e.fp else "{}"
        try:
            return e.code, json.loads(error_body)
        except json.JSONDecodeError:
            return e.code, {"error": str(e), "reason": error_body}
    except URLError as e:
        logger.error(f"CouchDB connection error: {e}")
        return 502, {"error": "connection_error", "reason": str(e)}
    except Exception as e:
        logger.error(f"CouchDB request error: {e}")
        return 500, {"error": "request_error", "reason": str(e)}


def couch_get(path: str, timeout: int = 30) -> Tuple[int, Dict]:
    """GET from CouchDB."""
    return couch_request(path, "GET", timeout=timeout)


def couch_put(path: str, doc: Dict, timeout: int = 30) -> Tuple[int, Dict]:
    """PUT to CouchDB."""
    return couch_request(path, "PUT", data=doc, timeout=timeout)


def couch_post(path: str, data: Dict, timeout: int = 30) -> Tuple[int, Dict]:
    """POST to CouchDB."""
    return couch_request(path, "POST", data=data, timeout=timeout)


def couch_delete(path: str, rev: Optional[str] = None, timeout: int = 30) -> Tuple[int, Dict]:
    """DELETE from CouchDB."""
    if rev:
        path = f"{path}?rev={rev}"
    return couch_request(path, "DELETE", timeout=timeout)


def proxy_request(
    path: str,
    method: str,
    body: Optional[bytes] = None,
    timeout: int = 30
) -> Tuple[bytes, int, str]:
    """
    Proxy a raw request to CouchDB.

    Args:
        path: Full path including query string
        method: HTTP method
        body: Raw request body
        timeout: Request timeout

    Returns:
        Tuple of (response_body_bytes, status_code, content_type)
    """
    url = f"{Config.COUCHDB_INTERNAL_URL}{path}"
    headers = {
        "Authorization": get_basic_auth_header(),
        "Content-Type": "application/json",
    }

    req = UrlRequest(url, data=body, headers=headers, method=method)

    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.read(), resp.status, resp.headers.get("Content-Type", "application/json")
    except HTTPError as e:
        error_body = e.read() if e.fp else b'{"error": "proxy_error"}'
        return error_body, e.code, "application/json"
    except URLError as e:
        logger.error(f"CouchDB connection error: {e}")
        return json.dumps({"error": "connection_error", "reason": str(e)}).encode(), 502, "application/json"
    except Exception as e:
        logger.error(f"Proxy error: {e}")
        return json.dumps({"error": "proxy_error", "reason": str(e)}).encode(), 500, "application/json"
