"""
Payment logic. Lock order (deadlock se bachne ke liye): appointment -> payment -> refund.
Gateway network calls kabhi DB lock/transaction ke andar nahi hote (process_refund on_commit se chalta hai).
"""
import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.appointments.models import Appointment, AppointmentStatus, AppointmentStatusHistory
from apps.notifications.models import Notification
from apps.notifications.services import notify

from .gateway import PaymentConfigError, RazorpayError, get_gateway, to_paise
from .models import Payment, Refund

S = AppointmentStatus
logger = logging.getLogger(__name__)


class PaymentError(Exception):
    """User/log ke liye samajhne layak message."""


class UnknownOrder(PaymentError):
    pass


class AmountMismatch(PaymentError):
    pass


def _log(appt, from_status, to_status, note):
    AppointmentStatusHistory.objects.create(appointment=appt, from_status=from_status, to_status=to_status, changed_by=None, note=note[:300])


# ---------- order ----------

def get_or_create_order(appointment, gateway=None):
    appt = Appointment.objects.get(pk=appointment.pk)
    if appt.status != S.PENDING or not appt.payment_due_at or appt.payment_due_at <= timezone.now():
        raise PaymentError("Is appointment ki payment window band ho chuki hai. Dobara book karo.")
    existing = appt.payments.filter(status=Payment.Status.CREATED).first()
    if existing:                                    # retry same order par (Razorpay modal mein retry allowed hai)
        return existing
    gateway = gateway or get_gateway()
    try:
        order = gateway.create_order(to_paise(appt.consultation_fee), receipt=appt.reference, notes={"appointment_id": str(appt.pk)})
    except RazorpayError as exc:
        logger.warning("Order create failed for appointment %s: %s", appt.pk, exc)
        raise PaymentError("Payment shuru nahi ho paya. Thodi der baad try karo.") from exc
    return Payment.objects.create(appointment=appt, patient_id=appt.patient_id, amount=appt.consultation_fee, gateway_order_id=order["id"])


# ---------- success ----------

def _try_reconfirm_expired(appt):
    """Hold expire hone ke baad payment aayi: slot abhi bhi free ho to appointment wapas confirm."""
    if appt.starts_at <= timezone.now():
        return False
    try:
        with transaction.atomic():                  # partial unique constraint slot conflict pakad leta hai
            appt.status = S.CONFIRMED
            appt.payment_due_at = None
            appt.save(update_fields=["status", "payment_due_at", "updated_at"])
    except IntegrityError:
        appt.status = S.EXPIRED
        return False
    return True


def mark_paid(order_id, gateway_payment_id, amount_paise=None):
    """Idempotent. Webhook aur browser callback dono isse call kar sakte hain."""
    try:
        appt_id = Payment.objects.values_list("appointment_id", flat=True).get(gateway_order_id=order_id)
    except Payment.DoesNotExist:
        raise UnknownOrder(f"Unknown order {order_id}")
    with transaction.atomic():
        appt = Appointment.objects.select_for_update().get(pk=appt_id)
        payment = Payment.objects.select_for_update().get(gateway_order_id=order_id)
        if payment.status in (Payment.Status.PAID, Payment.Status.REFUND_PENDING, Payment.Status.REFUNDED):
            return payment
        if amount_paise is not None and int(amount_paise) != to_paise(payment.amount):
            raise AmountMismatch(f"Amount mismatch for order {order_id}")
        duplicate = appt.payments.filter(status=Payment.Status.PAID).exclude(pk=payment.pk).exists()
        payment.gateway_payment_id = gateway_payment_id
        payment.status = Payment.Status.PAID
        payment.paid_at = timezone.now()
        payment.failure_reason = ""
        payment.save()
        confirmed = False
        if not duplicate:
            if appt.status == S.PENDING:
                appt.status = S.CONFIRMED
                appt.payment_due_at = None
                appt.save(update_fields=["status", "payment_due_at", "updated_at"])
                confirmed = True
                _log(appt, S.PENDING, S.CONFIRMED, "Payment received")
            elif appt.status == S.EXPIRED and _try_reconfirm_expired(appt):
                confirmed = True
                _log(appt, S.EXPIRED, S.CONFIRMED, "Payment received after hold expired; slot was still free")
        if confirmed:
            when = f"{appt.appointment_date:%d %b %Y}, {appt.start_time:%I:%M %p}"
            notify(appt.patient.user, Notification.Type.PAYMENT_SUCCESSFUL, "Payment successful",
                   f"₹{payment.amount} · {when}", appointment=appt)
            notify(appt.doctor.user, Notification.Type.PAYMENT_RECEIVED, "Payment received",
                   f"{appt.patient.user.get_full_name() or appt.patient.user.email} · ₹{payment.amount}", appointment=appt)
        if not confirmed:
            reason = "Duplicate payment" if duplicate else f"Appointment {appt.status}; slot confirm nahi ho saka"
            request_refund(payment, reason=reason)
            _log(appt, appt.status, appt.status, f"Payment received but not applied ({reason}); refund initiated")
    return payment


def record_attempt_failure(order_id, reason):
    """payment.failed: status CREATED hi rehta hai (Razorpay same order par retry allow karta hai)."""
    Payment.objects.filter(gateway_order_id=order_id, status=Payment.Status.CREATED).update(
        failure_reason=(reason or "Payment failed")[:300], updated_at=timezone.now())


def close_open_payments(appt, reason):
    """Cancel/expiry par unpaid orders band. Late payment aayi to mark_paid use refund kar dega."""
    Payment.objects.filter(appointment=appt, status=Payment.Status.CREATED).update(
        status=Payment.Status.FAILED, failure_reason=reason[:300], updated_at=timezone.now())


# ---------- refunds ----------

def request_refund(payment, *, reason, initiated_by=None):
    refund = Refund.objects.create(payment=payment, amount=payment.amount, reason=reason[:200], initiated_by=initiated_by)
    payment.status = Payment.Status.REFUND_PENDING
    payment.save(update_fields=["status", "updated_at"])
    transaction.on_commit(lambda: process_refund(refund.pk), robust=True)   # commit ke baad hi gateway call
    return refund


def request_refund_for_appointment(appt, *, initiated_by, reason):
    """Caller ne appointment row lock ki honi chahiye."""
    payment = appt.payments.select_for_update().filter(status=Payment.Status.PAID).first()
    if payment:
        return request_refund(payment, reason=reason, initiated_by=initiated_by)
    return None


def _mark_refund_processed(refund):
    now = timezone.now()
    refund.status = Refund.Status.PROCESSED
    refund.processed_at = now
    refund.failure_reason = ""
    refund.save(update_fields=["gateway_refund_id", "status", "processed_at", "failure_reason"])
    Payment.objects.filter(pk=refund.payment_id).update(status=Payment.Status.REFUNDED, updated_at=now)


def process_refund(refund_id, gateway=None):
    """Gateway ko refund bhejta hai. Fail ho to PENDING rehta hai; process_pending_refunds command retry karta hai."""
    refund = Refund.objects.select_related("payment").get(pk=refund_id)
    if refund.status != Refund.Status.PENDING or refund.gateway_refund_id:
        return refund
    try:
        gateway = gateway or get_gateway()
        data = gateway.refund(
            refund.payment.gateway_payment_id, to_paise(refund.amount),
            notes={"refund_id": str(refund.pk)}, idempotency_key=f"careslot-refund-{refund.pk}",   # retry par double-refund nahi
        )
    except (RazorpayError, PaymentConfigError) as exc:
        logger.warning("Refund %s failed: %s", refund.pk, exc)
        Refund.objects.filter(pk=refund.pk).update(failure_reason=str(exc)[:300])
        return refund
    with transaction.atomic():
        refund = Refund.objects.select_for_update().get(pk=refund_id)
        if refund.status == Refund.Status.PROCESSED:        # webhook pehle pahunch gaya
            return refund
        refund.gateway_refund_id = data.get("id")
        if data.get("status") == "processed":
            _mark_refund_processed(refund)
        else:
            refund.failure_reason = ""
            refund.save(update_fields=["gateway_refund_id", "failure_reason"])
    return refund


def apply_refund_webhook(entity, processed):
    with transaction.atomic():
        refund = Refund.objects.select_for_update().filter(gateway_refund_id=entity.get("id")).first()
        if refund is None:                                   # webhook hamare DB update se pehle aa gaya
            notes = entity.get("notes")
            rid = notes.get("refund_id") if isinstance(notes, dict) else None
            if rid and str(rid).isdigit():
                refund = Refund.objects.select_for_update().filter(pk=int(rid)).first()
        if refund is None:
            return
        refund.gateway_refund_id = refund.gateway_refund_id or entity.get("id")
        if processed:
            if refund.status != Refund.Status.PROCESSED:
                _mark_refund_processed(refund)
        else:
            refund.status = Refund.Status.FAILED
            refund.failure_reason = "Gateway ne refund fail bataya. Razorpay dashboard mein check karo."
            refund.save(update_fields=["gateway_refund_id", "status", "failure_reason"])


# ---------- webhook dispatch ----------

def handle_webhook_event(event_type, payload):
    try:
        entities = payload["payload"]
        if event_type in ("payment.captured", "order.paid"):
            ent = entities["payment"]["entity"]
            mark_paid(ent["order_id"], ent["id"], amount_paise=ent.get("amount"))
        elif event_type == "payment.failed":
            ent = entities["payment"]["entity"]
            record_attempt_failure(ent.get("order_id"), ent.get("error_description"))
        elif event_type in ("refund.processed", "refund.failed"):
            apply_refund_webhook(entities["refund"]["entity"], processed=(event_type == "refund.processed"))
    except (KeyError, TypeError) as exc:
        raise PaymentError(f"Malformed {event_type} payload: {exc!r}")
