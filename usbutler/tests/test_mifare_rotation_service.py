"""State-machine and authentication tests for MIFARE data UUIDs."""

from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.identifier import IdentifierType, MifareUuidState, MifareUuidValue
from app.models.user import UserStatus
from app.schemas.identifier import IdentifierCreate
from app.schemas.user import UserCreate, UserUpdate
from app.services.auth_service import AuthService, CardAuthAnomaly
from app.services.card_reader import CardScanResult
from app.services.identifier_service import IdentifierService
from app.services.mifare_rotation_service import MifareRotationService
from app.services.user_service import UserService


def create_fob(db, username="alice", enabled=True, uid="01020304"):
    users = UserService(db)
    identifiers = IdentifierService(db)
    user = users.create(UserCreate(username=username, mifare_rotation_enabled=enabled))
    identifier = identifiers.create(
        IdentifierCreate(value=uid, type=IdentifierType.UID, user_id=user.id)
    )
    return users, identifiers, user, identifier


def mifare_scan(uid="01020304", data_uuid=None):
    return CardScanResult(
        uid=uid,
        atr="3B8F8001804F0CA000000306030001",
        mifare_classic=True,
        mifare_uuid=data_uuid,
        identifiers={"identifier": {"type": "UID", "value": uid}},
    )


def test_pending_target_is_persisted_and_reused(db):
    _, _, _, identifier = create_fob(db)
    first = MifareRotationService(db).prepare_write(identifier.id)
    second = MifareRotationService(db).prepare_write(identifier.id)

    assert first is not None
    assert second == first
    values = db.query(MifareUuidValue).all()
    assert [(value.value, value.state) for value in values] == [
        (first.target_uuid, MifareUuidState.PENDING)
    ]


def test_only_observed_pending_uuid_starts_cooldown(db):
    _, _, _, identifier = create_fob(db)
    rotation = MifareRotationService(db)
    prepared = rotation.prepare_write(identifier.id)

    assert prepared is not None
    assert rotation.confirm_observed(identifier.id, prepared.target_uuid, 3) is True
    assert rotation.prepare_write(identifier.id) is None

    credential = identifier.mifare_credential
    assert credential.last_verified_rotation_at is not None
    assert credential.uuid_values[0].state == MifareUuidState.CONFIRMED


def test_retains_three_confirmed_values_plus_one_pending(db):
    _, _, _, identifier = create_fob(db)
    rotation = MifareRotationService(db)
    confirmed = []
    for _ in range(4):
        prepared = rotation.prepare_write(identifier.id, minimum_interval=timedelta(0))
        assert prepared is not None
        confirmed.append(prepared.target_uuid)
        assert rotation.confirm_observed(identifier.id, prepared.target_uuid, 3)

    pending = rotation.prepare_write(identifier.id, minimum_interval=timedelta(0))
    assert pending is not None
    values = db.query(MifareUuidValue).all()
    confirmed_values = {
        value.value for value in values if value.state == MifareUuidState.CONFIRMED
    }
    pending_values = [
        value.value for value in values if value.state == MifareUuidState.PENDING
    ]

    assert confirmed_values == set(confirmed[-3:])
    assert pending_values == [pending.target_uuid]


def test_multiple_fobs_have_independent_state(db):
    users = UserService(db)
    identifiers = IdentifierService(db)
    user = users.create(UserCreate(username="alice", mifare_rotation_enabled=True))
    first = identifiers.create(
        IdentifierCreate(value="01020304", type=IdentifierType.UID, user_id=user.id)
    )
    second = identifiers.create(
        IdentifierCreate(value="05060708", type=IdentifierType.UID, user_id=user.id)
    )
    rotation = MifareRotationService(db)

    first_write = rotation.prepare_write(first.id)
    second_write = rotation.prepare_write(second.id)

    assert first_write.credential_id != second_write.credential_id
    assert first_write.target_uuid != second_write.target_uuid


def test_legacy_uid_authenticates_until_first_confirmation(db):
    users, identifiers, user, identifier = create_fob(db)
    auth = AuthService(users, identifiers)

    assert auth.authenticate_card(mifare_scan())[:2] == (True, user)

    prepared = MifareRotationService(db).prepare_write(identifier.id)
    # A pending value is accepted in case a write succeeded before persistence
    # could record verification.
    pending_result = auth.authenticate_card(
        mifare_scan(uid="DEADBEEF", data_uuid=prepared.target_uuid)
    )
    assert pending_result[0] is True
    assert pending_result[2].id == identifier.id
    assert pending_result.anomalies == (CardAuthAnomaly.UID_UUID_MISMATCH,)

    MifareRotationService(db).confirm_observed(identifier.id, prepared.target_uuid, 3)
    strict_result = auth.authenticate_card(mifare_scan(data_uuid=None))
    assert strict_result[0] is False
    assert "requires a recognized data UUID" in strict_result[3]
    assert strict_result.anomalies == (CardAuthAnomaly.ENROLLED_UUID_REJECTED,)


def test_known_uuid_wins_over_hardware_uid(db):
    users, identifiers, _, identifier = create_fob(db)
    rotation = MifareRotationService(db)
    prepared = rotation.prepare_write(identifier.id)
    rotation.confirm_observed(identifier.id, prepared.target_uuid, 3)

    result = AuthService(users, identifiers).authenticate_card(
        mifare_scan(uid="DEADBEEF", data_uuid=prepared.target_uuid)
    )

    assert result[0] is True
    assert result[2].id == identifier.id
    assert result.anomalies == (CardAuthAnomaly.UID_UUID_MISMATCH,)


def test_previous_confirmed_uuid_remains_accepted(db):
    users, identifiers, _, identifier = create_fob(db)
    rotation = MifareRotationService(db)
    first = rotation.prepare_write(identifier.id)
    rotation.confirm_observed(identifier.id, first.target_uuid, 3)
    second = rotation.prepare_write(identifier.id, minimum_interval=timedelta(0))
    rotation.confirm_observed(identifier.id, second.target_uuid, 3)

    result = AuthService(users, identifiers).authenticate_card(
        mifare_scan(data_uuid=first.target_uuid)
    )

    assert result[0] is True
    assert result[2].id == identifier.id


def test_unknown_uuid_cannot_bypass_strict_enrollment_with_uid(db):
    users, identifiers, _, identifier = create_fob(db)
    rotation = MifareRotationService(db)
    prepared = rotation.prepare_write(identifier.id)
    rotation.confirm_observed(identifier.id, prepared.target_uuid, 3)

    result = AuthService(users, identifiers).authenticate_card(
        mifare_scan(data_uuid="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    )

    assert result[0] is False
    assert "requires a recognized data UUID" in result[3]


def test_disabling_rotation_keeps_uuid_auth_and_does_not_restore_uid(db):
    users, identifiers, user, identifier = create_fob(db)
    rotation = MifareRotationService(db)
    prepared = rotation.prepare_write(identifier.id)
    rotation.confirm_observed(identifier.id, prepared.target_uuid, 3)

    users.update(user.id, UserUpdate(mifare_rotation_enabled=False))
    auth = AuthService(users, identifiers)
    assert auth.authenticate_card(mifare_scan(data_uuid=prepared.target_uuid))[0]
    assert not auth.authenticate_card(mifare_scan(data_uuid=None))[0]


def test_inactive_user_is_rejected_for_known_uuid(db):
    users, identifiers, user, identifier = create_fob(db)
    rotation = MifareRotationService(db)
    prepared = rotation.prepare_write(identifier.id)
    rotation.confirm_observed(identifier.id, prepared.target_uuid, 3)

    users.update(user.id, UserUpdate(status=UserStatus.INACTIVE))
    result = AuthService(users, identifiers).authenticate_card(
        mifare_scan(data_uuid=prepared.target_uuid)
    )
    assert result[0] is False
    assert result[3] == "User is inactive"
    assert result.anomalies == (CardAuthAnomaly.DISABLED_USER,)


def test_unknown_card_is_classified_for_notification(db):
    users = UserService(db)
    identifiers = IdentifierService(db)

    result = AuthService(users, identifiers).authenticate_card(
        mifare_scan(uid="DEADBEEF")
    )

    assert result.success is False
    assert result.anomalies == (CardAuthAnomaly.UNKNOWN_CARD,)


def test_known_uuid_reports_different_registered_uid_owner(db):
    users, identifiers, alice, identifier = create_fob(db)
    bob = users.create(UserCreate(username="bob"))
    bob_identifier = identifiers.create(
        IdentifierCreate(value="DEADBEEF", type=IdentifierType.UID, user_id=bob.id)
    )
    rotation = MifareRotationService(db)
    prepared = rotation.prepare_write(identifier.id)
    rotation.confirm_observed(identifier.id, prepared.target_uuid, 3)

    result = AuthService(users, identifiers).authenticate_card(
        mifare_scan(uid=bob_identifier.value, data_uuid=prepared.target_uuid)
    )

    assert result.success is True
    assert result.user.id == alice.id
    assert result.uid_identifier.id == bob_identifier.id
    assert result.uuid_identifier.id == identifier.id
    assert result.anomalies == (CardAuthAnomaly.UID_UUID_MISMATCH,)


def test_non_mifare_pan_authentication_is_unchanged(db):
    users = UserService(db)
    identifiers = IdentifierService(db)
    user = users.create(UserCreate(username="alice"))
    identifiers.create(
        IdentifierCreate(
            value="4111111111111111", type=IdentifierType.PAN, user_id=user.id
        )
    )
    scan = CardScanResult(
        pan="4111111111111111",
        identifiers={"identifier": {"type": "PAN", "value": "4111111111111111"}},
    )
    assert AuthService(users, identifiers).authenticate_card(scan)[0] is True


def test_reassignment_moves_uuid_authentication_to_new_user(db):
    users, identifiers, _, identifier = create_fob(db)
    rotation = MifareRotationService(db)
    prepared = rotation.prepare_write(identifier.id)
    rotation.confirm_observed(identifier.id, prepared.target_uuid, 3)
    bob = users.create(UserCreate(username="bob"))
    identifiers.assign_to_user(identifier.id, bob.id)

    result = AuthService(users, identifiers).authenticate_card(
        mifare_scan(data_uuid=prepared.target_uuid)
    )

    assert result[0] is True
    assert result[1].id == bob.id


def test_deleting_identifier_cascades_mifare_state(db):
    _, identifiers, _, identifier = create_fob(db)
    MifareRotationService(db).prepare_write(identifier.id)

    assert identifiers.delete(identifier.id) is True
    assert db.query(MifareUuidValue).count() == 0


def test_database_enforces_one_pending_uuid_per_credential(db):
    _, _, _, identifier = create_fob(db)
    prepared = MifareRotationService(db).prepare_write(identifier.id)
    db.add(
        MifareUuidValue(
            credential_id=prepared.credential_id,
            value="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            state=MifareUuidState.PENDING,
        )
    )

    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    assert db.query(MifareUuidValue).count() == 1
