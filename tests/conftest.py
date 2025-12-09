"""
Pytest configuration for couchdb-jwt-proxy tests.

This file ensures that the src directory is in the Python path
so that tests can import from couchdb_jwt_proxy, and enables memory DAL
for all tests.
"""
import sys
import os
from pathlib import Path

# Force memory DAL backend for all tests
os.environ["DAL_BACKEND"] = "memory"

# Add src directory to Python path
src_path = Path(__file__).parent.parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))
