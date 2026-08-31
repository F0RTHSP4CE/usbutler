"""Database state machine for rotating MIFARE UID credentials."""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Optional, cast

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.identifier import (
    Identifier,
    IdentifierState,
    IdentifierType,
    UidReservation,
    UidRotationAttempt,
    UidRotationOutcome,
    UidRotationProtocol,
)
from app.models.user import User
from app.utils.time import utcnow

ROTATABLE_UID_RE = re.compile(r"^[0-9A-F]{8}$")


class UidCollisionError(ValueError):
    """Raised when a UID was used or reserved previously."""


class LineageMutationError(ValueError):
    """Raised when an individual operation would corrupt a UID lineage."""


@dataclass(frozen=True)
class PreparedUidWrite:
    attempt_id: int
    chain_root_id: int
    source_identifier_id: int
    target_identifier_id: int
    source_uid: str
    target_uid: str


def normalize_uid(value: str) -> str:
    return value.replace(" ", "").replace(":", "").upper()


def is_rotatable_uid(value: str) -> bool:
    return bool(ROTATABLE_UID_RE.fullmatch(normalize_uid(value)))


class UidRotationService:
    """Owns UID lineage transitions and write-attempt throttling."""

    def __init__(self, db: Session):
        self.db = db

    def is_reserved(self, value: str) -> bool:
        normalized = normalize_uid(value)
        stmt = select(UidReservation.id).where(
            func.lower(UidReservation.value) == normalized.lower()
        )
        return self.db.scalar(stmt) is not None

    def register_identifier(
        self, identifier: Identifier, rotation_enabled: bool
    ) -> None:
        """Reserve a UID and optionally initialize its rotating lineage."""
        if identifier.type != IdentifierType.UID:
            return
        identifier.value = normalize_uid(identifier.value)
        self._ensure_identifier_reservation(identifier)
        if rotation_enabled and is_rotatable_uid(identifier.value):
            self._initialize_lineage(identifier)

    def set_user_rotation(
        self, user: User, enabled: bool, initialize_candidates: bool = True
    ) -> None:
        """Apply a user's policy without committing the surrounding transaction."""
        user.uid_rotation_enabled = enabled
        if not enabled or not initialize_candidates:
            return

        identifiers = list(
            self.db.scalars(
                select(Identifier).where(Identifier.user_id == user.id)
            ).all()
        )
        for identifier in identifiers:
            if identifier.type == IdentifierType.UID:
                self._ensure_identifier_reservation(identifier)
            if (
                identifier.state == IdentifierState.STATIC
                and identifier.type == IdentifierType.UID
                and is_rotatable_uid(identifier.value)
            ):
                self._initialize_lineage(identifier)

        root_ids = {
            identifier.chain_root_id
            for identifier in identifiers
            if identifier.chain_root_id is not None
        }
        for root_id in root_ids:
            current = self._get_current(root_id)
            if current and not self._has_pending(root_id):
                self._create_pending(root_id, current)

    def ensure_policy_for_assignment(
        self,
        identifier: Identifier,
        user: Optional[User],
        initialize_candidates: bool = True,
    ) -> None:
        """Update a whole lineage assignment and initialize rotation if required."""
        if identifier.chain_root_id:
            nodes = self._get_nodes(identifier.chain_root_id)
            for node in nodes:
                node.user_id = user.id if user else None
            if user and user.uid_rotation_enabled and initialize_candidates:
                current = self._get_current(identifier.chain_root_id)
                if current and not self._has_pending(identifier.chain_root_id):
                    self._create_pending(identifier.chain_root_id, current)
            return

        identifier.user_id = user.id if user else None
        if identifier.type == IdentifierType.UID:
            self._ensure_identifier_reservation(identifier)
        if (
            user
            and user.uid_rotation_enabled
            and initialize_candidates
            and identifier.type == IdentifierType.UID
            and is_rotatable_uid(identifier.value)
        ):
            self._initialize_lineage(identifier)

    def initialize_enabled_users(self) -> None:
        """Reconcile users enabled while the global kill switch was disabled."""
        users = list(
            self.db.scalars(
                select(User).where(User.uid_rotation_enabled.is_(True))
            ).all()
        )
        for user in users:
            self.set_user_rotation(user, True, initialize_candidates=True)
        self.db.commit()

    def promote_pending(
        self, identifier_id: int, create_successor: bool
    ) -> Optional[Identifier]:
        """Promote an observed candidate; never called by API/POS lookups."""
        candidate = self.db.get(Identifier, identifier_id)
        if not candidate or candidate.state != IdentifierState.PENDING:
            return candidate
        if not candidate.chain_root_id:
            raise ValueError("Pending identifier has no lineage root")

        now = utcnow()
        current = self._get_current(candidate.chain_root_id)
        if current and current.id != candidate.id:
            current.state = IdentifierState.RETIRED
            self.db.flush()

        candidate.state = IdentifierState.CURRENT
        candidate.confirmed_at = now
        self.db.flush()

        if candidate.reservation_id:
            self.db.execute(
                update(UidRotationAttempt)
                .where(
                    UidRotationAttempt.target_reservation_id
                    == candidate.reservation_id,
                    UidRotationAttempt.confirmed_at.is_(None),
                )
                .values(confirmed_at=now)
            )

        siblings = list(
            self.db.scalars(
                select(Identifier).where(
                    Identifier.chain_root_id == candidate.chain_root_id,
                    Identifier.state == IdentifierState.PENDING,
                    Identifier.id != candidate.id,
                )
            ).all()
        )
        for sibling in siblings:
            self.db.delete(sibling)
        self.db.flush()

        if create_successor:
            self._create_pending(candidate.chain_root_id, candidate)
        self.db.commit()
        self.db.refresh(candidate)
        return candidate

    def prepare_write(
        self,
        source_identifier_id: int,
        minimum_interval: Optional[timedelta] = timedelta(hours=24),
    ) -> Optional[PreparedUidWrite]:
        """Atomically claim a write slot and persist an attempt before I/O.

        A ``None`` interval claims every invocation. The root-row update still
        serializes concurrent scans, while the default retains the rolling
        24-hour policy.
        """
        source = self.db.get(Identifier, source_identifier_id)
        if (
            not source
            or source.state != IdentifierState.CURRENT
            or not source.chain_root_id
        ):
            return None

        now = utcnow()
        claim_filters = [
            Identifier.id == source.chain_root_id,
            Identifier.chain_root_id == source.chain_root_id,
        ]
        if minimum_interval is not None:
            cutoff = now - minimum_interval
            claim_filters.append(
                or_(
                    Identifier.last_write_attempt_at.is_(None),
                    Identifier.last_write_attempt_at <= cutoff,
                )
            )
        claimed = cast(
            CursorResult[Any],
            self.db.execute(
                update(Identifier)
                .where(*claim_filters)
                .values(last_write_attempt_at=now)
            ),
        )
        if claimed.rowcount != 1:
            self.db.rollback()
            return None

        pending = list(
            self.db.scalars(
                select(Identifier)
                .where(
                    Identifier.chain_root_id == source.chain_root_id,
                    Identifier.predecessor_id == source.id,
                    Identifier.state == IdentifierState.PENDING,
                )
                .order_by(Identifier.generated_at, Identifier.id)
            ).all()
        )
        target = next(
            (
                item
                for item in pending
                if item.reservation_id
                and not self.db.scalar(
                    select(UidRotationAttempt.id).where(
                        UidRotationAttempt.target_reservation_id == item.reservation_id
                    )
                )
            ),
            None,
        )
        if target is None:
            target = self._create_pending(source.chain_root_id, source)

        attempt = UidRotationAttempt(
            chain_root_id=source.chain_root_id,
            source_identifier_id=source.id,
            target_reservation_id=target.reservation_id,
            attempted_at=now,
            protocol=UidRotationProtocol.UNKNOWN,
            outcome=UidRotationOutcome.STARTED,
        )
        self.db.add(attempt)
        self.db.commit()
        return PreparedUidWrite(
            attempt_id=attempt.id,
            chain_root_id=source.chain_root_id,
            source_identifier_id=source.id,
            target_identifier_id=target.id,
            source_uid=source.value,
            target_uid=target.value,
        )

    def complete_attempt(
        self,
        attempt_id: int,
        protocol: UidRotationProtocol,
        outcome: UidRotationOutcome,
        detail: Optional[str] = None,
    ) -> None:
        attempt = self.db.get(UidRotationAttempt, attempt_id)
        if not attempt:
            return
        attempt.protocol = protocol
        attempt.outcome = outcome
        attempt.detail = detail[:500] if detail else None
        self.db.commit()

    def get_lineage(self, root_id: int) -> Optional[dict]:
        root = self.db.get(Identifier, root_id)
        if not root or root.chain_root_id != root.id:
            return None
        return {
            "root_id": root.id,
            "user_id": root.user_id,
            "last_write_attempt_at": root.last_write_attempt_at,
            "identifiers": self._get_nodes(root.id),
            "attempts": list(
                self.db.scalars(
                    select(UidRotationAttempt)
                    .where(UidRotationAttempt.chain_root_id == root.id)
                    .order_by(UidRotationAttempt.attempted_at.desc())
                ).all()
            ),
        }

    def delete_lineage(self, root_id: int) -> bool:
        root = self.db.get(Identifier, root_id)
        if not root or root.chain_root_id != root.id:
            return False
        self.db.execute(
            delete(UidRotationAttempt).where(
                UidRotationAttempt.chain_root_id == root_id
            )
        )
        for node in reversed(self._get_nodes(root_id)):
            self.db.delete(node)
        self.db.commit()
        return True

    def _initialize_lineage(self, identifier: Identifier) -> None:
        if identifier.chain_root_id:
            return
        self.db.flush()
        identifier.chain_root_id = identifier.id
        identifier.state = IdentifierState.CURRENT
        identifier.confirmed_at = identifier.confirmed_at or utcnow()
        self.db.flush()
        self._create_pending(identifier.id, identifier)

    def _create_pending(self, root_id: int, predecessor: Identifier) -> Identifier:
        reservation = self._generate_reservation()
        candidate = Identifier(
            value=reservation.value,
            type=IdentifierType.UID,
            user_id=predecessor.user_id,
            chain_root_id=root_id,
            predecessor_id=predecessor.id,
            reservation_id=reservation.id,
            state=IdentifierState.PENDING,
            generated_at=utcnow(),
        )
        self.db.add(candidate)
        self.db.flush()
        return candidate

    def _generate_reservation(self) -> UidReservation:
        for _ in range(256):
            raw = secrets.token_bytes(4)
            if raw[0] == 0x88:
                continue
            reservation = UidReservation(value=raw.hex().upper())
            try:
                with self.db.begin_nested():
                    self.db.add(reservation)
                    self.db.flush()
                return reservation
            except IntegrityError:
                continue
        raise RuntimeError("Unable to reserve a collision-free UID")

    def _ensure_identifier_reservation(self, identifier: Identifier) -> None:
        if identifier.reservation_id or identifier.type != IdentifierType.UID:
            return
        normalized = normalize_uid(identifier.value)
        reservation = self.db.scalar(
            select(UidReservation).where(
                func.lower(UidReservation.value) == normalized.lower()
            )
        )
        if reservation is None:
            reservation = UidReservation(value=normalized)
            self.db.add(reservation)
            self.db.flush()
        identifier.value = normalized
        identifier.reservation_id = reservation.id

    def _get_nodes(self, root_id: int) -> list[Identifier]:
        return list(
            self.db.scalars(
                select(Identifier)
                .where(Identifier.chain_root_id == root_id)
                .order_by(Identifier.id)
            ).all()
        )

    def _get_current(self, root_id: int) -> Optional[Identifier]:
        return self.db.scalar(
            select(Identifier).where(
                Identifier.chain_root_id == root_id,
                Identifier.state == IdentifierState.CURRENT,
            )
        )

    def _has_pending(self, root_id: int) -> bool:
        return (
            self.db.scalar(
                select(Identifier.id).where(
                    Identifier.chain_root_id == root_id,
                    Identifier.state == IdentifierState.PENDING,
                )
            )
            is not None
        )
