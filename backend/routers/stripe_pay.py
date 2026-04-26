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

# Checkout success/cancel URLs are relative to the caller's origin so
# staging testers don't bounce back to prod after paying. Falls back
# to prod if the caller didn't send an Origin header (server-side job).
_DEFAULT_FRONTEND_BASE = os.getenv("FRONTEND_BASE_URL", "https://datasnoop.be").rstrip("/")

# Price IDs — create these in Stripe Dashboard > Products
# For now we create a checkout session with a custom price
MONTHLY_PRICE = 4900  # €49.00 in cents
PRODUCT_NAME = "Datasnoop Pro"


def _frontend_base(request: Request) -> str:
    """Resolve the caller's frontend origin for Stripe redirects.

    Prefers the request's Origin header (so staging users testing
    checkout land back on staging, not prod). Falls back to the env
    default. Restricted to the allowed origins we already trust for
    CORS in backend/main.py so a rogue client can't use us as an
    open Stripe-redirect pivot.
    """
    allowed = {
        "https://datasnoop.be",
        "https://www.datasnoop.be",
        "https://staging.datasnoop.be",
        "https://datasnoop.eu",
        "https://datapeak.invm.be",
    }
    origin = (request.headers.get("Origin") or "").rstrip("/")
    if origin and origin in allowed:
        return origin
    return _DEFAULT_FRONTEND_BASE


class CheckoutRequest(BaseModel):
    pass


class DonationRequest(BaseModel):
    amount: int = 500  # cents, default €5


@router.post("/checkout")
async def create_checkout(body: CheckoutRequest, request: Request, user=Depends(get_current_user)):
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
            success_url=f"{_frontend_base(request)}/account?payment=success",
            cancel_url=f"{_frontend_base(request)}/account?payment=cancelled",
            customer_email=user.get("email"),
            metadata={"user_id": user.get("id"), "email": user.get("email")},
        )
        return {"checkout_url": session.url, "session_id": session.id}
    except Exception as e:
        logger.exception("Stripe checkout failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/donate")
async def create_donation(body: DonationRequest, request: Request, user=Depends(optional_user)):
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
            success_url=f"{_frontend_base(request)}/?donated=true",
            cancel_url=f"{_frontend_base(request)}/",
            customer_email=user.get("email") if user else None,
        )
        return {"checkout_url": session.url, "session_id": session.id}
    except Exception as e:
        logger.exception("Stripe donation failed")
        raise HTTPException(status_code=500, detail="Payment processing error")


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
            _drop_tier_cache(email)
            logger.info("User %s upgraded to pro", email)

    elif event_type in ("customer.subscription.deleted", "customer.subscription.updated"):
        status = data.get("status")
        email = data.get("metadata", {}).get("email")
        if email and status in ("canceled", "unpaid", "past_due"):
            execute(
                """UPDATE user_roles SET role = 'user' WHERE email = %s AND role = 'pro'""",
                (email,),
            )
            _drop_tier_cache(email)
            logger.info("User %s downgraded from pro", email)

    return {"status": "ok"}


def _drop_tier_cache(email: str) -> None:
    """Drop the tier-role cache entry so the next request sees the new role
    immediately instead of waiting up to 60s for the TTL to lapse.

    Lazy-import keeps stripe_pay independent from main.py at module load.
    Failures are non-fatal — the cache will refresh on its own TTL.
    """
    try:
        from main import invalidate_tier_role_cache
        invalidate_tier_role_cache(email)
    except Exception:
        pass


@router.get("/status")
async def subscription_status(user=Depends(get_current_user)):
    """Check if the current user has a pro subscription."""
    row = fetch_one("SELECT role FROM user_roles WHERE email = %s", (user.get("email"),))
    is_pro = row and row["role"] == "pro"
    return {"email": user.get("email"), "is_pro": is_pro, "plan": "pro" if is_pro else "free"}
