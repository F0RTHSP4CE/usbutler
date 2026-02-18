"""Identifier model."""

import enum
from typing import TYPE_CHECKING, Optional
from sqlalchemy import String, Enum, ForeignKey, Integer, Index, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

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

    __table_args__ = (
        Index("uq_identifiers_value_lower", func.lower(value), unique=True),
    )
