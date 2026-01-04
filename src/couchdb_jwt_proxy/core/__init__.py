# Core shared modules for both FastAPI and stdlib servers
from .config import Config, setup_logging
from .auth import verify_jwt, decode_token_unsafe, get_jwks_client, extract_bearer_token
from .couch import couch_get, couch_put, couch_post, couch_delete, get_basic_auth_header, proxy_request
from .app_loader import load_applications
from .virtual_tables import (
    hash_user_id,
    handle_create_tenant,
    handle_list_tenants,
    handle_get_tenant,
    handle_update_tenant,
    handle_delete_tenant,
    handle_get_user,
    handle_update_user,
    handle_delete_user,
)

__all__ = [
    # Config
    "Config",
    "setup_logging",
    # Auth
    "verify_jwt",
    "decode_token_unsafe",
    "get_jwks_client",
    "extract_bearer_token",
    # CouchDB
    "couch_get",
    "couch_put",
    "couch_post",
    "couch_delete",
    "get_basic_auth_header",
    "proxy_request",
    # App loader
    "load_applications",
    # Virtual tables
    "hash_user_id",
    "handle_create_tenant",
    "handle_list_tenants",
    "handle_get_tenant",
    "handle_update_tenant",
    "handle_delete_tenant",
    "handle_get_user",
    "handle_update_user",
    "handle_delete_user",
]
