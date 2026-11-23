import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import redis.asyncio as redis
from sqlalchemy import delete

from app.database import AsyncSessionLocal, Base, engine
import app.models  # noqa: F401
from app.models import AuditLog, Mailbox
from app.routers import admin, auth, inbound, mailboxes

load_dotenv()


async def auto_purge_expired_mailboxes():
    """Story 5: Periodically purges expired burnt mailboxes & cascaded messages."""
    while True:
        try:
            async with AsyncSessionLocal() as db:
                now = datetime.now(timezone.utc)
                result = await db.execute(delete(Mailbox).where(Mailbox.expires_at <= now))
                if result.rowcount:
                    db.add(AuditLog(
                        event_type="AUTO_PURGE_COMPLETED",
                        severity="INFO",
                        details={"purged_count": result.rowcount},
                    ))
                await db.commit()
        except Exception:
            pass
        await asyncio.sleep(300)  # Runs every 5 minutes


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    app.state.redis = redis.from_url(redis_url, decode_responses=True)
    purge_task = asyncio.create_task(auto_purge_expired_mailboxes())

    yield

    purge_task.cancel()
    await app.state.redis.aclose()
    await engine.dispose()


app = FastAPI(
    title="Single-Use Burnt Email & Form Automation API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^(chrome-extension|moz-extension)://.*$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def error_audit_middleware(request: Request, call_next):
    """Story 8: Captures unhandled server errors into audit_logs."""
    try:
        return await call_next(request)
    except Exception as exc:
        async with AsyncSessionLocal() as db:
            db.add(AuditLog(
                event_type="UNHANDLED_API_ERROR",
                severity="ERROR",
                source_ip=request.client.host if request.client else None,
                details={"path": str(request.url.path), "error": str(exc)},
            ))
            await db.commit()
        return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


app.include_router(auth.router, prefix="/api/auth", tags=["Auth & RBAC"])
app.include_router(admin.router, prefix="/api/admin", tags=["Admin Config & Logs"])
app.include_router(mailboxes.router, prefix="/api/mailboxes", tags=["Mailboxes & Insta-Burn"])
app.include_router(inbound.router, prefix="/api/inbound", tags=["Inbound Mail"])


@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "ok"}