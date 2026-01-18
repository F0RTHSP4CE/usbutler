from enum import Enum
from pydantic import BaseModel, ConfigDict, Field


class UserStatus(str, Enum):
    ACTIVE = "Active"
    DISABLED = "Disabled"


class UserBase(BaseModel):
    username: str = Field(..., min_length=1, max_length=100, description="Username")
    status: UserStatus = Field(default=UserStatus.ACTIVE, description="User status")


class UserCreate(UserBase):
    """Schema for creating a new user."""

    pass


class UserUpdate(BaseModel):
    """Schema for updating an existing user."""

    username: str | None = Field(None, min_length=1, max_length=100)
    status: UserStatus | None = None


class User(UserBase):
    """Full user model stored in database."""

    id: str = Field(..., description="Unique user ID")
    identifiers: list[str] = Field(
        default_factory=list, description="List of identifier IDs"
    )

    model_config = ConfigDict(from_attributes=True)


class UserResponse(BaseModel):
    """Response schema for a single user."""

    success: bool = True
    data: User


class UserListResponse(BaseModel):
    """Response schema for a list of users."""

    success: bool = True
    data: list[User]
    total: int
