"""Integration tests for user-management API endpoints."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.dependencies import get_db
from app.routers.users import router as users_router


def _client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(users_router, prefix="/api")
    app.dependency_overrides[get_db] = override_db
    return TestClient(app), engine


def test_change_username():
    client, engine = _client()
    headers = {"X-API-Key": "test_admin_pw"}
    try:
        created = client.post(
            "/api/users", json={"username": "alice"}, headers=headers
        ).json()

        response = client.patch(
            f"/api/users/{created['id']}",
            json={"username": "alicia"},
            headers=headers,
        )

        assert response.status_code == 200
        assert response.json()["username"] == "alicia"
    finally:
        engine.dispose()


def test_change_username_rejects_duplicate():
    client, engine = _client()
    headers = {"X-API-Key": "test_admin_pw"}
    try:
        alice = client.post(
            "/api/users", json={"username": "alice"}, headers=headers
        ).json()
        client.post("/api/users", json={"username": "bob"}, headers=headers)

        response = client.patch(
            f"/api/users/{alice['id']}",
            json={"username": "bob"},
            headers=headers,
        )

        assert response.status_code == 409
        assert response.json()["detail"] == "Username 'bob' exists"
    finally:
        engine.dispose()


def test_change_username_rejects_blank_name():
    client, engine = _client()
    headers = {"X-API-Key": "test_admin_pw"}
    try:
        created = client.post(
            "/api/users", json={"username": "alice"}, headers=headers
        ).json()

        response = client.patch(
            f"/api/users/{created['id']}",
            json={"username": "   "},
            headers=headers,
        )

        assert response.status_code == 422
    finally:
        engine.dispose()
