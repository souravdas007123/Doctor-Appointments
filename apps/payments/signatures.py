"""Razorpay signature checks. Pure functions (Django ki zaroorat nahi), constant-time compare."""
import hashlib
import hmac


def _hmac_hex(secret, message):
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def _safe_equal(expected_hex, given):
    return hmac.compare_digest(expected_hex.encode(), (given or "").encode())


def verify_payment_signature(order_id, payment_id, signature, secret):
    """Checkout success ke baad: HMAC-SHA256(order_id|payment_id) with key_secret."""
    if not (secret and order_id and payment_id and signature):
        return False
    return _safe_equal(_hmac_hex(secret, f"{order_id}|{payment_id}".encode()), signature)


def verify_webhook_signature(body, signature, secret):
    """Webhook: HMAC-SHA256 of RAW request body with webhook secret (X-Razorpay-Signature)."""
    if not (secret and signature):
        return False
    return _safe_equal(_hmac_hex(secret, body), signature)
