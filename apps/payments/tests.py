import hashlib
import hmac
import json
from datetime import time, timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.appointments import services as appt_services
from apps.appointments.models import Appointment, AppointmentStatus
from apps.doctors.models import DoctorAvailability, DoctorProfile
from apps.doctors.slots import get_available_slots
from apps.patients.models import PatientProfile

from . import services
from .models import Payment, Refund, WebhookEvent

S = AppointmentStatus
KEYS = dict(RAZORPAY_KEY_ID="rzp_test_x", RAZORPAY_KEY_SECRET="key_secret_test", RAZORPAY_WEBHOOK_SECRET="whsec_test")


def make_user(email, role, first="T"):
    return User.objects.create_user(username=email, email=email, password="Str0ng-pass-123", role=role, first_name=first)


class FakeGateway:
    def __init__(self):
        self.orders, self.refunds = [], []

    def create_order(self, amount_paise, receipt, notes=None):
        self.orders.append((amount_paise, receipt))
        return {"id": f"order_{len(self.orders)}", "amount": amount_paise}

    def refund(self, payment_id, amount_paise, notes=None, idempotency_key=None):
        self.refunds.append((payment_id, amount_paise, idempotency_key))
        return {"id": f"rfnd_{len(self.refunds)}", "status": "processed"}


class PaymentTestBase(TestCase):
    def setUp(self):
        self.gw = FakeGateway()
        self.day = timezone.localdate() + timedelta(days=7)
        self.doctor = DoctorProfile.objects.create(user=make_user("d@x.com", "doctor", "Doc"), is_verified=True, consultation_fee=800)
        DoctorAvailability.objects.create(doctor=self.doctor, weekday=self.day.weekday(), start_time=time(9), end_time=time(12))
        self.p1 = PatientProfile.objects.create(user=make_user("p1@x.com", "patient", "One"))
        self.p2 = PatientProfile.objects.create(user=make_user("p2@x.com", "patient", "Two"))

    def book(self, patient=None, start=time(10)):
        return appt_services.book_appointment(patient=patient or self.p1, doctor=self.doctor, day=self.day, start_time=start)

    def paid_appointment(self):
        appt = self.book()
        pay = services.get_or_create_order(appt, self.gw)
        services.mark_paid(pay.gateway_order_id, "pay_1", amount_paise=80000)
        appt.refresh_from_db()
        return appt, pay


class PendingHoldTests(PaymentTestBase):
    def test_paid_doctor_booking_is_pending_and_slot_held(self):
        appt = self.book()
        self.assertEqual(appt.status, S.PENDING)
        self.assertIsNotNone(appt.payment_due_at)
        self.assertNotIn((time(10), time(10, 30)), get_available_slots(self.doctor, self.day))

    def test_expired_hold_frees_slot_and_late_payment_is_refunded(self):
        appt = self.book()
        pay = services.get_or_create_order(appt, self.gw)
        Appointment.objects.filter(pk=appt.pk).update(payment_due_at=timezone.now() - timedelta(minutes=1))
        self.assertIn((time(10), time(10, 30)), get_available_slots(self.doctor, self.day))
        appt2 = self.book(patient=self.p2)                      # doosra patient wahi slot le leta hai
        appt.refresh_from_db(); pay.refresh_from_db()
        self.assertEqual((appt.status, pay.status), (S.EXPIRED, Payment.Status.FAILED))
        services.mark_paid(pay.gateway_order_id, "pay_late", amount_paise=80000)   # p1 ki late payment
        appt.refresh_from_db(); pay.refresh_from_db()
        self.assertEqual(appt.status, S.EXPIRED)
        self.assertEqual(pay.status, Payment.Status.REFUND_PENDING)
        self.assertEqual(Refund.objects.filter(payment=pay).count(), 1)
        self.assertEqual(appt2.status, S.PENDING)

    def test_late_payment_reconfirms_if_slot_still_free(self):
        appt = self.book()
        pay = services.get_or_create_order(appt, self.gw)
        Appointment.objects.filter(pk=appt.pk).update(payment_due_at=timezone.now() - timedelta(minutes=1))
        appt_services.expire_stale_holds()
        services.mark_paid(pay.gateway_order_id, "pay_late", amount_paise=80000)
        appt.refresh_from_db()
        self.assertEqual(appt.status, S.CONFIRMED)

    def test_cannot_reschedule_unpaid_appointment(self):
        appt = self.book()
        self.assertIsNotNone(appt_services.reschedule_block_reason(appt, self.p1.user))


class OrderAndPaymentTests(PaymentTestBase):
    def test_order_created_once_and_reused(self):
        appt = self.book()
        p_a = services.get_or_create_order(appt, self.gw)
        p_b = services.get_or_create_order(appt, self.gw)
        self.assertEqual(p_a.pk, p_b.pk)
        self.assertEqual(self.gw.orders, [(80000, appt.reference)])

    def test_order_refused_after_hold_expired(self):
        appt = self.book()
        Appointment.objects.filter(pk=appt.pk).update(payment_due_at=timezone.now() - timedelta(minutes=1))
        with self.assertRaises(services.PaymentError):
            services.get_or_create_order(appt, self.gw)

    def test_mark_paid_confirms_and_is_idempotent(self):
        appt, pay = self.paid_appointment()
        self.assertEqual(appt.status, S.CONFIRMED)
        history = appt.history.count()
        services.mark_paid(pay.gateway_order_id, "pay_1", amount_paise=80000)     # duplicate webhook/callback
        self.assertEqual(appt.history.count(), history)
        self.assertEqual(Payment.objects.get(pk=pay.pk).status, Payment.Status.PAID)

    def test_amount_mismatch_rejected(self):
        appt = self.book()
        pay = services.get_or_create_order(appt, self.gw)
        with self.assertRaises(services.AmountMismatch):
            services.mark_paid(pay.gateway_order_id, "pay_1", amount_paise=100)
        appt.refresh_from_db()
        self.assertEqual(appt.status, S.PENDING)

    def test_unknown_order(self):
        with self.assertRaises(services.UnknownOrder):
            services.mark_paid("order_nope", "pay_x")

    def test_second_payment_for_same_appointment_is_refunded(self):
        appt = self.book()
        p1 = services.get_or_create_order(appt, self.gw)
        Payment.objects.create(appointment=appt, patient=self.p1, amount=800, gateway_order_id="order_other")
        services.mark_paid(p1.gateway_order_id, "pay_1", amount_paise=80000)
        services.mark_paid("order_other", "pay_2", amount_paise=80000)
        self.assertEqual(Payment.objects.get(gateway_order_id="order_other").status, Payment.Status.REFUND_PENDING)
        self.assertEqual(Payment.objects.get(pk=p1.pk).status, Payment.Status.PAID)


class RefundTests(PaymentTestBase):
    def test_cancel_paid_appointment_creates_refund_and_processes_it(self):
        appt, pay = self.paid_appointment()
        appt_services.cancel_appointment(appt, by_user=self.p1.user)
        refund = Refund.objects.get(payment=pay)
        self.assertEqual(refund.status, Refund.Status.PENDING)
        services.process_refund(refund.pk, gateway=self.gw)
        refund.refresh_from_db(); pay.refresh_from_db()
        self.assertEqual((refund.status, pay.status), (Refund.Status.PROCESSED, Payment.Status.REFUNDED))
        self.assertEqual(self.gw.refunds, [("pay_1", 80000, f"careslot-refund-{refund.pk}")])

    def test_process_refund_is_idempotent(self):
        appt, pay = self.paid_appointment()
        appt_services.cancel_appointment(appt, by_user=self.doctor.user, reason="Emergency")
        refund = Refund.objects.get(payment=pay)
        services.process_refund(refund.pk, gateway=self.gw)
        services.process_refund(refund.pk, gateway=self.gw)
        self.assertEqual(len(self.gw.refunds), 1)

    def test_cancel_unpaid_pending_closes_order_and_late_payment_refunds(self):
        appt = self.book()
        pay = services.get_or_create_order(appt, self.gw)
        appt_services.cancel_appointment(appt, by_user=self.p1.user)
        pay.refresh_from_db()
        self.assertEqual(pay.status, Payment.Status.FAILED)
        services.mark_paid(pay.gateway_order_id, "pay_x", amount_paise=80000)
        pay.refresh_from_db()
        self.assertEqual(pay.status, Payment.Status.REFUND_PENDING)

    def test_gateway_failure_keeps_refund_pending(self):
        appt, pay = self.paid_appointment()
        appt_services.cancel_appointment(appt, by_user=self.p1.user)
        refund = Refund.objects.get(payment=pay)
        bad = mock.Mock(); bad.refund.side_effect = services.RazorpayError("down")
        services.process_refund(refund.pk, gateway=bad)
        refund.refresh_from_db()
        self.assertEqual(refund.status, Refund.Status.PENDING)
        self.assertIn("down", refund.failure_reason)

    def test_refund_processed_webhook_updates_payment(self):
        appt, pay = self.paid_appointment()
        appt_services.cancel_appointment(appt, by_user=self.p1.user)
        refund = Refund.objects.get(payment=pay)
        services.apply_refund_webhook({"id": "rfnd_w1", "notes": {"refund_id": str(refund.pk)}}, processed=True)
        refund.refresh_from_db(); pay.refresh_from_db()
        self.assertEqual((refund.status, pay.status, refund.gateway_refund_id), (Refund.Status.PROCESSED, Payment.Status.REFUNDED, "rfnd_w1"))


@override_settings(**KEYS)
class WebhookTests(PaymentTestBase):
    def signed_post(self, payload, secret="whsec_test", event_id="evt_1"):
        body = json.dumps(payload).encode()
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return self.client.post(reverse("payments:webhook"), data=body, content_type="application/json",
                                HTTP_X_RAZORPAY_SIGNATURE=sig, HTTP_X_RAZORPAY_EVENT_ID=event_id)

    def captured(self, order_id, amount=80000):
        return {"event": "payment.captured", "payload": {"payment": {"entity": {
            "id": "pay_w1", "order_id": order_id, "amount": amount, "status": "captured"}}}}

    def pending_with_order(self):
        appt = self.book()
        with mock.patch("apps.payments.services.get_gateway", return_value=self.gw):
            pay = services.get_or_create_order(appt)
        return appt, pay

    def test_bad_signature_rejected(self):
        appt, pay = self.pending_with_order()
        self.assertEqual(self.signed_post(self.captured(pay.gateway_order_id), secret="wrong").status_code, 400)
        appt.refresh_from_db()
        self.assertEqual(appt.status, S.PENDING)

    def test_captured_confirms_appointment(self):
        appt, pay = self.pending_with_order()
        self.assertEqual(self.signed_post(self.captured(pay.gateway_order_id)).status_code, 200)
        appt.refresh_from_db()
        self.assertEqual(appt.status, S.CONFIRMED)

    def test_duplicate_event_ignored(self):
        appt, pay = self.pending_with_order()
        self.signed_post(self.captured(pay.gateway_order_id), event_id="evt_dup")
        history = appt.history.count()
        self.assertEqual(self.signed_post(self.captured(pay.gateway_order_id), event_id="evt_dup").status_code, 200)
        self.assertEqual(appt.history.count(), history)
        self.assertEqual(WebhookEvent.objects.filter(event_id="evt_dup").count(), 1)

    def test_amount_mismatch_is_ignored_not_confirmed(self):
        appt, pay = self.pending_with_order()
        self.assertEqual(self.signed_post(self.captured(pay.gateway_order_id, amount=100)).status_code, 200)
        appt.refresh_from_db()
        self.assertEqual(appt.status, S.PENDING)

    def test_unknown_event_type_returns_200(self):
        self.assertEqual(self.signed_post({"event": "something.else", "payload": {}}).status_code, 200)


@override_settings(**KEYS)
class ViewTests(PaymentTestBase):
    def test_checkout_creates_order_and_renders(self):
        appt = self.book()
        self.client.force_login(self.p1.user)
        with mock.patch("apps.payments.services.get_gateway", return_value=self.gw):
            resp = self.client.get(reverse("payments:checkout", args=[appt.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "checkout-data")
        self.assertEqual(Payment.objects.filter(appointment=appt).count(), 1)

    def test_other_patient_cannot_open_checkout(self):
        appt = self.book()
        self.client.force_login(self.p2.user)
        self.assertEqual(self.client.get(reverse("payments:checkout", args=[appt.pk])).status_code, 404)

    def test_verify_with_valid_signature_confirms(self):
        appt = self.book()
        pay = services.get_or_create_order(appt, self.gw)
        sig = hmac.new(b"key_secret_test", f"{pay.gateway_order_id}|pay_v1".encode(), hashlib.sha256).hexdigest()
        self.client.force_login(self.p1.user)
        resp = self.client.post(reverse("payments:verify"), {
            "razorpay_order_id": pay.gateway_order_id, "razorpay_payment_id": "pay_v1", "razorpay_signature": sig})
        self.assertRedirects(resp, reverse("appointments:detail", args=[appt.pk]))
        appt.refresh_from_db()
        self.assertEqual(appt.status, S.CONFIRMED)

    def test_verify_with_bad_signature_does_not_confirm(self):
        appt = self.book()
        pay = services.get_or_create_order(appt, self.gw)
        self.client.force_login(self.p1.user)
        self.client.post(reverse("payments:verify"), {
            "razorpay_order_id": pay.gateway_order_id, "razorpay_payment_id": "pay_v1", "razorpay_signature": "bad"})
        appt.refresh_from_db()
        self.assertEqual(appt.status, S.PENDING)
