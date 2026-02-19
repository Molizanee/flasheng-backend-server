import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.user import Payment, PaymentStatus, User

logger = logging.getLogger(__name__)


class PaymentService:
    def __init__(self):
        self.settings = get_settings()
        self._client = None

    @property
    def client(self):
        if self._client is None:
            import abacatepay

            self._client = abacatepay.AbacatePay(self.settings.abacatepay_api_key)
        return self._client

    async def get_or_create_user(self, db: AsyncSession, user_id: str) -> User:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            user = User(id=user_id, credits=0)
            db.add(user)
            await db.commit()
            await db.refresh(user)
        return user

    async def get_user_credits(self, db: AsyncSession, user_id: str) -> int:
        user = await self.get_or_create_user(db, user_id)
        return user.credits

    async def create_pix_payment(
        self,
        db: AsyncSession,
        user_id: str,
        amount_cents: int,
    ) -> Payment:
        credits = amount_cents // 1000
        description = f"{credits} credit(s) for Flash Resume"

        data = {
            "amount": amount_cents,
            "description": description[:37],
            "expires_in": 3600,
        }
        pix_data = self.client.pixQrCode.create(data=data)
        print(pix_data)
        expires_at = None
        if hasattr(pix_data, "expires_at") and pix_data.expires_at:
            try:
                expires_at = datetime.fromisoformat(
                    pix_data.expires_at.replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                pass

        payment = Payment(
            user_id=user_id,
            abacatepay_id=pix_data.id,
            amount_cents=amount_cents,
            credits_purchased=credits,
            status=PaymentStatus.PENDING,
            br_code=pix_data.brcode,
            br_code_base64=pix_data.brcode_base64,
            expires_at=expires_at,
        )

        db.add(payment)
        await db.commit()
        await db.refresh(payment)

        logger.info(
            "Created payment %s for user %s: %d cents = %d credits",
            payment.id,
            user_id,
            amount_cents,
            credits,
        )

        if self.settings.dev:
            await self.simulate_payment(db, pix_data.id)

        return payment

    async def check_payment_status(
        self,
        db: AsyncSession,
        payment_id: str,
    ) -> Payment | None:
        result = await db.execute(select(Payment).where(Payment.id == payment_id))
        payment = result.scalar_one_or_none()
        if not payment:
            return None

        if payment.status == PaymentStatus.PAID:
            return payment

        status_data = self.client.pixQrCode.check(id=payment.abacatepay_id)
        new_status = PaymentStatus(status_data.status)

        if new_status != payment.status:
            payment.status = new_status
            if new_status == PaymentStatus.PAID:
                await self._add_credits_for_payment(db, payment)
            await db.commit()
            await db.refresh(payment)

        return payment

    async def process_webhook_payment(
        self,
        db: AsyncSession,
        abacatepay_id: str,
    ) -> Payment | None:
        result = await db.execute(
            select(Payment).where(Payment.abacatepay_id == abacatepay_id)
        )
        payment = result.scalar_one_or_none()
        if not payment:
            logger.warning("Payment not found for abacatepay_id: %s", abacatepay_id)
            return None

        if payment.status == PaymentStatus.PAID:
            logger.info("Payment %s already processed", payment.id)
            return payment

        payment.status = PaymentStatus.PAID
        await self._add_credits_for_payment(db, payment)
        await db.commit()
        await db.refresh(payment)

        logger.info(
            "Webhook processed: Payment %s marked as PAID, added %d credits to user %s",
            payment.id,
            payment.credits_purchased,
            payment.user_id,
        )

        return payment

    async def _add_credits_for_payment(
        self,
        db: AsyncSession,
        payment: Payment,
    ) -> None:
        user = await self.get_or_create_user(db, payment.user_id)
        user.credits += payment.credits_purchased
        user.updated_at = datetime.now(timezone.utc)

    async def simulate_payment(
        self,
        db: AsyncSession,
        abacatepay_id: str,
    ) -> Payment | None:
        """Simulate a payment for testing in dev mode."""
        if not self.settings.dev:
            logger.warning("simulate_payment called but not in dev mode")
            return None

        logger.info("Simulating payment for abacatepay_id: %s", abacatepay_id)
        try:
            self.client.pixQrCode.simulate(id=abacatepay_id)
            logger.info("Payment simulation successful for: %s", abacatepay_id)
        except Exception as e:
            logger.warning("Payment simulation failed: %s", e)
            return None

        result = await db.execute(
            select(Payment).where(Payment.abacatepay_id == abacatepay_id)
        )
        payment = result.scalar_one_or_none()
        if not payment:
            logger.warning("Payment not found for abacatepay_id: %s", abacatepay_id)
            return None

        payment.status = PaymentStatus.PAID
        await self._add_credits_for_payment(db, payment)
        await db.commit()
        await db.refresh(payment)

        logger.info(
            "Dev mode: Payment %s marked as PAID, added %d credits to user %s",
            payment.id,
            payment.credits_purchased,
            payment.user_id,
        )

        return payment

    async def deduct_credit(
        self,
        db: AsyncSession,
        user_id: str,
    ) -> bool:
        user = await self.get_or_create_user(db, user_id)
        if user.credits < 1:
            return False

        user.credits -= 1
        user.updated_at = datetime.now(timezone.utc)
        await db.commit()

        logger.info(
            "Deducted 1 credit from user %s. Remaining: %d", user_id, user.credits
        )
        return True

    @staticmethod
    def verify_webhook_signature(raw_body: bytes, signature: str) -> bool:
        import hashlib
        import hmac

        public_key = get_settings().abacatepay_public_key
        if not public_key:
            logger.warning(
                "AbacatePay public key not configured, skipping signature verification"
            )
            return True

        expected_sig = hmac.new(
            public_key.encode(),
            raw_body,
            hashlib.sha256,
        ).digest()

        expected_sig_b64 = __import__("base64").b64encode(expected_sig).decode()

        return hmac.compare_digest(expected_sig_b64, signature)


payment_service = PaymentService()
