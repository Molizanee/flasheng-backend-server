from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.user import PaymentStatus


class PaymentResponse(BaseModel):
    id: UUID
    amount_cents: int
    credits_purchased: int
    status: PaymentStatus
    br_code: str = Field(..., description="Copia e cola PIX code")
    br_code_base64: str = Field(..., description="QR code image as base64")
    created_at: datetime
    expires_at: datetime | None = None


class PaymentStatusResponse(BaseModel):
    id: UUID
    status: PaymentStatus
    credits_purchased: int
    expires_at: datetime | None = None


class CreditBalanceResponse(BaseModel):
    credits: int
