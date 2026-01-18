from fastapi import Depends, HTTPException, status

from database import JsonDatabase, get_database
from schemas import User, UserCreate, UserUpdate


class UserService:
    """Service layer for user operations."""

    COLLECTION = "users"

    def __init__(self, db: JsonDatabase):
        self.db = db

    def get_all(self) -> list[User]:
        """Get all users."""
        users_data = self.db.get_all(self.COLLECTION)
        return [User(**user) for user in users_data.values()]

    def get_by_id(self, user_id: str) -> User:
        """Get a user by ID."""
        user_data = self.db.get_by_id(self.COLLECTION, user_id)
        if not user_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User with id '{user_id}' not found",
            )
        return User(**user_data)

    def get_by_username(self, username: str) -> User | None:
        """Get a user by username."""
        users = self.db.find_by_field(self.COLLECTION, "username", username)
        if users:
            return User(**users[0])
        return None

    def create(self, user_data: UserCreate) -> User:
        """Create a new user."""
        # Check for duplicate username
        existing = self.get_by_username(user_data.username)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"User with username '{user_data.username}' already exists",
            )

        user_id = self.db.generate_id()
        user = User(
            id=user_id,
            username=user_data.username,
            status=user_data.status,
            identifiers=[],
        )
        self.db.create(self.COLLECTION, user_id, user.model_dump())
        return user

    def update(self, user_id: str, user_data: UserUpdate) -> User:
        """Update an existing user."""
        existing = self.get_by_id(user_id)

        # Check for duplicate username if changing
        if user_data.username and user_data.username != existing.username:
            duplicate = self.get_by_username(user_data.username)
            if duplicate and duplicate.id != user_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"User with username '{user_data.username}' already exists",
                )

        update_data = user_data.model_dump(exclude_unset=True)
        updated_user = existing.model_copy(update=update_data)
        self.db.update(self.COLLECTION, user_id, updated_user.model_dump())
        return updated_user

    def delete(self, user_id: str) -> bool:
        """Delete a user."""
        # Ensure user exists
        self.get_by_id(user_id)
        return self.db.delete(self.COLLECTION, user_id)

    def add_identifier(self, user_id: str, identifier_id: str) -> User:
        """Add an identifier to a user."""
        user = self.get_by_id(user_id)
        if identifier_id not in user.identifiers:
            user.identifiers.append(identifier_id)
            self.db.update(self.COLLECTION, user_id, user.model_dump())
        return user

    def remove_identifier(self, user_id: str, identifier_id: str) -> User:
        """Remove an identifier from a user."""
        user = self.get_by_id(user_id)
        if identifier_id in user.identifiers:
            user.identifiers.remove(identifier_id)
            self.db.update(self.COLLECTION, user_id, user.model_dump())
        return user

    def get_user_identifiers(self, user_id: str) -> list[str]:
        """Get all identifier IDs for a user."""
        user = self.get_by_id(user_id)
        return user.identifiers


def get_user_service(db: JsonDatabase = Depends(get_database)) -> UserService:
    """Dependency injection for UserService."""
    return UserService(db)
