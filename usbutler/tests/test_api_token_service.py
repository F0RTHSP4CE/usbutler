"""Tests for API token generation and hashing."""

from app.services.api_token_service import TOKEN_PREFIX, generate_token, hash_token


class TestGenerateToken:
    def test_has_prefix(self):
        token = generate_token()
        assert token.startswith(TOKEN_PREFIX)

    def test_length(self):
        token = generate_token()
        # 4 prefix chars + 64 hex chars
        assert len(token) == 68

    def test_unique(self):
        tokens = {generate_token() for _ in range(50)}
        assert len(tokens) == 50

    def test_hex_suffix(self):
        token = generate_token()
        suffix = token[len(TOKEN_PREFIX) :]
        int(suffix, 16)  # raises if not valid hex


class TestHashToken:
    def test_deterministic(self):
        token = generate_token()
        assert hash_token(token) == hash_token(token)

    def test_sha256_length(self):
        assert len(hash_token("anything")) == 64

    def test_different_inputs_different_hashes(self):
        assert hash_token("token_a") != hash_token("token_b")
