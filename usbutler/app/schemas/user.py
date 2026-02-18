"""User schemas."""

from typing import List, Optional
from pydantic import BaseModel, ConfigDict
from app.models.user import UserStatus


class UserCreate(BaseModel):
    username: str
    status: UserStatus = UserStatus.ACTIVE


class UserUpdate(BaseModel):
    username: Optional[str] = None
    status: Optional[UserStatus] = None


class IdentifierBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    value: str
    type: str


class IdentifierLookupRequest(BaseModel):
    value: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    status: UserStatus


class UserWithIdentifiers(UserResponse):
    identifiers: List[IdentifierBrief] = []
