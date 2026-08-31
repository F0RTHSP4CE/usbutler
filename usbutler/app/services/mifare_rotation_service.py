"""Persistent state machine for rotating MIFARE data-block UUIDs."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.models.identifier import (
    Identifier,
    IdentifierType,
    MifareCredential,
    MifareUuidState,
    MifareUuidValue,
)
from app.utils.time import utcnow


@dataclass(frozen=True)
class PreparedMifareWrite:
    credential_id: int
    identifier_id: int
    target_uuid: str


def canonical_uuid4(value: str) -> Optional[str]:
    """Return canonical UUIDv4 text, or None for any other 16-byte value."""
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return None
    if parsed.version != 4 or parsed.variant != uuid.RFC_4122:
        return None
    return str(parsed)


class MifareRotationService:
    """Owns UUID lookup, pending writes, verification, and retention."""

    def __init__(self, db: Session):
        self.db = db

    def get_uuid_record(self, value: str) -> Optional[MifareUuidValue]:
        canonical = canonical_uuid4(value)
        if canonical is None:
            return None
        stmt = (
            select(MifareUuidValue)
            .options(
                joinedload(MifareUuidValue.credential)
                .joinedload(MifareCredential.identifier)
                .joinedload(Identifier.user)
            )
            .where(func.lower(MifareUuidValue.value) == canonical.lower())
        )
        return self.db.scalar(stmt)

    def has_confirmed_uuid(self, identifier_id: int) -> bool:
        stmt = (
            select(MifareUuidValue.id)
            .join(MifareCredential)
            .where(
                MifareCredential.identifier_id == identifier_id,
                MifareUuidValue.state == MifareUuidState.CONFIRMED,
            )
            .limit(1)
        )
        return self.db.scalar(stmt) is not None

    def prepare_write(
        self,
        identifier_id: int,
        minimum_interval: timedelta = timedelta(hours=24),
    ) -> Optional[PreparedMifareWrite]:
        """Return the existing pending target or create one after cooldown."""
        identifier = self.db.get(Identifier, identifier_id)
        if not identifier or identifier.type != IdentifierType.UID:
            return None

        credential = self._ensure_credential(identifier)
        pending = self._pending(credential.id)
        if pending:
            return self._prepared(credential, pending)

        now = utcnow()
        if (
            credential.last_verified_rotation_at is not None
            and credential.last_verified_rotation_at > now - minimum_interval
        ):
            return None

        # Both the UUID uniqueness constraint and the partial pending index are
        # authoritative. If another worker wins either race, reload its target.
        for _ in range(256):
            target = MifareUuidValue(
                credential_id=credential.id,
                value=str(uuid.uuid4()),
                state=MifareUuidState.PENDING,
                created_at=now,
            )
            self.db.add(target)
            try:
                self.db.commit()
                return self._prepared(credential, target)
            except IntegrityError:
                self.db.rollback()
                reloaded = self._credential_for_identifier(identifier_id)
                credential = reloaded or self._ensure_credential(identifier)
                pending = self._pending(credential.id)
                if pending:
                    return self._prepared(credential, pending)
        raise RuntimeError("Unable to allocate a unique MIFARE UUID")

    def confirm_observed(
        self, identifier_id: int, value: str, history_limit: int
    ) -> bool:
        """Confirm a pending value only after it is actually read from the card."""
        canonical = canonical_uuid4(value)
        if canonical is None:
            return False
        stmt = (
            select(MifareUuidValue)
            .join(MifareCredential)
            .where(
                MifareCredential.identifier_id == identifier_id,
                func.lower(MifareUuidValue.value) == canonical.lower(),
            )
        )
        observed = self.db.scalar(stmt)
        if not observed or observed.state != MifareUuidState.PENDING:
            return False

        now = utcnow()
        observed.state = MifareUuidState.CONFIRMED
        observed.confirmed_at = now
        credential = observed.credential
        credential.last_verified_rotation_at = now
        credential.last_write_error = None
        self.db.flush()
        self._prune_credential(credential.id, history_limit)
        self.db.commit()
        return True

    def record_attempt(self, credential_id: int, error: Optional[str]) -> None:
        credential = self.db.get(MifareCredential, credential_id)
        if not credential:
            return
        credential.last_write_attempt_at = utcnow()
        credential.last_write_error = error[:500] if error else None
        self.db.commit()

    def reconcile(self, history_limit: int) -> None:
        """Apply a lowered retention limit without changing credential state."""
        credential_ids = self.db.scalars(select(MifareCredential.id)).all()
        for credential_id in credential_ids:
            self._prune_credential(credential_id, history_limit)
        self.db.commit()

    def _ensure_credential(self, identifier: Identifier) -> MifareCredential:
        credential = self._credential_for_identifier(identifier.id)
        if credential:
            return credential
        credential = MifareCredential(identifier_id=identifier.id)
        self.db.add(credential)
        try:
            self.db.flush()
            return credential
        except IntegrityError:
            self.db.rollback()
            existing = self._credential_for_identifier(identifier.id)
            if existing is None:
                raise
            return existing

    def _credential_for_identifier(
        self, identifier_id: int
    ) -> Optional[MifareCredential]:
        return self.db.scalar(
            select(MifareCredential).where(
                MifareCredential.identifier_id == identifier_id
            )
        )

    def _pending(self, credential_id: int) -> Optional[MifareUuidValue]:
        return self.db.scalar(
            select(MifareUuidValue).where(
                MifareUuidValue.credential_id == credential_id,
                MifareUuidValue.state == MifareUuidState.PENDING,
            )
        )

    @staticmethod
    def _prepared(
        credential: MifareCredential, pending: MifareUuidValue
    ) -> PreparedMifareWrite:
        return PreparedMifareWrite(
            credential_id=credential.id,
            identifier_id=credential.identifier_id,
            target_uuid=pending.value,
        )

    def _prune_credential(self, credential_id: int, history_limit: int) -> None:
        if history_limit < 1:
            raise ValueError("MIFARE UUID history limit must be at least 1")
        confirmed = list(
            self.db.scalars(
                select(MifareUuidValue)
                .where(
                    MifareUuidValue.credential_id == credential_id,
                    MifareUuidValue.state == MifareUuidState.CONFIRMED,
                )
                .order_by(
                    MifareUuidValue.confirmed_at.desc(),
                    MifareUuidValue.id.desc(),
                )
            ).all()
        )
        for stale in confirmed[history_limit:]:
            self.db.delete(stale)
