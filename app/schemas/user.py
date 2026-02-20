from datetime import datetime

from pydantic import BaseModel


class UserProfileResponse(BaseModel):
    id: str
    linkedin_url: str | None = None
    credits: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserProfileUpdate(BaseModel):
    linkedin_url: str | None = None
