import os
import secrets
import string
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, status
import redis.asyncio as redis
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, get_redis
from app.models import AuditLog, Mailbox, Message, SystemConfig, User
from app.schemas import InstaBurnRequest, MailboxResponse, MessageResponse

router = APIRouter()
MAIL_DOMAIN = os.getenv("MAIL_DOMAIN", "burn.yourdomain.com")


def _generate_slug(length: int = 10) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


async def _get_runtime_limits(db: AsyncSession) -> tuple[int, int]:
    res = await db.execute(select(SystemConfig).where(SystemConfig.id == 1))
    cfg = res.scalar_one_or_none()
    if not cfg:
        return 10, 5
    return cfg.global_rate_limit_per_min, cfg.max_active_boxes_per_user


@router.post("/insta-burn", response_model=MailboxResponse, status_code=status.HTTP_201_CREATED)
async def create_insta_burn(
    payload: InstaBurnRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    r: redis.Redis = Depends(get_redis),
):
    rate_limit, max_boxes = await _get_runtime_limits(db)

    # 1. Global / User Rate Limit Check (Story 9 & REQ-15, REQ-17)
    minute_bucket = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
    rate_key = f"rate:create:{minute_bucket}"
    try:
        current_count = await r.incr(rate_key)
        if current_count == 1:
            await r.expire(rate_key, 60)
        if current_count > rate_limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Global rate limit exceeded. Try again shortly.",
                headers={"Retry-After": "60"},
            )
    except redis.RedisError:
        pass  # Allow graceful operation if local Redis daemon is stopped

    # 2. Enforce max concurrently active mailboxes (SRS Section 5.5)
    now = datetime.now(timezone.utc)
    active_count_res = await db.execute(
        select(func.count(Mailbox.id)).where(
            and_(
                Mailbox.user_id == current_user.id,
                Mailbox.status == "active",
                Mailbox.expires_at > now,
            )
        )
    )
    if (active_count_res.scalar() or 0) >= max_boxes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Maximum {max_boxes} concurrently active mailboxes allowed.",
        )

    # 3. Generate unique address & bind TTL (Story 3 & REQ-1, REQ-2, REQ-13)
    slug = payload.custom_alias or _generate_slug()
    address = f"{slug}@{MAIL_DOMAIN}"

    existing = await db.execute(select(Mailbox).where(Mailbox.address == address))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email alias already exists. Choose another.")

    expires_at = now + timedelta(seconds=payload.ttl_seconds)
    mailbox = Mailbox(
        user_id=current_user.id,
        address=address,
        status="active",
        target_domain=payload.target_domain,
        expires_at=expires_at,
    )
    db.add(mailbox)
    await db.flush()

    try:
        await r.set(f"route:{address}", str(mailbox.id), ex=payload.ttl_seconds)
    except redis.RedisError:
        pass

    db.add(AuditLog(
        event_type="MAILBOX_CREATED",
        severity="INFO",
        source_ip=request.client.host if request.client else None,
        user_id=current_user.id,
        details={"address": address, "ttl_seconds": payload.ttl_seconds},
    ))
    await db.commit()
    await db.refresh(mailbox)
    return mailbox


@router.get("/", response_model=list[MailboxResponse])
async def list_active_mailboxes(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Mailbox)
        .where(
            and_(
                Mailbox.user_id == current_user.id,
                Mailbox.status == "active",
                Mailbox.expires_at > now,
            )
        )
        .order_by(desc(Mailbox.created_at))
    )
    return result.scalars().all()


@router.get("/{address}/messages", response_model=list[MessageResponse])
async def get_mailbox_messages(
    address: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    mb_res = await db.execute(
        select(Mailbox).where(and_(Mailbox.address == address, Mailbox.user_id == current_user.id))
    )
    mailbox = mb_res.scalar_one_or_none()
    if not mailbox or mailbox.status != "active":
        raise HTTPException(status_code=404, detail="Active mailbox not found")

    msg_res = await db.execute(
        select(Message).where(Message.mailbox_id == mailbox.id).order_by(desc(Message.received_at))
    )
    return msg_res.scalars().all()


@router.delete("/{address}", status_code=status.HTTP_204_NO_CONTENT)
async def instant_burn_mailbox(
    address: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    r: redis.Redis = Depends(get_redis),
):
    # Immediate expiration & message purge (Story 11 & REQ-4, REQ-10)
    mb_res = await db.execute(
        select(Mailbox).where(and_(Mailbox.address == address, Mailbox.user_id == current_user.id))
    )
    mailbox = mb_res.scalar_one_or_none()
    if not mailbox:
        raise HTTPException(status_code=404, detail="Mailbox not found")

    try:
        await r.delete(f"route:{address}")
    except redis.RedisError:
        pass

    db.add(AuditLog(
        event_type="MAILBOX_INSTANT_BURNED",
        severity="INFO",
        source_ip=request.client.host if request.client else None,
        user_id=current_user.id,
        details={"address": address},
    ))
    await db.delete(mailbox)  # Cascades deletion to all associated messages
    await db.commit()