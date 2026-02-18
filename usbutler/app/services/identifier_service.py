"""Identifier service for database operations."""

from typing import List, Optional
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.identifier import Identifier
from app.schemas.identifier import IdentifierCreate, IdentifierUpdate


class IdentifierService:
    def __init__(self, db: Session):
        self.db = db

    def get_all(self, skip: int = 0, limit: int = 100) -> List[Identifier]:
        stmt = (
            select(Identifier)
            .options(selectinload(Identifier.user))
            .offset(skip)
            .limit(limit)
        )
        return list(self.db.scalars(stmt).all())

    def get_by_id(self, identifier_id: int) -> Optional[Identifier]:
        stmt = (
            select(Identifier)
            .options(selectinload(Identifier.user))
            .where(Identifier.id == identifier_id)
        )
        return self.db.scalars(stmt).first()

    def get_by_value(self, value: str) -> Optional[Identifier]:
        stmt = (
            select(Identifier)
            .options(selectinload(Identifier.user))
            .where(func.lower(Identifier.value) == value.lower())
        )
        return self.db.scalars(stmt).first()

    def create(self, data: IdentifierCreate) -> Identifier:
        identifier = Identifier(value=data.value, type=data.type, user_id=data.user_id)
        self.db.add(identifier)
        self.db.commit()
        self.db.refresh(identifier)
        return identifier

    def update(
        self, identifier_id: int, data: IdentifierUpdate
    ) -> Optional[Identifier]:
        identifier = self.get_by_id(identifier_id)
        if not identifier:
            return None
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(identifier, k, v)
        self.db.commit()
        self.db.refresh(identifier)
        return identifier

    def delete(self, identifier_id: int) -> bool:
        identifier = self.get_by_id(identifier_id)
        if not identifier:
            return False
        self.db.delete(identifier)
        self.db.commit()
        return True

    def assign_to_user(
        self, identifier_id: int, user_id: Optional[int]
    ) -> Optional[Identifier]:
        identifier = self.get_by_id(identifier_id)
        if not identifier:
            return None
        identifier.user_id = user_id
        self.db.commit()
        self.db.refresh(identifier)
        return identifier
