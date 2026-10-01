"""SMS client (sirf standard library). Django import sirf get_sms_gateway() mein, taaki testable rahe."""
import base64
import json
import urllib.error
import urllib.parse
import urllib.request


class SMSError(Exception):
    """Gateway ne error diya ya connect nahi hua."""


class SMSConfigError(Exception):
    """SMS provider configure nahi hai."""


class ConsoleSMSGateway:
    """Dev/test default: SMS bhejta nahi, bas console/log mein dikhata hai."""

    def send(self, to, body):
        print(f"[console-sms] to={to} body={body!r}")
        return {"sid": "console-fake", "status": "queued"}


class TwilioSMSGateway:
    BASE_URL = "https://api.twilio.com/2010-04-01"

    def __init__(self, account_sid, auth_token, from_number, base_url=None, timeout=15):
        self.account_sid, self.auth_token, self.from_number = account_sid, auth_token, from_number
        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        self.timeout = timeout

    def send(self, to, body):
        url = f"{self.base_url}/Accounts/{self.account_sid}/Messages.json"
        data = urllib.parse.urlencode({"To": to, "From": self.from_number, "Body": body}).encode()
        token = base64.b64encode(f"{self.account_sid}:{self.auth_token}".encode()).decode()
        req = urllib.request.Request(url, data=data, method="POST", headers={
            "Authorization": f"Basic {token}", "Content-Type": "application/x-www-form-urlencoded",
        })
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            try:
                message = json.loads(exc.read().decode()).get("message", f"HTTP {exc.code}")
            except Exception:
                message = f"Twilio error (HTTP {exc.code})"
            raise SMSError(message) from exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise SMSError("SMS gateway se connect nahi ho paya.") from exc


def get_sms_gateway():
    from django.conf import settings

    if settings.SMS_BACKEND == "twilio":
        if not (settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN and settings.TWILIO_FROM_NUMBER):
            raise SMSConfigError("Twilio keys configure nahi hain.")
        return TwilioSMSGateway(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN, settings.TWILIO_FROM_NUMBER)
    return ConsoleSMSGateway()
