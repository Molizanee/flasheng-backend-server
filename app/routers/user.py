import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user_id
from app.database import get_db
from app.models.user import User
from app.schemas.user import UserProfileResponse, UserProfileUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.post("", response_model=UserProfileResponse, status_code=201)
async def create_user(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Create a new user.

    Requires a valid Supabase JWT in the Authorization header.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    existing_user = result.scalar_one_or_none()

    if existing_user:
        return UserProfileResponse.model_validate(existing_user)

    new_user = User(id=user_id, credits=0)
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    return UserProfileResponse.model_validate(new_user)


@router.get("/me", response_model=UserProfileResponse)
async def get_my_profile(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Get the current user's profile.

    Requires a valid Supabase JWT in the Authorization header.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return UserProfileResponse.model_validate(user)


@router.put("/me", response_model=UserProfileResponse)
async def update_my_profile(
    profile_update: UserProfileUpdate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Update the current user's profile.

    Requires a valid Supabase JWT in the Authorization header.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if profile_update.linkedin_url is not None:
        user.linkedin_url = profile_update.linkedin_url

    await db.commit()
    await db.refresh(user)

    return UserProfileResponse.model_validate(user)
