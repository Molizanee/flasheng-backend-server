import uuid

from sqlalchemy import select

from app.database import get_engine
from app.models import CreditPlan


STATIC_PLAN_IDS = {
    "starter": uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890"),
    "silver": uuid.UUID("b2c3d4e5-f6a7-8901-bcde-f12345678901"),
    "gold": uuid.UUID("c3d4e5f6-a7b8-9012-cdef-123456789012"),
}


PLANS = [
    {
        "id": STATIC_PLAN_IDS["starter"],
        "name": "Starter",
        "credits_amount": 1,
        "price_brl_cents": 1000,
    },
    {
        "id": STATIC_PLAN_IDS["silver"],
        "name": "Silver",
        "credits_amount": 2,
        "price_brl_cents": 1900,
    },
    {
        "id": STATIC_PLAN_IDS["gold"],
        "name": "Gold",
        "credits_amount": 3,
        "price_brl_cents": 2800,
    },
]


async def seed_credit_plans():
    from app.database import get_async_session

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(CreditPlan.metadata.create_all)

    session_factory = get_async_session()
    async with session_factory() as session:
        for plan_data in PLANS:
            result = await session.execute(
                select(CreditPlan).where(CreditPlan.id == plan_data["id"])
            )
            existing = result.scalar_one_or_none()

            if existing:
                existing.name = plan_data["name"]
                existing.credits_amount = plan_data["credits_amount"]
                existing.price_brl_cents = plan_data["price_brl_cents"]
                existing.is_active = True
                print(f"Updated plan: {plan_data['name']}")
            else:
                plan = CreditPlan(**plan_data)
                session.add(plan)
                print(f"Created plan: {plan_data['name']}")

        await session.commit()

    await engine.dispose()
    print("Credit plans seeded successfully!")


if __name__ == "__main__":
    import asyncio

    asyncio.run(seed_credit_plans())
