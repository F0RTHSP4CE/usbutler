"""Identifier service for database operations."""

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.identifier import Identifier, IdentifierType
from app.schemas.identifier import IdentifierCreate, IdentifierUpdate


class IdentifierService:
    """Service for identifier CRUD operations."""

    def __init__(self, db: Session):
        self.db = db

    def get_all(self, skip: int = 0, limit: int = 100) -> List[Identifier]:
        """Get all identifiers with pagination."""
        stmt = (
            select(Identifier)
            .options(selectinload(Identifier.user))
            .offset(skip)
            .limit(limit)
        )
        return list(self.db.scalars(stmt).all())

    def get_by_id(self, identifier_id: int) -> Optional[Identifier]:
        """Get an identifier by ID."""
        stmt = (
            select(Identifier)
            .options(selectinload(Identifier.user))
            .where(Identifier.id == identifier_id)
        )
        return self.db.scalars(stmt).first()

    def get_by_value(self, value: str) -> Optional[Identifier]:
        """Get an identifier by value."""
        stmt = (
            select(Identifier)
            .options(selectinload(Identifier.user))
            .where(Identifier.value == value)
        )
        return self.db.scalars(stmt).first()

    def get_by_user_id(self, user_id: int) -> List[Identifier]:
        """Get all identifiers for a user."""
        stmt = (
            select(Identifier)
            .options(selectinload(Identifier.user))
            .where(Identifier.user_id == user_id)
        )
        return list(self.db.scalars(stmt).all())

    def create(self, identifier_data: IdentifierCreate) -> Identifier:
        """Create a new identifier."""
        identifier = Identifier(
            value=identifier_data.value,
            type=identifier_data.type,
            user_id=identifier_data.user_id,
        )
        self.db.add(identifier)
        self.db.commit()
        self.db.refresh(identifier)
        return identifier

    def update(
        self, identifier_id: int, identifier_data: IdentifierUpdate
    ) -> Optional[Identifier]:
        """Update an existing identifier."""
        identifier = self.get_by_id(identifier_id)
        if not identifier:
            return None

        update_data = identifier_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(identifier, field, value)

        self.db.commit()
        self.db.refresh(identifier)
        return identifier

    def delete(self, identifier_id: int) -> bool:
        """Delete an identifier."""
        identifier = self.get_by_id(identifier_id)
        if not identifier:
            return False

        self.db.delete(identifier)
        self.db.commit()
        return True

    def assign_to_user(
        self, identifier_id: int, user_id: Optional[int]
    ) -> Optional[Identifier]:
        """Assign an identifier to a user (or unassign if user_id is None)."""
        identifier = self.get_by_id(identifier_id)
        if not identifier:
            return None

        identifier.user_id = user_id
        self.db.commit()
        self.db.refresh(identifier)
        return identifier
