import hashlib
import hmac
import unittest
from decimal import Decimal

from .gateway import to_paise
from .signatures import verify_payment_signature, verify_webhook_signature


class WebhookSignatureTests(unittest.TestCase):
    def test_known_hmac_sha256_vector(self):
        # Standard HMAC-SHA256 test vector (key="key")
        sig = "f7bc83f430538424b13298e6aa6fb143ef4d59a14946175997479dbc2d1a3cd8"
        self.assertTrue(verify_webhook_signature(b"The quick brown fox jumps over the lazy dog", sig, "key"))

    def test_wrong_body_or_secret_or_missing(self):
        sig = hmac.new(b"whsec", b'{"a":1}', hashlib.sha256).hexdigest()
        self.assertTrue(verify_webhook_signature(b'{"a":1}', sig, "whsec"))
        self.assertFalse(verify_webhook_signature(b'{"a":2}', sig, "whsec"))
        self.assertFalse(verify_webhook_signature(b'{"a":1}', sig, "other"))
        self.assertFalse(verify_webhook_signature(b'{"a":1}', "", "whsec"))
        self.assertFalse(verify_webhook_signature(b'{"a":1}', sig, ""))

    def test_non_ascii_signature_does_not_crash(self):
        self.assertFalse(verify_webhook_signature(b"x", "सिग्नेचर", "s"))


class PaymentSignatureTests(unittest.TestCase):
    def sign(self, order, pay, secret="sec"):
        return hmac.new(secret.encode(), f"{order}|{pay}".encode(), hashlib.sha256).hexdigest()

    def test_valid_and_tampered(self):
        sig = self.sign("order_1", "pay_1")
        self.assertTrue(verify_payment_signature("order_1", "pay_1", sig, "sec"))
        self.assertFalse(verify_payment_signature("order_1", "pay_2", sig, "sec"))    # payment id badla
        self.assertFalse(verify_payment_signature("order_2", "pay_1", sig, "sec"))    # order id badla
        self.assertFalse(verify_payment_signature("order_1", "pay_1", sig, "wrong"))

    def test_missing_parts(self):
        self.assertFalse(verify_payment_signature("", "pay_1", "x", "sec"))
        self.assertFalse(verify_payment_signature("order_1", "pay_1", "", "sec"))
        self.assertFalse(verify_payment_signature("order_1", "pay_1", "x", ""))


class ToPaiseTests(unittest.TestCase):
    def test_conversion(self):
        self.assertEqual(to_paise(Decimal("800.00")), 80000)
        self.assertEqual(to_paise(Decimal("99.99")), 9999)
        self.assertEqual(to_paise(Decimal("0.5")), 50)
        self.assertEqual(to_paise("1500"), 150000)
