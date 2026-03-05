"""
Tenant isolation tests.

Two layers of protection:

1. Unit tests — verify each filter function strips foreign-tenant documents.
   Fast, no HTTP stack required.

2. Invariant test — every endpoint in ALLOWED_ENDPOINTS must be explicitly
   accounted for in one of three buckets. If a new endpoint is added and this
   test fails, isolation has been forgotten.
"""

import json
import os

import pytest

os.environ.setdefault("SESSION_SECRET", "test-session-secret-that-is-long-enough-here")
os.environ.setdefault("APPLICATION_ID", "roady,roady-staging")

from couchdb_jwt_proxy.main import (
    TENANT_FIELD,
    filter_response_documents,
    filter_changes_response,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

TENANT_A = "tenant_aaaa-1111"
TENANT_B = "tenant_bbbb-2222"

DOC_A = {"_id": "doc-alpha", "_rev": "1-aaa", TENANT_FIELD: TENANT_A, "name": "Alpha"}
DOC_B = {"_id": "doc-bravo", "_rev": "1-bbb", TENANT_FIELD: TENANT_B, "name": "Bravo"}


# ---------------------------------------------------------------------------
# filter_response_documents  (_all_docs / _find)
# ---------------------------------------------------------------------------

class TestFilterResponseDocuments:
    def _all_docs_body(self, *docs):
        return json.dumps({
            "total_rows": len(docs),
            "rows": [
                {"id": d["_id"], "key": d["_id"],
                 "value": {"rev": d["_rev"]}, "doc": d}
                for d in docs
            ],
        }).encode()

    def _find_body(self, *docs):
        return json.dumps({"docs": list(docs)}).encode()

    def test_all_docs_keeps_own_tenant(self):
        out = json.loads(filter_response_documents(self._all_docs_body(DOC_A), TENANT_A))
        assert len(out["rows"]) == 1
        assert out["rows"][0]["id"] == DOC_A["_id"]

    def test_all_docs_strips_foreign_tenant(self):
        out = json.loads(filter_response_documents(self._all_docs_body(DOC_A, DOC_B), TENANT_A))
        ids = [r["id"] for r in out["rows"]]
        assert DOC_A["_id"] in ids
        assert DOC_B["_id"] not in ids

    def test_all_docs_empty_when_no_matching_docs(self):
        out = json.loads(filter_response_documents(self._all_docs_body(DOC_B), TENANT_A))
        assert out["rows"] == []
        assert out["total_rows"] == 0

    def test_find_keeps_own_tenant(self):
        out = json.loads(filter_response_documents(self._find_body(DOC_A, DOC_B), TENANT_A))
        assert len(out["docs"]) == 1
        assert out["docs"][0]["_id"] == DOC_A["_id"]

    def test_find_strips_foreign_tenant(self):
        out = json.loads(filter_response_documents(self._find_body(DOC_A, DOC_B), TENANT_A))
        ids = [d["_id"] for d in out["docs"]]
        assert DOC_B["_id"] not in ids


# ---------------------------------------------------------------------------
# _bulk_get filter  (inline logic in proxy_couchdb)
# ---------------------------------------------------------------------------

def _apply_bulk_get_filter(results: list, tenant_id: str) -> list:
    """Mirror of the filter logic added to proxy_couchdb for _bulk_get."""
    filtered = []
    for row in results:
        filtered_docs = []
        for doc_entry in row.get("docs", []):
            doc = doc_entry.get("ok") or doc_entry.get("error") or {}
            doc_tenant = doc.get(TENANT_FIELD)
            if (row.get("id", "").startswith("_local/")
                    or doc_tenant is None
                    or doc_tenant == tenant_id):
                filtered_docs.append(doc_entry)
        if filtered_docs:
            filtered.append({**row, "docs": filtered_docs})
    return filtered


class TestBulkGetFilter:
    def test_keeps_own_tenant_doc(self):
        results = [{"id": DOC_A["_id"], "docs": [{"ok": DOC_A}]}]
        out = _apply_bulk_get_filter(results, TENANT_A)
        assert len(out) == 1
        assert out[0]["id"] == DOC_A["_id"]

    def test_strips_foreign_tenant_doc(self):
        results = [
            {"id": DOC_A["_id"], "docs": [{"ok": DOC_A}]},
            {"id": DOC_B["_id"], "docs": [{"ok": DOC_B}]},
        ]
        out = _apply_bulk_get_filter(results, TENANT_A)
        ids = [r["id"] for r in out]
        assert DOC_A["_id"] in ids
        assert DOC_B["_id"] not in ids

    def test_local_docs_always_pass(self):
        """_local/* replication checkpoints must never be filtered."""
        local = {"_id": "_local/checkpoint-xyz", "_rev": "0-1"}
        results = [{"id": "_local/checkpoint-xyz", "docs": [{"ok": local}]}]
        out = _apply_bulk_get_filter(results, TENANT_A)
        assert len(out) == 1

    def test_docs_without_tenant_field_pass(self):
        """Documents with no tenant_id are not filtered (design docs, etc.)."""
        design_doc = {"_id": "_design/views", "_rev": "1-abc"}
        results = [{"id": "_design/views", "docs": [{"ok": design_doc}]}]
        out = _apply_bulk_get_filter(results, TENANT_A)
        assert len(out) == 1

    def test_row_omitted_when_all_docs_filtered(self):
        """If all docs in a row are foreign, the row itself is dropped."""
        results = [{"id": DOC_B["_id"], "docs": [{"ok": DOC_B}]}]
        out = _apply_bulk_get_filter(results, TENANT_A)
        assert out == []


# ---------------------------------------------------------------------------
# filter_changes_response  (_changes non-streaming / fallback)
# ---------------------------------------------------------------------------

class TestFilterChangesResponse:
    def _changes_body(self, *docs):
        return json.dumps({
            "last_seq": "5",
            "results": [
                {"seq": str(i + 1), "id": d["_id"],
                 "changes": [{"rev": d["_rev"]}], "doc": d}
                for i, d in enumerate(docs)
            ],
        }).encode()

    def test_keeps_own_tenant(self):
        out = json.loads(filter_changes_response(self._changes_body(DOC_A), TENANT_A))
        assert len(out["results"]) == 1

    def test_strips_foreign_tenant(self):
        out = json.loads(filter_changes_response(self._changes_body(DOC_A, DOC_B), TENANT_A))
        ids = [r["id"] for r in out["results"]]
        assert DOC_A["_id"] in ids
        assert DOC_B["_id"] not in ids


# ---------------------------------------------------------------------------
# Architectural invariant
# ---------------------------------------------------------------------------

def test_all_allowed_endpoints_have_filter_coverage():
    """
    Every endpoint in ALLOWED_ENDPOINTS must be in exactly one bucket below.
    Adding a new endpoint without updating this test is a deliberate act —
    the failure forces a decision about isolation strategy.

    Buckets:
      filtered_server_side  tenant selector injected into CouchDB request URL
      filtered_response     response post-filtered by tenant before returning
      no_doc_content        endpoint never returns full document bodies
    """
    from couchdb_jwt_proxy.main import ALLOWED_ENDPOINTS

    filtered_server_side = {
        "/_changes",        # selector={"tenant_id":...} injected into _changes URL
    }
    filtered_response = {
        "/_all_docs",       # filter_response_documents() in proxy_couchdb
        "/_find",           # filter_response_documents() in proxy_couchdb
        "/_bulk_get",       # inline filter loop in proxy_couchdb
    }
    no_doc_content = {
        "/_revs_diff",      # returns {doc_id: [missing_revs]} — no doc bodies
        "/_bulk_docs",      # write endpoint; reads are in _bulk_get
        "/_session",        # CouchDB session cookie management
        "/_local/",         # replication checkpoints — no business data
        "/_all_dbs",        # list of DB names, not documents
    }

    accounted_for = filtered_server_side | filtered_response | no_doc_content
    unaccounted = set(ALLOWED_ENDPOINTS.keys()) - accounted_for

    assert not unaccounted, (
        f"These endpoints have no tenant isolation strategy: {unaccounted}\n"
        "Add each to the correct bucket in test_tenant_isolation.py "
        "after confirming the isolation mechanism."
    )
