"""User schemas."""

from typing import List, Optional
from pydantic import BaseModel, ConfigDict
from app.models.user import UserStatus


class UserCreate(BaseModel):
    username: str
    status: UserStatus = UserStatus.ACTIVE
    allowed_sources: Optional[List[str]] = None


class UserUpdate(BaseModel):
    username: Optional[str] = None
    status: Optional[UserStatus] = None
    allowed_sources: Optional[List[str]] = None


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
    allowed_sources: List[str] = []


class UserWithIdentifiers(UserResponse):
    identifiers: List[IdentifierBrief] = []


class TokenResponse(BaseModel):
    token: str
    message: str = "Store this token securely. It will not be shown again."
