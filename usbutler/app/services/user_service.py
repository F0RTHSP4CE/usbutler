"""User service for database operations."""

from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate


class UserService:
    def __init__(self, db: Session):
        self.db = db

    def get_all(self, skip: int = 0, limit: int = 100) -> List[User]:
        stmt = (
            select(User)
            .options(selectinload(User.identifiers))
            .offset(skip)
            .limit(limit)
        )
        return list(self.db.scalars(stmt).all())

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

    def create(self, data: UserCreate) -> User:
        user = User(username=data.username, status=data.status)
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def update(self, user_id: int, data: UserUpdate) -> Optional[User]:
        user = self.get_by_id(user_id)
        if not user:
            return None
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(user, k, v)
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
