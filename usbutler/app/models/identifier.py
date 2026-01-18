"""Identifier model."""

import enum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import String, Enum, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class IdentifierType(str, enum.Enum):
    """Identifier type enumeration."""

    PAN = "PAN"  # Payment card number
    UID = "UID"  # NFC tag UID


class Identifier(Base):
    """Identifier model representing a card/tag identifier."""

    __tablename__ = "identifiers"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    value: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    type: Mapped[IdentifierType] = mapped_column(Enum(IdentifierType))
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )

    # Relationships
    user: Mapped[Optional["User"]] = relationship("User", back_populates="identifiers")

    def __repr__(self) -> str:
        return f"<Identifier(id={self.id}, value={self.value}, type={self.type})>"
