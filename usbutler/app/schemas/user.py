"""User schemas."""

from typing import List, Optional
from pydantic import BaseModel, ConfigDict
from app.models.user import UserStatus


class UserCreate(BaseModel):
    username: str
    status: UserStatus = UserStatus.ACTIVE
    allowed_sources: Optional[List[str]] = None
    uid_rotation_enabled: bool = True
    uid_rotation_every_read: bool = False


class UserUpdate(BaseModel):
    username: Optional[str] = None
    status: Optional[UserStatus] = None
    allowed_sources: Optional[List[str]] = None
    uid_rotation_enabled: Optional[bool] = None
    uid_rotation_every_read: Optional[bool] = None


class IdentifierBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    value: str
    type: str
    state: str
    chain_root_id: Optional[int] = None


class IdentifierLookupRequest(BaseModel):
    value: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    status: UserStatus
    allowed_sources: List[str] = []
    uid_rotation_enabled: bool
    uid_rotation_every_read: bool


class UserWithIdentifiers(UserResponse):
    identifiers: List[IdentifierBrief] = []


class TokenResponse(BaseModel):
    token: str
    message: str = "Store this token securely. It will not be shown again."
