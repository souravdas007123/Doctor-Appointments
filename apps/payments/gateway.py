"""Razorpay REST client (sirf standard library). Django import sirf get_gateway() mein, taaki testable rahe."""
import base64
import json
import urllib.error
import urllib.request
from decimal import ROUND_HALF_UP, Decimal


class RazorpayError(Exception):
    """Gateway ne error diya ya connect nahi hua."""


class PaymentConfigError(Exception):
    """Razorpay keys configure nahi hain."""


def to_paise(amount):
    return int((Decimal(amount) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class RazorpayGateway:
    BASE_URL = "https://api.razorpay.com/v1"

    def __init__(self, key_id, key_secret, base_url=None, timeout=15):
        self.key_id, self.key_secret = key_id, key_secret
        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        self.timeout = timeout

    def _post(self, path, payload, extra_headers=None):
        token = base64.b64encode(f"{self.key_id}:{self.key_secret}".encode()).decode()
        headers = {"Authorization": f"Basic {token}", "Content-Type": "application/json", **(extra_headers or {})}
        req = urllib.request.Request(f"{self.base_url}{path}", data=json.dumps(payload).encode(), method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            try:
                message = json.loads(exc.read().decode())["error"]["description"]
            except Exception:
                message = f"Gateway error (HTTP {exc.code})"
            raise RazorpayError(message) from exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise RazorpayError("Payment gateway se connect nahi ho paya.") from exc

    def create_order(self, amount_paise, receipt, notes=None):
        return self._post("/orders", {"amount": amount_paise, "currency": "INR", "receipt": receipt, "notes": notes or {}})

    def refund(self, payment_id, amount_paise, notes=None, idempotency_key=None):
        headers = {"X-Refund-Idempotency": idempotency_key} if idempotency_key else None
        return self._post(f"/payments/{payment_id}/refund", {"amount": amount_paise, "speed": "normal", "notes": notes or {}}, headers)


def get_gateway():
    from django.conf import settings

    if not (settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET):
        raise PaymentConfigError("Razorpay keys configure nahi hain.")
    return RazorpayGateway(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
