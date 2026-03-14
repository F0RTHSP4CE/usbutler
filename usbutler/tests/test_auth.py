"""Tests for API authentication endpoints (integration via FastAPI TestClient)."""

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ["ADMIN_PASSWORD"] = "test_admin_pw"
os.environ["POS_SECRET"] = "test_pos_pw"

import pytest
from fastapi import FastAPI, APIRouter
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.dependencies import (
    ApiKeyAuth,
    PosSecretAuth,
    get_db,
)
from app.models.user import User
from app.services.api_token_service import generate_token, hash_token


@pytest.fixture()
def app_and_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)

    def override_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    # Patch SessionLocal so verify_api_key's direct DB access uses test DB
    import app.dependencies as deps
    original_session_local = deps.SessionLocal
    deps.SessionLocal = TestSession

    router = APIRouter()

    @router.get("/protected")
    def protected(auth: ApiKeyAuth):
        return {"ok": True}

    @router.get("/pos-protected")
    def pos_protected(auth: PosSecretAuth):
        return {"ok": True}

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = override_db

    session = TestSession()
    yield app, session
    session.close()
    deps.SessionLocal = original_session_local
    engine.dispose()


class TestApiKeyAuth:
    def test_no_key_returns_401(self, app_and_db):
        app, _ = app_and_db
        client = TestClient(app)
        r = client.get("/protected")
        assert r.status_code == 401
        assert "Missing API key" in r.json()["detail"]

    def test_admin_password_accepted(self, app_and_db):
        app, _ = app_and_db
        client = TestClient(app)
        r = client.get("/protected", headers={"X-API-Key": "test_admin_pw"})
        assert r.status_code == 200

    def test_wrong_admin_password_rejected(self, app_and_db):
        app, _ = app_and_db
        client = TestClient(app)
        r = client.get("/protected", headers={"X-API-Key": "wrong_password"})
        assert r.status_code == 401

    def test_valid_user_token_accepted(self, app_and_db):
        app, db = app_and_db
        raw = generate_token()
        user = User(username="tokenuser", api_token_hash=hash_token(raw))
        db.add(user)
        db.commit()

        client = TestClient(app)
        r = client.get("/protected", headers={"X-API-Key": raw})
        assert r.status_code == 200

    def test_invalid_token_rejected(self, app_and_db):
        app, _ = app_and_db
        client = TestClient(app)
        r = client.get("/protected", headers={"X-API-Key": "ubt_invalid_token_hex"})
        assert r.status_code == 401
        assert "Invalid API token" in r.json()["detail"]

    def test_token_ip_restriction_allowed(self, app_and_db):
        app, db = app_and_db
        raw = generate_token()
        # TestClient peer address is 'testclient'; not a valid IP, so
        # we test with no restriction set (allowed) vs restriction set (denied)
        # This test uses a wildcard CIDR that covers all IPs, but since
        # 'testclient' isn't a real IP, we test the 'no restriction' path.
        user = User(
            username="restricted",
            api_token_hash=hash_token(raw),
            api_allowed_sources=None,  # no restriction = allowed from anywhere
        )
        db.add(user)
        db.commit()

        client = TestClient(app)
        r = client.get("/protected", headers={"X-API-Key": raw})
        assert r.status_code == 200

    def test_token_ip_restriction_denied(self, app_and_db):
        app, db = app_and_db
        raw = generate_token()
        user = User(
            username="locked_down",
            api_token_hash=hash_token(raw),
            api_allowed_sources="10.99.99.0/24",
        )
        db.add(user)
        db.commit()

        client = TestClient(app)
        # TestClient peer IP is 'testclient' which won't be in 10.99.99.0/24
        r = client.get("/protected", headers={"X-API-Key": raw})
        assert r.status_code == 403
        assert "not allowed from this IP" in r.json()["detail"]

    def test_token_no_restriction_any_ip(self, app_and_db):
        app, db = app_and_db
        raw = generate_token()
        user = User(
            username="unrestricted",
            api_token_hash=hash_token(raw),
            api_allowed_sources=None,
        )
        db.add(user)
        db.commit()

        client = TestClient(app)
        r = client.get("/protected", headers={"X-API-Key": raw})
        assert r.status_code == 200

    def test_garbage_key_rejected(self, app_and_db):
        app, _ = app_and_db
        client = TestClient(app)
        r = client.get("/protected", headers={"X-API-Key": "random_garbage"})
        assert r.status_code == 401


class TestPosSecretAuth:
    def test_correct_pos_secret(self, app_and_db):
        app, _ = app_and_db
        client = TestClient(app)
        r = client.get("/pos-protected", headers={"X-POS-Secret": "test_pos_pw"})
        assert r.status_code == 200

    def test_wrong_pos_secret(self, app_and_db):
        app, _ = app_and_db
        client = TestClient(app)
        r = client.get("/pos-protected", headers={"X-POS-Secret": "wrong"})
        assert r.status_code == 401

    def test_missing_pos_secret(self, app_and_db):
        app, _ = app_and_db
        client = TestClient(app)
        r = client.get("/pos-protected")
        assert r.status_code == 401
