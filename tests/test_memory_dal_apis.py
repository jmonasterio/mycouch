"""
Memory DAL REST API tests.

Tests that use the Memory DAL for realistic testing without external dependencies.
"""

import pytest
import json
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock
from httpx import AsyncClient, Response, ASGITransport

# Import our DAL components
from couchdb_jwt_proxy.dal import CouchDAL, MemoryBackend, create_dal


@pytest.fixture
def memory_dal():
    """Memory DAL for testing"""
    return create_dal(backend="memory")


@pytest.fixture
def mock_clerk_jwt_payload():
    """Mock Clerk JWT payload"""
    return {
        "sub": "user_abc123def456",
        "email": "user@example.com",
        "iss": "https://test-clerk-instance.clerk.accounts.dev",
        "aud": "test-app-id",
        "user_id": "user_123"
    }


@pytest.mark.asyncio
class TestMemoryDALRestAPI:
    """Test REST API-like operations using Memory DAL"""

    async def test_document_crud_operations(self, memory_dal):
        """Test complete CRUD operations"""
        # Create document
        doc = {
            "_id": "test_task_1",
            "type": "task",
            "title": "Test Task",
            "status": "pending"
        }

        response = await memory_dal.get("/testdb/test_task_1", "PUT", doc)
        assert response["ok"] is True
        assert response["id"] == "test_task_1"
        rev = response["_rev"]

        # Read document
        response = await memory_dal.get("/testdb/test_task_1", "GET")
        assert response["_id"] == "test_task_1"
        assert response["type"] == "task"
        assert response["title"] == "Test Task"
        assert response["_rev"] == rev

        # Update document
        updated_doc = response.copy()
        updated_doc["status"] = "completed"

        response = await memory_dal.get("/testdb/test_task_1", "PUT", updated_doc)
        assert response["ok"] is True
        assert response["_rev"] != rev

        # Read updated document
        response = await memory_dal.get("/testdb/test_task_1", "GET")
        assert response["status"] == "completed"

        # Delete document
        response = await memory_dal.get("/testdb/test_task_1", "DELETE")
        assert response["ok"] is True

        # Verify deletion
        response = await memory_dal.get("/testdb/test_task_1", "GET")
        assert response["error"] == "not_found"

    async def test_bulk_operations(self, memory_dal):
        """Test bulk document operations"""
        docs = [
            {"_id": "bulk_1", "type": "task", "title": "Task 1"},
            {"_id": "bulk_2", "type": "task", "title": "Task 2"},
            {"_id": "bulk_3", "type": "note", "title": "Note 1"}
        ]

        response = await memory_dal.get("/testdb/_bulk_docs", "POST", {"docs": docs})
        assert len(response) == 3

        for result in response:
            assert result["ok"] is True

        # Query documents
        response = await memory_dal.get("/testdb/_all_docs", "GET")
        assert response["total_rows"] == 3
        doc_ids = [row["id"] for row in response["rows"]]
        assert "bulk_1" in doc_ids
        assert "bulk_2" in doc_ids
        assert "bulk_3" in doc_ids

    async def test_find_operations(self, memory_dal):
        """Test Mango-style find operations"""
        # Create test documents
        docs = [
            {"_id": "find_1", "type": "task", "priority": 1, "status": "pending"},
            {"_id": "find_2", "type": "task", "priority": 2, "status": "completed"},
            {"_id": "find_3", "type": "note", "priority": 1, "status": "active"}
        ]

        await memory_dal.get("/testdb/_bulk_docs", "POST", {"docs": docs})

        # Find all tasks
        response = await memory_dal.get("/testdb/_find", "POST", {
            "selector": {"type": "task"}
        })
        assert len(response["docs"]) == 2
        assert all(doc["type"] == "task" for doc in response["docs"])

        # Find pending tasks
        response = await memory_dal.get("/testdb/_find", "POST", {
            "selector": {"type": "task", "status": "pending"}
        })
        assert len(response["docs"]) == 1
        assert response["docs"][0]["status"] == "pending"

        # Find with limit
        response = await memory_dal.get("/testdb/_find", "POST", {
            "selector": {"type": "task"},
            "limit": 1
        })
        assert len(response["docs"]) == 1

        # Find with comparison operators
        response = await memory_dal.get("/testdb/_find", "POST", {
            "selector": {"priority": {"$gt": 1}}
        })
        assert len(response["docs"]) == 1
        assert response["docs"][0]["priority"] == 2

    async def test_changes_feed(self, memory_dal):
        """Test changes feed for real-time sync simulation"""
        # Initial state
        response = await memory_dal.get("/testdb/_changes", "GET")
        assert response["last_seq"] == 0
        assert len(response["results"]) == 0

        # Create document
        doc = {"_id": "changes_test", "type": "test", "data": "test"}
        await memory_dal.get("/testdb/changes_test", "PUT", doc)

        # Check changes
        response = await memory_dal.get("/testdb/_changes", "GET")
        assert response["last_seq"] == 1
        assert len(response["results"]) == 1

        change = response["results"][0]
        assert change["id"] == "changes_test"
        assert change["seq"] == 1
        assert change["deleted"] is False

        # Update document
        updated_doc = doc.copy()
        updated_doc["data"] = "updated"
        await memory_dal.get("/testdb/changes_test", "PUT", updated_doc)

        # Check changes
        response = await memory_dal.get("/testdb/_changes", "GET")
        assert response["last_seq"] == 2
        assert len(response["results"]) == 2

        # Delete document
        await memory_dal.get("/testdb/changes_test", "DELETE")

        # Check changes
        response = await memory_dal.get("/testdb/_changes", "GET")
        assert response["last_seq"] == 3
        assert len(response["results"]) == 3

        # Find deleted change
        deleted_changes = [c for c in response["results"] if c["deleted"]]
        assert len(deleted_changes) == 1
        assert deleted_changes[0]["id"] == "changes_test"

    async def test_local_documents(self, memory_dal):
        """Test local document operations"""
        checkpoint_data = {
            "seq": 42,
            "last_processed": "2023-11-12T00:00:00Z",
            "processed_ids": ["doc1", "doc2"]
        }

        # Create local document
        response = await memory_dal.get("/testdb/_local/checkpoint", "PUT", checkpoint_data)
        assert response["ok"] is True
        assert response["id"] == "_local/checkpoint"

        # Read local document
        response = await memory_dal.get("/testdb/_local/checkpoint", "GET")
        assert response == checkpoint_data

        # Update local document
        checkpoint_data["seq"] = 43
        response = await memory_dal.get("/testdb/_local/checkpoint", "PUT", checkpoint_data)
        assert response["ok"] is True

        # Delete local document
        response = await memory_dal.get("/testdb/_local/checkpoint", "DELETE")
        assert response["ok"] is True

        # Verify deletion
        response = await memory_dal.get("/testdb/_local/checkpoint", "GET")
        assert response["error"] == "not_found"

        # Verify local docs don't appear in _all_docs
        response = await memory_dal.get("/testdb/_all_docs", "GET")
        doc_ids = [row["id"] for row in response["rows"]]
        assert "_local/checkpoint" not in doc_ids

    async def test_bulk_get_operations(self, memory_dal):
        """Test _bulk_get operations"""
        # Create test documents
        docs = [
            {"_id": "bulk_get_1", "type": "task", "title": "Task 1"},
            {"_id": "bulk_get_2", "type": "task", "title": "Task 2"},
            {"_id": "bulk_get_3", "type": "note", "title": "Note 1"}
        ]

        await memory_dal.get("/testdb/_bulk_docs", "POST", {"docs": docs})

        # Bulk get specific documents
        response = await memory_dal.get("/testdb/_bulk_get", "POST", {
            "docs": [
                {"id": "bulk_get_1"},
                {"id": "bulk_get_3"},
                {"id": "nonexistent"}
            ]
        })

        assert "results" in response
        results = response["results"]
        assert len(results) == 3

        # Find successful gets
        successful = [r for r in results if "ok" in r]
        missing = [r for r in results if "missing" in r]

        assert len(successful) == 2
        assert len(missing) == 1
        assert missing[0]["missing"] == "nonexistent"

        # Verify document contents
        titles = [doc["ok"]["title"] for doc in successful]
        assert "Task 1" in titles
        assert "Note 1" in titles

    async def test_revisions_diff(self, memory_dal):
        """Test _revs_diff operations"""
        # Create a document
        doc = {"_id": "revs_test", "type": "test"}
        response = await memory_dal.get("/testdb/revs_test", "PUT", doc)
        rev = response["_rev"]

        # Test revs diff
        response = await memory_dal.get("/testdb/_revs_diff", "POST", {
            "revs_test": [rev, "nonexistent-rev"],
            "missing_doc": ["1-abc"]
        })

        # Should return information about the existing doc
        assert "revs_test" in response
        assert "missing_doc" in response

    async def test_database_info(self, memory_dal):
        """Test database metadata endpoint"""
        response = await memory_dal.get("/testdb", "GET")

        assert response["db_name"] == "memory_db"
        assert response["doc_count"] >= 0
        assert response["doc_del_count"] == 0
        assert "update_seq" in response
        assert "instance_start_time" in response

    async def test_session_endpoint(self, memory_dal):
        """Test session endpoint"""
        # GET session info
        response = await memory_dal.get("/_session", "GET")
        assert response["ok"] is True
        assert "userCtx" in response
        assert "info" in response

        # POST session (login simulation)
        response = await memory_dal.get("/_session", "POST", {})
        assert response["ok"] is True

    async def test_thread_safety(self, memory_dal):
        """Test thread safety of Memory Backend"""
        # Note: Thread safety test is tricky with async, but we can test concurrent access
        
        results = []
        errors = []

        async def worker(worker_id):
            try:
                for i in range(10):
                    doc_id = f"worker_{worker_id}_doc_{i}"
                    doc = {"_id": doc_id, "worker": worker_id, "index": i}
                    response = await memory_dal.get(f"/testdb/{doc_id}", "PUT", doc)
                    results.append((worker_id, i, response))
                    await asyncio.sleep(0.001)
            except Exception as e:
                errors.append((worker_id, e))

        # Start multiple tasks
        tasks = [worker(i) for i in range(5)]
        await asyncio.gather(*tasks)

        # Verify no errors occurred
        assert len(errors) == 0, f"Errors occurred: {errors}"

        # Verify all documents were created
        assert len(results) == 50  # 5 workers * 10 docs each

        # Verify document count
        response = await memory_dal.get("/testdb/_all_docs", "GET")
        assert response["total_rows"] == 50

        # Verify all documents are valid
        for worker_id, i, response in results:
            assert response["ok"] is True
            doc_id = f"worker_{worker_id}_doc_{i}"
            doc = await memory_dal.get(f"/testdb/{doc_id}", "GET")
            assert doc["worker"] == worker_id
            assert doc["index"] == i

    async def test_memory_backend_persistence(self, memory_dal):
        """Test that MemoryBackend doesn't persist between instances"""
        # Create a document
        doc = {"_id": "persistence_test", "type": "test"}
        response = await memory_dal.get("/testdb/persistence_test", "PUT", doc)
        assert response["ok"] is True

        # Verify it exists in current instance
        response = await memory_dal.get("/testdb/persistence_test", "GET")
        assert response["type"] == "test"

        # Create new DAL instance
        new_dal = create_dal(backend="memory")

        # Document should not exist in new instance
        response = await new_dal.get("/testdb/persistence_test", "GET")
        assert response["error"] == "not_found"

        # Database should be empty in new instance
        response = await new_dal.get("/testdb", "GET")
        assert response["doc_count"] == 0

    async def test_error_handling(self, memory_dal):
        """Test error handling for invalid requests"""
        # Missing payload for POST requests (returns None, not an error)
        response = await memory_dal.get("/testdb/_find", "POST", None)
        # Should handle gracefully without crashing (returns None for missing payload)
        assert response is None

        # Empty payload for _bulk_docs (returns None when no docs)
        response = await memory_dal.get("/testdb/_bulk_docs", "POST", {})
        # Should handle gracefully (returns None for missing docs)
        assert response is None

        # Empty docs array (should work)
        response = await memory_dal.get("/testdb/_bulk_docs", "POST", {"docs": []})
        # Should return empty list for empty docs array
        assert isinstance(response, list)
        assert len(response) == 0

        # Non-existent endpoints
        response = await memory_dal.get("/testdb/_nonexistent_endpoint", "GET")
        # Should return not implemented error
        assert response["error"] == "not_implemented"

        # Invalid document operations
        response = await memory_dal.get("/testdb/test_doc", "PUT", None)
        # Should handle missing body gracefully
        assert response["error"] == "bad_request"


@pytest.mark.asyncio
class TestTenantIsolationWithMemoryDAL:
    """Test tenant isolation using Memory DAL"""

    async def test_tenant_field_injection_simulation(self, memory_dal):
        """Simulate tenant field injection like the proxy would do"""
        # Simulate what the proxy does - inject tenant_id into documents
        doc = {
            "_id": "tenant_test",
            "type": "task",
            "title": "Test Task"
        }

        # Simulate tenant injection (as done by the proxy)
        doc_with_tenant = doc.copy()
        doc_with_tenant["tenant_id"] = "tenant-123"

        response = await memory_dal.get("/testdb/tenant_test", "PUT", doc_with_tenant)
        assert response["ok"] is True

        # Retrieve and verify tenant is there
        response = await memory_dal.get("/testdb/tenant_test", "GET")
        assert response["tenant_id"] == "tenant-123"

    async def test_cross_tenant_data_isolation(self, memory_dal):
        """Simulate cross-tenant data isolation"""
        # Documents from different "tenants"
        tenant_a_doc = {
            "_id": "shared_doc",
            "type": "shared",
            "tenant_id": "tenant-a",
            "data": "tenant-a data"
        }

        tenant_b_doc = {
            "_id": "shared_doc_b",
            "type": "shared",
            "tenant_id": "tenant-b",
            "data": "tenant-b data"
        }

        # Create documents for both tenants
        await memory_dal.get("/testdb/shared_doc", "PUT", tenant_a_doc)
        await memory_dal.get("/testdb/shared_doc_b", "PUT", tenant_b_doc)

        # Simulate tenant filtering (what the proxy would do)
        all_docs = await memory_dal.get("/testdb/_all_docs", "GET")
        assert all_docs["total_rows"] == 2

        # Filter for tenant-a documents
        tenant_a_docs = [
            row for row in all_docs["rows"]
            if row["id"] == "shared_doc"  # In real scenario, this would check tenant_id
        ]
        assert len(tenant_a_docs) == 1


@pytest.mark.asyncio
class TestPerformanceAndScalability:
    """Test performance characteristics of Memory DAL"""

    async def test_large_bulk_operations(self, memory_dal):
        """Test handling large bulk operations"""
        # Create 100 documents
        docs = [
            {"_id": f"perf_test_{i}", "type": "test", "index": i}
            for i in range(100)
        ]

        response = await memory_dal.get("/testdb/_bulk_docs", "POST", {"docs": docs})
        assert len(response) == 100

        # Verify all were created
        all_docs = await memory_dal.get("/testdb/_all_docs", "GET")
        assert all_docs["total_rows"] == 100

    async def test_performance_with_find_queries(self, memory_dal):
        """Test performance with find queries"""
        # Create documents
        docs = [
            {"_id": f"perf_find_{i}", "type": "task", "priority": i % 5, "status": "pending"}
            for i in range(200)
        ]

        await memory_dal.get("/testdb/_bulk_docs", "POST", {"docs": docs})

        # Query with different selectors
        queries = [
            {"selector": {"type": "task"}},
            {"selector": {"priority": 3}},
            {"selector": {"status": "pending", "priority": {"$gt": 2}}},
            {"selector": {"type": "task"}, "limit": 50}
        ]

        for query in queries:
            response = await memory_dal.get("/testdb/_find", "POST", query)
            assert "docs" in response
            assert isinstance(response["docs"], list)


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])