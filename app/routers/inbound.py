from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
import redis.asyncio as redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_redis
from app.models import AuditLog, Mailbox, Message
from app.schemas import InboundEmailWebhook, MessageResponse
from app.services.sanitizer import extract_otp_and_link, sanitize_html

router = APIRouter()


@router.post("/webhook", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def receive_inbound_email(
    payload: InboundEmailWebhook,
    db: AsyncSession = Depends(get_db),
    r: redis.Redis = Depends(get_redis),
):
    now = datetime.now(timezone.utc)
    result = await db.execute(select(Mailbox).where(Mailbox.address == payload.recipient))
    mailbox = result.scalar_one_or_none()

    # Reject if missing, burned, or TTL expired (REQ-3, REQ-10)
    if not mailbox or mailbox.status != "active" or mailbox.expires_at <= now:
        try:
            await r.delete(f"route:{payload.recipient}")
        except redis.RedisError:
            pass
        raise HTTPException(status_code=404, detail="Recipient mailbox inactive or expired")

    clean_html = sanitize_html(payload.html_body)
    otp, link = extract_otp_and_link(payload.text_body, payload.html_body)

    message = Message(
        mailbox_id=mailbox.id,
        sender=payload.sender,
        subject=payload.subject,
        sanitized_html=clean_html,
        extracted_otp=otp,
        verification_link=link,
    )
    db.add(message)
    db.add(AuditLog(
        event_type="EMAIL_RECEIVED",
        severity="INFO",
        user_id=mailbox.user_id,
        details={"recipient": payload.recipient, "has_otp": bool(otp), "has_link": bool(link)},
    ))
    await db.commit()
    await db.refresh(message)
    return message