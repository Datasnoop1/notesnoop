"""Stripe payment router — subscriptions and donations."""

import os
import logging
from typing import Optional

import stripe
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel

from db import fetch_one, execute
from auth import get_current_user, optional_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/stripe", tags=["stripe"])

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

# Price IDs — create these in Stripe Dashboard > Products
# For now we create a checkout session with a custom price
MONTHLY_PRICE = 4900  # €49.00 in cents
PRODUCT_NAME = "Datasnoop Pro"


class CheckoutRequest(BaseModel):
    pass


class DonationRequest(BaseModel):
    amount: int = 500  # cents, default €5


@router.post("/checkout")
async def create_checkout(body: CheckoutRequest, user=Depends(get_current_user)):
    """Create a Stripe Checkout session for a Pro subscription."""
    if not stripe.api_key:
        raise HTTPException(status_code=503, detail="Stripe not configured")

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "eur",
                    "product_data": {"name": PRODUCT_NAME},
                    "unit_amount": MONTHLY_PRICE,
                    "recurring": {"interval": "month"},
                },
                "quantity": 1,
            }],
            mode="subscription",
            success_url="https://datasnoop.be/account?payment=success",
            cancel_url="https://datasnoop.be/account?payment=cancelled",
            customer_email=user.get("email"),
            metadata={"user_id": user.get("id"), "email": user.get("email")},
        )
        return {"checkout_url": session.url, "session_id": session.id}
    except Exception as e:
        logger.exception("Stripe checkout failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/donate")
async def create_donation(body: DonationRequest, user=Depends(optional_user)):
    """Create a one-time donation payment."""
    if not stripe.api_key:
        raise HTTPException(status_code=503, detail="Stripe not configured")

    amount = max(100, min(body.amount, 100000))  # €1 to €1000

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "eur",
                    "product_data": {"name": "Datasnoop — Support Us"},
                    "unit_amount": amount,
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url="https://datasnoop.be/?donated=true",
            cancel_url="https://datasnoop.be/",
            customer_email=user.get("email") if user else None,
        )
        return {"checkout_url": session.url, "session_id": session.id}
    except Exception as e:
        logger.exception("Stripe donation failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhooks (subscription events)."""
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Webhook secret not configured")

    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        logger.warning("Webhook signature failed: %s", e)
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event.get("type", "")
    data = event.get("data", {}).get("object", {})
    logger.info("Stripe webhook: %s", event_type)

    if event_type == "checkout.session.completed":
        email = data.get("customer_email") or data.get("metadata", {}).get("email")
        if email:
            execute(
                """INSERT INTO user_roles (email, role) VALUES (%s, 'pro')
                   ON CONFLICT (email) DO UPDATE SET role = 'pro'""",
                (email,),
            )
            logger.info("User %s upgraded to pro", email)

    elif event_type in ("customer.subscription.deleted", "customer.subscription.updated"):
        status = data.get("status")
        email = data.get("metadata", {}).get("email")
        if email and status in ("canceled", "unpaid", "past_due"):
            execute(
                """UPDATE user_roles SET role = 'user' WHERE email = %s AND role = 'pro'""",
                (email,),
            )
            logger.info("User %s downgraded from pro", email)

    return {"status": "ok"}


@router.get("/status")
async def subscription_status(user=Depends(get_current_user)):
    """Check if the current user has a pro subscription."""
    row = fetch_one("SELECT role FROM user_roles WHERE email = %s", (user.get("email"),))
    is_pro = row and row["role"] == "pro"
    return {"email": user.get("email"), "is_pro": is_pro, "plan": "pro" if is_pro else "free"}
