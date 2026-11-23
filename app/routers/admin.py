import base64
import hashlib
import os
from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_admin
from app.models import AuditLog, SystemConfig, User
from app.schemas import AuditLogResponse, SystemConfigResponse, SystemConfigUpdate

router = APIRouter()


def _get_cipher() -> Fernet:
    secret = os.getenv("JWT_SECRET_KEY", "dev-secret-change-in-prod").encode()
    key = base64.urlsafe_b64encode(hashlib.sha256(secret).digest())
    return Fernet(key)


@router.get("/config", response_model=SystemConfigResponse)
async def get_system_config(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(SystemConfig).where(SystemConfig.id == 1))
    config = result.scalar_one_or_none()
    if not config:
        config = SystemConfig(id=1)
        db.add(config)
        await db.commit()
        await db.refresh(config)

    return SystemConfigResponse(
        provider_name=config.provider_name,
        has_api_key=bool(config.encrypted_api_key),
        global_rate_limit_per_min=config.global_rate_limit_per_min,
        max_active_boxes_per_user=config.max_active_boxes_per_user,
        updated_at=config.updated_at,
    )


@router.put("/config", response_model=SystemConfigResponse)
async def update_system_config(
    payload: SystemConfigUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(SystemConfig).where(SystemConfig.id == 1))
    config = result.scalar_one_or_none()
    if not config:
        config = SystemConfig(id=1)
        db.add(config)

    config.provider_name = payload.provider_name
    config.global_rate_limit_per_min = payload.global_rate_limit_per_min
    config.max_active_boxes_per_user = payload.max_active_boxes_per_user

    if payload.provider_api_key:
        config.encrypted_api_key = _get_cipher().encrypt(payload.provider_api_key.encode()).decode()

    db.add(AuditLog(
        event_type="SYSTEM_CONFIG_UPDATED",
        severity="INFO",
        user_id=admin.id,
        details={
            "provider_name": config.provider_name,
            "global_rate_limit_per_min": config.global_rate_limit_per_min,
        },
    ))
    await db.commit()
    await db.refresh(config)

    return SystemConfigResponse(
        provider_name=config.provider_name,
        has_api_key=bool(config.encrypted_api_key),
        global_rate_limit_per_min=config.global_rate_limit_per_min,
        max_active_boxes_per_user=config.max_active_boxes_per_user,
        updated_at=config.updated_at,
    )


@router.get("/audit-logs", response_model=list[AuditLogResponse])
async def list_audit_logs(
    limit: int = 50,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AuditLog).order_by(desc(AuditLog.created_at)).limit(min(limit, 200))
    )
    return result.scalars().all()