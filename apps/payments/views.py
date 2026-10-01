import hashlib
import json
import logging

from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.accounts.decorators import role_required
from apps.appointments.models import Appointment, AppointmentStatus

from . import services
from .gateway import PaymentConfigError, to_paise
from .models import Payment, WebhookEvent
from .signatures import verify_payment_signature, verify_webhook_signature

logger = logging.getLogger(__name__)


@role_required("patient")
def checkout(request, appointment_id):
    appt = get_object_or_404(
        Appointment.objects.select_related("doctor__user"), pk=appointment_id, patient__user=request.user)
    back = redirect("appointments:detail", pk=appt.pk)
    if appt.status != AppointmentStatus.PENDING:
        messages.info(request, "Is appointment ke liye payment pending nahi hai.")
        return back
    if not settings.RAZORPAY_KEY_ID:
        messages.error(request, "Online payment abhi configure nahi hai.")
        return back
    try:
        payment = services.get_or_create_order(appt)
    except (services.PaymentError, PaymentConfigError) as exc:
        messages.error(request, str(exc))
        return back
    user = request.user
    checkout_cfg = {
        "key": settings.RAZORPAY_KEY_ID, "amount": to_paise(payment.amount), "currency": "INR",
        "order_id": payment.gateway_order_id, "name": "CareSlot",
        "description": f"Consultation with Dr. {appt.doctor.user.get_full_name() or appt.doctor.user.email}",
        "prefill": {"name": user.get_full_name(), "email": user.email, "contact": user.phone},
        "theme": {"color": "#0f766e"},
    }
    return render(request, "payments/checkout.html", {"appt": appt, "payment": payment, "checkout": checkout_cfg})


@require_POST
@role_required("patient")
def verify(request):
    """Browser callback. Signature verify hone par hi payment maani jaati hai."""
    order_id = request.POST.get("razorpay_order_id", "")
    payment_id = request.POST.get("razorpay_payment_id", "")
    signature = request.POST.get("razorpay_signature", "")
    payment = get_object_or_404(Payment, gateway_order_id=order_id, patient__user=request.user)
    back = redirect("appointments:detail", pk=payment.appointment_id)
    if not verify_payment_signature(order_id, payment_id, signature, settings.RAZORPAY_KEY_SECRET):
        messages.error(request, "Payment verify nahi ho paya. Agar paisa kata hai to kuch der baad yahi page check karo; "
                                "confirm na ho to support se sampark karo.")
        return back
    try:
        services.mark_paid(order_id, payment_id)
    except services.PaymentError:
        messages.error(request, "Payment record karte waqt dikkat aayi. Support se sampark karo.")
        return back
    appt = Appointment.objects.get(pk=payment.appointment_id)
    if appt.status == AppointmentStatus.CONFIRMED:
        messages.success(request, f"Payment mil gayi. Appointment confirm hai: {appt.reference}")
    else:
        messages.warning(request, "Payment mil gayi, lekin slot ab available nahi tha. Poora refund shuru kar diya gaya hai.")
    return back


@csrf_exempt
@require_POST
def webhook(request):
    body = request.body                                   # signature RAW body par hota hai
    if not verify_webhook_signature(body, request.headers.get("X-Razorpay-Signature", ""), settings.RAZORPAY_WEBHOOK_SECRET):
        return HttpResponse(status=400)
    try:
        payload = json.loads(body)
        event_type = str(payload.get("event", ""))
    except (ValueError, AttributeError):
        return HttpResponse(status=400)
    event_id = request.headers.get("X-Razorpay-Event-Id") or hashlib.sha256(body).hexdigest()
    with transaction.atomic():
        event, created = WebhookEvent.objects.get_or_create(event_id=event_id, defaults={"event_type": event_type[:60]})
        if not created and event.processed:
            return HttpResponse(status=200)               # duplicate delivery
        try:
            services.handle_webhook_event(event_type, payload)
        except services.PaymentError as exc:              # unknown order / amount mismatch: log karo, retry mat karwao
            logger.warning("Webhook %s ignored: %s", event_type, exc)
        event.processed = True
        event.save(update_fields=["processed"])
    return HttpResponse(status=200)                       # unexpected error => 500 => Razorpay retry karega


@role_required("patient")
def my_payments(request):
    payments = (Payment.objects.filter(patient__user=request.user)
                .select_related("appointment__doctor__user").prefetch_related("refunds")[:100])
    return render(request, "payments/list.html", {"payments": payments})
