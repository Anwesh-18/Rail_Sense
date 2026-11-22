from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID
from pydantic import BaseModel, ConfigDict, EmailStr, Field



class UserRole(str, Enum):
    ADMIN = "admin"
    USER = "user"


class MailboxStatus(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    BURNED = "burned"


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)


class UserRoleUpdate(BaseModel):
    role: UserRole


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    role: UserRole
    is_active: bool
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class SystemConfigUpdate(BaseModel):
    provider_name: str = Field(default="internal_mx", max_length=50)
    provider_api_key: str | None = Field(default=None, description="Stored encrypted at rest")
    global_rate_limit_per_min: int = Field(default=10, ge=1, le=1000)
    max_active_boxes_per_user: int = Field(default=5, ge=1, le=50)


class SystemConfigResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    provider_name: str
    has_api_key: bool
    global_rate_limit_per_min: int
    max_active_boxes_per_user: int
    updated_at: datetime



class InstaBurnRequest(BaseModel):
    custom_alias: str | None = Field(
        default=None,
        min_length=3,
        max_length=24,
        pattern=r"^[a-z0-9_-]+$"
    )
    ttl_seconds: int = Field(default=3600, ge=300, le=86400)  # Max 24h (SRS REQ-3/5.5)
    target_domain: str | None = Field(default=None, max_length=120)


class MailboxResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    address: str
    status: MailboxStatus
    target_domain: str | None
    created_at: datetime
    expires_at: datetime


class InboundEmailWebhook(BaseModel):
    recipient: EmailStr
    sender: str
    subject: str = "(No Subject)"
    text_body: str | None = None
    html_body: str | None = None


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    mailbox_id: UUID
    sender: str
    subject: str
    sanitized_html: str | None
    extracted_otp: str | None = None
    verification_link: str | None = None
    received_at: datetime


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_type: str
    severity: str  
    source_ip: str | None
    user_id: UUID | None
    details: dict[str, Any]
    created_at: datetime