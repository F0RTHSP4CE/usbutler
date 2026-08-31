"""Identifier and rotating UID lineage models."""

import enum
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from sqlalchemy import DateTime, String, Enum, ForeignKey, Integer, Index, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.utils.time import utcnow

if TYPE_CHECKING:
    from app.models.user import User


class IdentifierType(str, enum.Enum):
    PAN = "PAN"
    UID = "UID"


class IdentifierState(str, enum.Enum):
    STATIC = "static"
    CURRENT = "current"
    PENDING = "pending"
    RETIRED = "retired"


class Identifier(Base):
    __tablename__ = "identifiers"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    value: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    type: Mapped[IdentifierType] = mapped_column(Enum(IdentifierType))
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    user: Mapped[Optional["User"]] = relationship("User", back_populates="identifiers")
    chain_root_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("identifiers.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    predecessor_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("identifiers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reservation_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("uid_reservations.id", ondelete="RESTRICT"),
        nullable=True,
        unique=True,
    )
    state: Mapped[IdentifierState] = mapped_column(
        Enum(IdentifierState), default=IdentifierState.STATIC, index=True
    )
    generated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_write_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )

    chain_root: Mapped[Optional["Identifier"]] = relationship(
        "Identifier",
        remote_side="Identifier.id",
        foreign_keys=[chain_root_id],
        post_update=True,
    )
    predecessor: Mapped[Optional["Identifier"]] = relationship(
        "Identifier",
        remote_side="Identifier.id",
        foreign_keys=[predecessor_id],
    )
    reservation: Mapped[Optional["UidReservation"]] = relationship(
        "UidReservation", foreign_keys=[reservation_id]
    )

    __table_args__ = (
        Index("uq_identifiers_value_lower", func.lower(value), unique=True),
        Index(
            "uq_identifiers_current_per_chain",
            chain_root_id,
            unique=True,
            sqlite_where=(state == IdentifierState.CURRENT),
            postgresql_where=(state == IdentifierState.CURRENT),
        ),
    )


class UidReservation(Base):
    """A UID value that must never be generated again."""

    __tablename__ = "uid_reservations"

    id: Mapped[int] = mapped_column(primary_key=True)
    value: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        Index("uq_uid_reservations_value_lower", func.lower(value), unique=True),
    )


class UidRotationProtocol(str, enum.Enum):
    UNKNOWN = "unknown"
    GEN1A = "gen1a"
    GEN2 = "gen2"


class UidRotationOutcome(str, enum.Enum):
    STARTED = "started"
    ACKNOWLEDGED = "acknowledged"
    UNSUPPORTED = "unsupported"
    NAK = "nak"
    TIMEOUT = "timeout"
    PCSC_ERROR = "pcsc_error"
    CONNECTION_LOSS = "connection_loss"
    FAILED = "failed"


class UidRotationAttempt(Base):
    """Immutable audit record for one hardware UID-write attempt."""

    __tablename__ = "uid_rotation_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    chain_root_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("identifiers.id", ondelete="CASCADE"), index=True
    )
    source_identifier_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("identifiers.id", ondelete="CASCADE"), index=True
    )
    target_reservation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("uid_reservations.id", ondelete="RESTRICT"), index=True
    )
    attempted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    protocol: Mapped[UidRotationProtocol] = mapped_column(
        Enum(UidRotationProtocol), default=UidRotationProtocol.UNKNOWN
    )
    outcome: Mapped[UidRotationOutcome] = mapped_column(
        Enum(UidRotationOutcome), default=UidRotationOutcome.STARTED
    )
    detail: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    chain_root: Mapped[Identifier] = relationship(
        Identifier, foreign_keys=[chain_root_id]
    )
    source_identifier: Mapped[Identifier] = relationship(
        Identifier, foreign_keys=[source_identifier_id]
    )
    target_reservation: Mapped[UidReservation] = relationship(UidReservation)
