"""User service for database operations."""

from typing import List, Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from app.models.identifier import Identifier, MifareCredential
from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate


class UserService:
    def __init__(self, db: Session):
        self.db = db

    def get_all(self, skip: int = 0, limit: int = 100) -> List[User]:
        stmt = (
            select(User)
            .options(
                selectinload(User.identifiers)
                .selectinload(Identifier.mifare_credential)
                .selectinload(MifareCredential.uuid_values)
            )
            .offset(skip)
            .limit(limit)
        )
        return list(self.db.scalars(stmt).all())

    def set_mifare_rotation_for_all(self, enabled: bool) -> int:
        """Atomically update the per-user rolling preference for every user."""
        result = self.db.execute(update(User).values(mifare_rotation_enabled=enabled))
        self.db.commit()
        return int(getattr(result, "rowcount", 0) or 0)

    def get_by_id(self, user_id: int) -> Optional[User]:
        stmt = (
            select(User)
            .options(selectinload(User.identifiers))
            .where(User.id == user_id)
        )
        return self.db.scalars(stmt).first()

    def get_by_username(self, username: str) -> Optional[User]:
        stmt = (
            select(User)
            .options(selectinload(User.identifiers))
            .where(User.username == username)
        )
        return self.db.scalars(stmt).first()

    def create(
        self, data: UserCreate, allowed_sources_csv: Optional[str] = None
    ) -> User:
        user = User(
            username=data.username,
            status=data.status,
            api_allowed_sources=allowed_sources_csv,
            mifare_rotation_enabled=data.mifare_rotation_enabled,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def update(
        self,
        user_id: int,
        data: UserUpdate,
        allowed_sources_csv: Optional[str] = None,
    ) -> Optional[User]:
        user = self.get_by_id(user_id)
        if not user:
            return None
        update_data = data.model_dump(exclude_unset=True, exclude={"allowed_sources"})
        for key, value in update_data.items():
            setattr(user, key, value)
        if data.allowed_sources is not None:
            user.api_allowed_sources = allowed_sources_csv
        self.db.commit()
        self.db.refresh(user)
        return user

    def set_token_hash(self, user_id: int, token_hash: Optional[str]) -> Optional[User]:
        user = self.get_by_id(user_id)
        if not user:
            return None
        user.api_token_hash = token_hash
        self.db.commit()
        self.db.refresh(user)
        return user

    def delete(self, user_id: int) -> bool:
        user = self.get_by_id(user_id)
        if not user:
            return False
        self.db.delete(user)
        self.db.commit()
        return True
