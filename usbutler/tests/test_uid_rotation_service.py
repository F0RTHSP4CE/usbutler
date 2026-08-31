"""Tests for per-user UID lineage state and throttling."""

from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.identifier import (
    Identifier,
    IdentifierState,
    IdentifierType,
    UidReservation,
    UidRotationAttempt,
)
from app.models.user import User
from app.database import Base
from app.schemas.identifier import IdentifierCreate
from app.schemas.user import UserCreate, UserUpdate
from app.services.auth_service import AuthService
from app.services.identifier_service import IdentifierService
from app.services.uid_rotation_service import UidCollisionError, UidRotationService
from app.services.uid_rotation_service import LineageMutationError
from app.services.user_service import UserService
from app.config import settings
from app.utils.time import utcnow


def _sequence_rng(monkeypatch, values: list[str]) -> None:
    iterator = iter(values)
    monkeypatch.setattr(
        "app.services.uid_rotation_service.secrets.token_bytes",
        lambda _: bytes.fromhex(next(iterator)),
    )


def _create_uid(db, user: User, value: str = "01020304") -> Identifier:
    return IdentifierService(db).create(
        IdentifierCreate(value=value, type=IdentifierType.UID, user_id=user.id)
    )


def test_new_user_defaults_to_rotation_enabled(db):
    user = UserService(db).create(UserCreate(username="new-user"))
    assert user.uid_rotation_enabled is True
    assert user.uid_rotation_every_read is False


def test_every_read_policy_can_be_enabled_per_user(db):
    users = UserService(db)
    user = users.create(UserCreate(username="new-user"))

    users.update(user.id, UserUpdate(uid_rotation_every_read=True))

    assert users.get_by_id(user.id).uid_rotation_every_read is True


def test_disabled_user_uid_remains_static(db):
    user = UserService(db).create(
        UserCreate(username="legacy", uid_rotation_enabled=False)
    )
    identifier = _create_uid(db, user)
    assert identifier.state == IdentifierState.STATIC
    assert identifier.chain_root_id is None
    assert identifier.reservation_id is not None


def test_global_kill_switch_defers_then_reconciles_candidates(db, monkeypatch):
    _sequence_rng(monkeypatch, ["11111111"])
    monkeypatch.setattr(settings, "UID_ROTATION_ENABLED", False)
    user = UserService(db).create(UserCreate(username="paused"))
    identifier = _create_uid(db, user)
    assert identifier.state == IdentifierState.STATIC

    monkeypatch.setattr(settings, "UID_ROTATION_ENABLED", True)
    UidRotationService(db).initialize_enabled_users()
    db.refresh(identifier)
    assert identifier.chain_root_id == identifier.id
    assert db.scalar(
        select(Identifier.id).where(
            Identifier.chain_root_id == identifier.id,
            Identifier.state == IdentifierState.PENDING,
        )
    )


def test_enabling_user_initializes_independent_lineages(db, monkeypatch):
    _sequence_rng(monkeypatch, ["11111111", "22222222"])
    users = UserService(db)
    user = users.create(UserCreate(username="legacy", uid_rotation_enabled=False))
    first = _create_uid(db, user, "01020304")
    second = _create_uid(db, user, "05060708")

    users.update(user.id, UserUpdate(uid_rotation_enabled=True))

    nodes = list(
        db.scalars(
            select(Identifier)
            .where(Identifier.user_id == user.id)
            .order_by(Identifier.id)
        ).all()
    )
    assert len(nodes) == 4
    assert first.chain_root_id == first.id
    assert second.chain_root_id == second.id
    assert {node.value for node in nodes if node.state == IdentifierState.PENDING} == {
        "11111111",
        "22222222",
    }


def test_daily_retry_creates_fresh_pending_branch(db, monkeypatch):
    _sequence_rng(monkeypatch, ["11111111", "22222222"])
    user = UserService(db).create(UserCreate(username="alice"))
    current = _create_uid(db, user)
    rotation = UidRotationService(db)

    first = rotation.prepare_write(current.id)
    assert first is not None
    assert first.target_uid == "11111111"
    assert rotation.prepare_write(current.id) is None

    root = db.get(Identifier, current.id)
    root.last_write_attempt_at = utcnow() - timedelta(hours=25)
    db.commit()
    second = rotation.prepare_write(current.id)
    assert second is not None
    assert second.target_uid == "22222222"

    pending = list(
        db.scalars(
            select(Identifier).where(
                Identifier.chain_root_id == current.id,
                Identifier.state == IdentifierState.PENDING,
            )
        ).all()
    )
    assert {item.value for item in pending} == {"11111111", "22222222"}


def test_every_read_policy_bypasses_daily_slot(db, monkeypatch):
    _sequence_rng(monkeypatch, ["11111111", "22222222"])
    user = UserService(db).create(
        UserCreate(username="alice", uid_rotation_every_read=True)
    )
    current = _create_uid(db, user)
    rotation = UidRotationService(db)

    first = rotation.prepare_write(current.id, minimum_interval=None)
    second = rotation.prepare_write(current.id, minimum_interval=None)

    assert first is not None
    assert second is not None
    assert first.target_uid == "11111111"
    assert second.target_uid == "22222222"
    assert db.scalar(
        select(UidRotationAttempt).where(UidRotationAttempt.id == first.attempt_id)
    )
    assert db.scalar(
        select(UidRotationAttempt).where(UidRotationAttempt.id == second.attempt_id)
    )


def test_daily_slot_is_atomic_across_sessions(tmp_path, monkeypatch):
    _sequence_rng(monkeypatch, ["11111111"])
    engine = create_engine(
        f"sqlite:///{tmp_path / 'concurrent.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as setup:
        user = UserService(setup).create(UserCreate(username="alice"))
        root = IdentifierService(setup).create(
            IdentifierCreate(value="01020304", type=IdentifierType.UID, user_id=user.id)
        )
        root_id = root.id

    def claim_slot():
        with Session() as session:
            return UidRotationService(session).prepare_write(root_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: claim_slot(), range(2)))

    assert sum(result is not None for result in results) == 1
    engine.dispose()


def test_observed_candidate_selects_branch_and_retires_old_uid(db, monkeypatch):
    _sequence_rng(monkeypatch, ["11111111", "22222222", "33333333"])
    user = UserService(db).create(UserCreate(username="alice"))
    current = _create_uid(db, user)
    rotation = UidRotationService(db)
    first = rotation.prepare_write(current.id)
    root = db.get(Identifier, current.id)
    root.last_write_attempt_at = utcnow() - timedelta(hours=25)
    db.commit()
    rotation.prepare_write(current.id)

    promoted = rotation.promote_pending(first.target_identifier_id, True)
    assert promoted.state == IdentifierState.CURRENT
    assert db.get(Identifier, current.id).state == IdentifierState.RETIRED

    values = list(
        db.scalars(
            select(Identifier.value).where(Identifier.chain_root_id == current.id)
        ).all()
    )
    assert set(values) == {"01020304", "11111111", "33333333"}
    assert "22222222" not in values
    assert db.scalar(
        select(UidReservation.id).where(UidReservation.value == "22222222")
    )
    confirmed_attempt = db.scalar(
        select(UidRotationAttempt).where(
            UidRotationAttempt.target_reservation_id == promoted.reservation_id
        )
    )
    assert confirmed_attempt.confirmed_at is not None


def test_pending_confirms_while_disabled_without_successor(db, monkeypatch):
    _sequence_rng(monkeypatch, ["11111111"])
    users = UserService(db)
    user = users.create(UserCreate(username="alice"))
    current = _create_uid(db, user)
    pending = db.scalar(
        select(Identifier).where(
            Identifier.chain_root_id == current.id,
            Identifier.state == IdentifierState.PENDING,
        )
    )
    users.update(user.id, UserUpdate(uid_rotation_enabled=False))

    promoted = UidRotationService(db).promote_pending(pending.id, False)
    assert promoted.state == IdentifierState.CURRENT
    assert (
        db.scalar(
            select(Identifier.id).where(
                Identifier.chain_root_id == current.id,
                Identifier.state == IdentifierState.PENDING,
            )
        )
        is None
    )


def test_retired_uid_is_rejected(db, monkeypatch):
    _sequence_rng(monkeypatch, ["11111111", "22222222"])
    user_service = UserService(db)
    identifier_service = IdentifierService(db)
    user = user_service.create(UserCreate(username="alice"))
    current = _create_uid(db, user)
    pending = db.scalar(
        select(Identifier).where(Identifier.state == IdentifierState.PENDING)
    )
    UidRotationService(db).promote_pending(pending.id, True)

    success, _, _, message = AuthService(user_service, identifier_service).authenticate(
        current.value
    )
    assert success is False
    assert message == "Retired identifier"


def test_reserved_uid_cannot_be_reenrolled_after_lineage_deletion(db, monkeypatch):
    _sequence_rng(monkeypatch, ["11111111"])
    user = UserService(db).create(UserCreate(username="alice"))
    current = _create_uid(db, user)
    IdentifierService(db).delete_lineage(current.id)

    with pytest.raises(UidCollisionError):
        _create_uid(db, user, "01020304")


def test_lineage_assignment_moves_every_node(db, monkeypatch):
    _sequence_rng(monkeypatch, ["11111111"])
    users = UserService(db)
    source_user = users.create(UserCreate(username="source"))
    destination = users.create(
        UserCreate(username="destination", uid_rotation_enabled=False)
    )
    root = _create_uid(db, source_user)

    IdentifierService(db).assign_lineage(root.id, destination.id)

    owners = set(
        db.scalars(
            select(Identifier.user_id).where(Identifier.chain_root_id == root.id)
        ).all()
    )
    assert owners == {destination.id}


def test_individual_lineage_assignment_is_rejected(db, monkeypatch):
    _sequence_rng(monkeypatch, ["11111111"])
    user = UserService(db).create(UserCreate(username="source"))
    root = _create_uid(db, user)

    with pytest.raises(LineageMutationError):
        IdentifierService(db).assign_to_user(root.id, None)


def test_deleting_user_with_lineage_preserves_uid_reservations(db, monkeypatch):
    _sequence_rng(monkeypatch, ["11111111"])
    users = UserService(db)
    user = users.create(UserCreate(username="alice"))
    _create_uid(db, user)

    assert users.delete(user.id) is True
    assert db.get(User, user.id) is None
    assert set(db.scalars(select(UidReservation.value)).all()) == {
        "01020304",
        "11111111",
    }
