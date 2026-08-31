"""Identifier and MIFARE credential models."""

import enum
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.utils.time import utcnow

if TYPE_CHECKING:
    from app.models.user import User


class IdentifierType(str, enum.Enum):
    PAN = "PAN"
    UID = "UID"


class Identifier(Base):
    __tablename__ = "identifiers"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    value: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    type: Mapped[IdentifierType] = mapped_column(Enum(IdentifierType))
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    user: Mapped[Optional["User"]] = relationship("User", back_populates="identifiers")
    mifare_credential: Mapped[Optional["MifareCredential"]] = relationship(
        "MifareCredential",
        back_populates="identifier",
        cascade="all, delete-orphan",
        single_parent=True,
        uselist=False,
    )

    __table_args__ = (
        Index("uq_identifiers_value_lower", func.lower(value), unique=True),
    )


class MifareUuidState(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"


class MifareCredential(Base):
    """Rolling data-block credential belonging to one legacy UID identifier."""

    __tablename__ = "mifare_credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    identifier_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("identifiers.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    last_verified_rotation_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    last_write_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    last_write_error: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    identifier: Mapped[Identifier] = relationship(
        Identifier, back_populates="mifare_credential"
    )
    uuid_values: Mapped[List["MifareUuidValue"]] = relationship(
        "MifareUuidValue",
        back_populates="credential",
        cascade="all, delete-orphan",
        order_by="MifareUuidValue.created_at",
    )


class MifareUuidValue(Base):
    """A pending or previously confirmed UUID accepted for a MIFARE fob."""

    __tablename__ = "mifare_uuid_values"

    id: Mapped[int] = mapped_column(primary_key=True)
    credential_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("mifare_credentials.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    value: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    state: Mapped[MifareUuidState] = mapped_column(
        Enum(MifareUuidState), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    credential: Mapped[MifareCredential] = relationship(
        MifareCredential, back_populates="uuid_values"
    )

    __table_args__ = (
        Index("uq_mifare_uuid_values_value_lower", func.lower(value), unique=True),
        Index(
            "uq_mifare_uuid_values_pending_per_credential",
            credential_id,
            unique=True,
            sqlite_where=(state == MifareUuidState.PENDING),
            postgresql_where=(state == MifareUuidState.PENDING),
        ),
    )
