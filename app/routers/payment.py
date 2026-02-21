import json
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user_id
from app.config import get_settings
from app.database import get_db
from app.schemas.payment import (
    CreditBalanceResponse,
    CreditPlanResponse,
    CreatePaymentRequest,
    PaymentResponse,
    PaymentStatusResponse,
)
from app.services.payment import payment_service

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/api/v1/payment", tags=["payment"])


@router.get("/plans", response_model=list[CreditPlanResponse])
async def get_credit_plans(
    db: AsyncSession = Depends(get_db),
):
    plans = await payment_service.get_active_plans(db)
    return [
        CreditPlanResponse(
            id=plan.id,
            name=plan.name,
            credits_amount=plan.credits_amount,
            price_brl_cents=plan.price_brl_cents,
            is_active=plan.is_active,
        )
        for plan in plans
    ]


@router.post("/create", response_model=PaymentResponse, status_code=201)
async def create_payment(
    request: CreatePaymentRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):    
    payment = await payment_service.create_pix_payment(
        db=db,
        user_id=user_id,
        plan_id=request.plan_id,
    )

    return PaymentResponse(
        id=payment.id,
        amount_cents=payment.amount_cents,
        credits_purchased=payment.credits_purchased,
        status=payment.status,
        br_code=payment.br_code,
        br_code_base64=payment.br_code_base64,
        created_at=payment.created_at,
        expires_at=payment.expires_at,
    )


@router.get("/{payment_id}", response_model=PaymentStatusResponse)
async def get_payment_status(
    payment_id: UUID,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    payment = await payment_service.check_payment_status(db, str(payment_id))
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    if payment.user_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    return PaymentStatusResponse(
        id=payment.id,
        status=payment.status,
        credits_purchased=payment.credits_purchased,
        expires_at=payment.expires_at,
    )


@router.get("/balance", response_model=CreditBalanceResponse)
async def get_credit_balance(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    credits = await payment_service.get_user_credits(db, user_id)
    return CreditBalanceResponse(credits=credits)


@router.post("/webhook")
async def abacatepay_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    webhook_secret = request.query_params.get("webhookSecret")
    if webhook_secret != settings.abacatepay_webhook_secret:
        logger.warning("Invalid webhook secret received")
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    raw_body = await request.body()
    signature = request.headers.get("X-Webhook-Signature", "")

    if signature and not payment_service.verify_webhook_signature(raw_body, signature):
        logger.warning("Invalid webhook signature")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event = payload.get("event")
    if event != "billing.paid":
        logger.info("Ignoring webhook event: %s", event)
        return {"received": True, "processed": False}

    data = payload.get("data", {})
    pix_qr_code = data.get("pixQrCode", {})
    abacatepay_id = pix_qr_code.get("id")

    if not abacatepay_id:
        logger.warning("Webhook missing pixQrCode.id")
        raise HTTPException(status_code=400, detail="Missing payment ID")

    payment = await payment_service.process_webhook_payment(db, abacatepay_id)
    if not payment:
        logger.warning("Payment not found for webhook: %s", abacatepay_id)
        return {"received": True, "processed": False, "error": "Payment not found"}

    return {"received": True, "processed": True, "payment_id": str(payment.id)}
