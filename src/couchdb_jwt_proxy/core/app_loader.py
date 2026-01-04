"""
Application configuration loader - loads app configs from couch-sitter database.
"""
import logging
from typing import Dict, Any

from .config import Config
from .couch import couch_post

logger = logging.getLogger(__name__)


def load_applications() -> Dict[str, Dict[str, Any]]:
    """
    Load application configurations from couch-sitter database.

    Returns:
        Dict mapping issuer URL to application config:
        {
            "https://clerk.example.com": {
                "databaseNames": ["roady"],
                "clerkSecretKey": "sk_..."
            }
        }
    """
    applications: Dict[str, Dict[str, Any]] = {}

    try:
        # Query for application documents
        query = {
            "selector": {"type": "application"},
            "limit": 100
        }

        status, result = couch_post("/couch-sitter/_find", query)

        if status != 200:
            logger.warning(f"Failed to query applications: {status} {result}")
            return applications

        for doc in result.get("docs", []):
            # Support both "issuer" and "clerkIssuerId" field names
            issuer = doc.get("issuer") or doc.get("clerkIssuerId")
            if issuer:
                # Support both "databaseNames" (array) and "databaseName" (string)
                db_names = doc.get("databaseNames", [])
                if not db_names and doc.get("databaseName"):
                    db_names = [doc.get("databaseName")]

                applications[issuer] = {
                    "databaseNames": db_names,
                    "clerkSecretKey": doc.get("clerkSecretKey")
                }
                logger.info(f"Loaded application: {issuer} -> {db_names}")

        logger.info(f"Loaded {len(applications)} applications from couch-sitter")

    except Exception as e:
        logger.warning(f"Could not load applications from couch-sitter: {e}")
        logger.warning("JWT issuer validation may be limited")

    return applications
