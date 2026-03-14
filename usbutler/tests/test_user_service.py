"""Tests for UserService with token and allowed_sources fields."""

from app.models.user import User, UserStatus
from app.schemas.user import UserCreate, UserUpdate
from app.services.api_token_service import generate_token, hash_token
from app.services.user_service import UserService


class TestUserServiceTokens:
    def test_create_user_no_token(self, db):
        svc = UserService(db)
        user = svc.create(UserCreate(username="alice"))
        assert user.api_token_hash is None
        assert user.api_allowed_sources is None

    def test_create_user_with_sources(self, db):
        svc = UserService(db)
        user = svc.create(UserCreate(username="bob"), "10.0.0.0/8,172.16.0.0/12")
        assert user.api_allowed_sources == "10.0.0.0/8,172.16.0.0/12"

    def test_set_token_hash(self, db):
        svc = UserService(db)
        user = svc.create(UserCreate(username="carol"))
        raw = generate_token()
        h = hash_token(raw)
        svc.set_token_hash(user.id, h)
        reloaded = svc.get_by_id(user.id)
        assert reloaded.api_token_hash == h

    def test_set_token_hash_nonexistent(self, db):
        svc = UserService(db)
        assert svc.set_token_hash(999, "deadbeef") is None

    def test_token_lookup(self, db):
        svc = UserService(db)
        user = svc.create(UserCreate(username="dave"))
        raw = generate_token()
        h = hash_token(raw)
        svc.set_token_hash(user.id, h)
        found = db.query(User).filter(User.api_token_hash == h).first()
        assert found.id == user.id

    def test_update_allowed_sources(self, db):
        svc = UserService(db)
        user = svc.create(UserCreate(username="eve"), "10.0.0.0/8")
        svc.update(user.id, UserUpdate(allowed_sources=["172.16.0.0/12"]), "172.16.0.0/12")
        reloaded = svc.get_by_id(user.id)
        assert reloaded.api_allowed_sources == "172.16.0.0/12"

    def test_update_clears_sources_with_empty(self, db):
        svc = UserService(db)
        user = svc.create(UserCreate(username="frank"), "10.0.0.0/8")
        svc.update(user.id, UserUpdate(allowed_sources=[]), None)
        reloaded = svc.get_by_id(user.id)
        assert reloaded.api_allowed_sources is None

    def test_update_preserves_sources_when_not_set(self, db):
        svc = UserService(db)
        user = svc.create(UserCreate(username="grace"), "10.0.0.0/8")
        svc.update(user.id, UserUpdate(username="grace2"))
        reloaded = svc.get_by_id(user.id)
        assert reloaded.api_allowed_sources == "10.0.0.0/8"
        assert reloaded.username == "grace2"

    def test_regenerate_token_replaces_old(self, db):
        svc = UserService(db)
        user = svc.create(UserCreate(username="heidi"))
        t1 = generate_token()
        svc.set_token_hash(user.id, hash_token(t1))
        t2 = generate_token()
        svc.set_token_hash(user.id, hash_token(t2))
        reloaded = svc.get_by_id(user.id)
        assert reloaded.api_token_hash == hash_token(t2)
        assert reloaded.api_token_hash != hash_token(t1)

    def test_delete_user_removes_token(self, db):
        svc = UserService(db)
        user = svc.create(UserCreate(username="ivan"))
        svc.set_token_hash(user.id, hash_token(generate_token()))
        svc.delete(user.id)
        assert db.query(User).filter(User.id == user.id).first() is None
