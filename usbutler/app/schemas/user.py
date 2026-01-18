"""User schemas."""

from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from app.models.user import UserStatus


class UserBase(BaseModel):
    """Base schema for user data."""

    username: str
    status: UserStatus = UserStatus.ACTIVE


class UserCreate(UserBase):
    """Schema for creating a user."""

    pass


class UserUpdate(BaseModel):
    """Schema for updating a user."""

    username: Optional[str] = None
    status: Optional[UserStatus] = None


class UserResponse(UserBase):
    """Schema for user response."""

    model_config = ConfigDict(from_attributes=True)

    id: int


class IdentifierBrief(BaseModel):
    """Brief identifier info for user response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    value: str
    type: str


class UserWithIdentifiers(UserResponse):
    """Schema for user response with identifiers."""

    identifiers: List[IdentifierBrief] = []
