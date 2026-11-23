from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import (
    create_access_token,
    get_current_user,
    hash_password,
    require_admin,
    verify_password,
)
from app.models import AuditLog, User
from app.schemas import TokenResponse, UserCreate, UserResponse, UserRoleUpdate

router = APIRouter()


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register_user(payload: UserCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    # First user becomes admin automatically for prototype bootstrap
    count_result = await db.execute(select(func.count(User.id)))
    is_first_user = (count_result.scalar() or 0) == 0
    assigned_role = "admin" if is_first_user else "user"

    new_user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=assigned_role,
    )
    db.add(new_user)
    await db.flush()

    db.add(AuditLog(
        event_type="USER_REGISTERED",
        severity="INFO",
        user_id=new_user.id,
        details={"email": new_user.email, "role": assigned_role},
    ))
    await db.commit()
    await db.refresh(new_user)

    token = create_access_token(new_user.id, new_user.role)
    return TokenResponse(access_token=token, user=new_user)


@router.post("/login", response_model=TokenResponse)
async def login_user(payload: UserCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token(user.id, user.role)
    return TokenResponse(access_token=token, user=user)


@router.get("/me", response_model=UserResponse)
async def get_profile(current_user: User = Depends(get_current_user)):
    return current_user


@router.patch("/users/{user_id}/role", response_model=UserResponse)
async def update_user_role(
    user_id: UUID,
    payload: UserRoleUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    target_user = result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    target_user.role = payload.role.value
    db.add(AuditLog(
        event_type="ROLE_UPDATED",
        severity="INFO",
        user_id=admin.id,
        details={"target_user_id": str(user_id), "new_role": payload.role.value},
    ))
    await db.commit()
    await db.refresh(target_user)
    return target_user