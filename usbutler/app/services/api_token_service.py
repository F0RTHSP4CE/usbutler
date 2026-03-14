"""API token generation and hashing."""

import hashlib
import secrets

TOKEN_PREFIX = "ubt_"


def generate_token() -> str:
    """Generate a new API token. Format: ubt_<64 hex chars>."""
    return TOKEN_PREFIX + secrets.token_hex(32)


def hash_token(raw_token: str) -> str:
    """Hash a raw token with SHA-256 for storage."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
