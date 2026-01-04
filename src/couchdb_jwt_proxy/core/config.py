"""
Shared configuration for both FastAPI and stdlib servers.
"""
import os
import logging
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Centralized configuration loaded from environment variables."""

    # CouchDB
    COUCHDB_INTERNAL_URL = os.getenv("COUCHDB_INTERNAL_URL", "http://localhost:5984")
    COUCHDB_USER = os.getenv("COUCHDB_USER", "admin")
    COUCHDB_PASSWORD = os.getenv("COUCHDB_PASSWORD", "admin")

    # Proxy server
    PROXY_HOST = os.getenv("PROXY_HOST", "127.0.0.1")
    PROXY_PORT = int(os.getenv("PROXY_PORT", "5985"))

    # Logging
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

    # JWT
    SKIP_JWT_EXPIRATION_CHECK = os.getenv("SKIP_JWT_EXPIRATION_CHECK", "false").lower() == "true"

    # CORS
    @classmethod
    def get_allowed_origins(cls) -> list:
        """Get CORS allowed origins from env, including 127.0.0.1 variants."""
        cors_env = os.getenv("CORS_ORIGINS", "http://localhost:5000,http://localhost:4000")
        origins = [origin.strip() for origin in cors_env.split(",")]
        # Also allow 127.0.0.1 variants
        origins += [origin.replace("localhost", "127.0.0.1") for origin in origins if "localhost" in origin]
        return origins


def setup_logging():
    """Configure logging based on LOG_LEVEL."""
    logging.basicConfig(
        level=getattr(logging, Config.LOG_LEVEL.upper(), logging.INFO),
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    return logging.getLogger(__name__)
