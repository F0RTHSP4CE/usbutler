"""User service for database operations."""

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.user import User, UserStatus
from app.schemas.user import UserCreate, UserUpdate


class UserService:
    """Service for user CRUD operations."""

    def __init__(self, db: Session):
        self.db = db

    def get_all(self, skip: int = 0, limit: int = 100) -> List[User]:
        """Get all users with pagination."""
        stmt = (
            select(User)
            .options(selectinload(User.identifiers))
            .offset(skip)
            .limit(limit)
        )
        return list(self.db.scalars(stmt).all())

    def get_by_id(self, user_id: int) -> Optional[User]:
        """Get a user by ID."""
        stmt = (
            select(User)
            .options(selectinload(User.identifiers))
            .where(User.id == user_id)
        )
        return self.db.scalars(stmt).first()

    def get_by_username(self, username: str) -> Optional[User]:
        """Get a user by username."""
        stmt = (
            select(User)
            .options(selectinload(User.identifiers))
            .where(User.username == username)
        )
        return self.db.scalars(stmt).first()

    def create(self, user_data: UserCreate) -> User:
        """Create a new user."""
        user = User(
            username=user_data.username,
            status=user_data.status,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def update(self, user_id: int, user_data: UserUpdate) -> Optional[User]:
        """Update an existing user."""
        user = self.get_by_id(user_id)
        if not user:
            return None

        update_data = user_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(user, field, value)

        self.db.commit()
        self.db.refresh(user)
        return user

    def delete(self, user_id: int) -> bool:
        """Delete a user."""
        user = self.get_by_id(user_id)
        if not user:
            return False

        self.db.delete(user)
        self.db.commit()
        return True

    def get_active_users(self) -> List[User]:
        """Get all active users."""
        stmt = (
            select(User)
            .options(selectinload(User.identifiers))
            .where(User.status == UserStatus.ACTIVE)
        )
        return list(self.db.scalars(stmt).all())
