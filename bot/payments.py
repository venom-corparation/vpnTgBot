"""
YooKassa Smart Payment helper.
Creates redirect payment and returns confirmation_url.
Lazily imports yookassa SDK to avoid crash if not installed.
"""

from typing import Optional, Dict
import json
import uuid
from config import YOOKASSA_ACCOUNT_ID, YOOKASSA_SECRET_KEY, YOOKASSA_RETURN_URL, USE_YOOKASSA


def init_yookassa() -> bool:
    if not (YOOKASSA_ACCOUNT_ID and YOOKASSA_SECRET_KEY):
        return False
    try:
        from yookassa import Configuration  # type: ignore
    except ImportError:
        return False
    try:
        # Prefer new style configure; fallback to attributes if not available
        if hasattr(Configuration, "configure"):
            Configuration.configure(account_id=YOOKASSA_ACCOUNT_ID, secret_key=YOOKASSA_SECRET_KEY)
        else:
            Configuration.account_id = YOOKASSA_ACCOUNT_ID
            Configuration.secret_key = YOOKASSA_SECRET_KEY
    except Exception:
        return False
    return True


def create_redirect_payment(amount_rub: float, description: str, bot_username: str, user_id: int) -> Optional[Dict]:
    """Create payment and return dict with id and confirmation_url."""
    if not USE_YOOKASSA:
        return {"error": "YooKassa disabled in config"}
    if not init_yookassa():
        return {"error": "yookassa not configured (check YOOKASSA_ACCOUNT_ID/YOOKASSA_SECRET_KEY and SDK)"}
    try:
        from yookassa import Payment  # type: ignore
    except ImportError as e:
        return {"error": f"yookassa not installed: {e}"}
    try:
        # Base payment data
        payment_data = {
            "amount": {
                "value": f"{amount_rub:.2f}",
                "currency": "RUB",
            },
            "confirmation": {
                "type": "redirect",
                "return_url": YOOKASSA_RETURN_URL or f"https://t.me/{bot_username}",
            },
            "capture": True,
            "description": description[:128],
            "metadata": {
                "user_id": user_id
            }
        }
        
        # Add receipt for real payments (not test mode)
        if not YOOKASSA_SECRET_KEY.startswith("test_"):
            payment_data["receipt"] = {
                "customer": {
                    "email": f"user{user_id}@telegram.bot"
                },
                "items": [{
                    "description": description[:128],
                    "quantity": "1",
                    "amount": {
                        "value": f"{amount_rub:.2f}",
                        "currency": "RUB"
                    },
                    "vat_code": 1,  # НДС 20%
                    "payment_mode": "full_payment",
                    "payment_subject": "service"
                }]
            }
        
        payment = Payment.create(payment_data, uuid.uuid4())
        raw = payment.json()
        data = json.loads(raw) if isinstance(raw, str) else raw
        return {
            "id": data.get("id"),
            "status": data.get("status"),
            "confirmation_url": data.get("confirmation", {}).get("confirmation_url"),
        }
    except Exception as e:
        return {"error": str(e)}


def get_payment_status(payment_id: str) -> Optional[Dict]:
    if not init_yookassa():
        return {"error": "yookassa not configured"}
    try:
        from yookassa import Payment  # type: ignore
        p = Payment.find_one(payment_id)
        raw = p.json()
        data = json.loads(raw) if isinstance(raw, str) else raw
        return {"status": data.get("status"), "paid": bool(data.get("paid"))}
    except Exception as e:
        return {"error": str(e)}