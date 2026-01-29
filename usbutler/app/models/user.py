"""User model."""

import enum
from typing import TYPE_CHECKING, List
from sqlalchemy import String, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

if TYPE_CHECKING:
    from app.models.identifier import Identifier


class UserStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus), default=UserStatus.ACTIVE
    )
    identifiers: Mapped[List["Identifier"]] = relationship(
        "Identifier", back_populates="user", cascade="all, delete-orphan"
    )
