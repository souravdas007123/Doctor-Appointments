from datetime import date, time, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.decorators import role_required
from apps.doctors.models import DoctorProfile
from apps.doctors.slots import get_available_slots

from . import services
from .models import ACTIVE_STATUSES, CANCELLABLE_STATUSES, Appointment, AppointmentStatus
from .rules import MAX_BOOKING_DAYS, PAYMENT_HOLD_MINUTES

RELATED = ("doctor__user", "doctor__specialization", "patient__user")


def _own_appointment(request, pk):
    """Object-level access: patient sirf apni, doctor sirf apne patients ki appointment dekh sakta hai."""
    qs = Appointment.objects.select_related(*RELATED)
    if request.user.role == "patient":
        return get_object_or_404(qs, pk=pk, patient__user=request.user)
    if request.user.role == "doctor":
        return get_object_or_404(qs, pk=pk, doctor__user=request.user)
    raise PermissionDenied


def _parse_day_and_start(data):
    try:
        return date.fromisoformat(data.get("date", "")), time.fromisoformat(data.get("start", ""))
    except ValueError:
        return None, None


def _pick_day(doctor, raw, default):
    today = timezone.localdate()
    last = today + timedelta(days=MAX_BOOKING_DAYS)
    day, error = default, None
    if raw:
        try:
            day = date.fromisoformat(raw)
        except ValueError:
            error = "Date galat hai. Dobara select karo."
    if day < today:
        error, day = "Past date select nahi ho sakti.", today
    slots = []
    if day > last:
        error = f"Sirf agle {MAX_BOOKING_DAYS} din ke slots dikh sakte hain."
    else:
        slots = get_available_slots(doctor, day)
    return {"day": day, "error": error, "slots": slots, "min_date": today.isoformat(), "max_date": last.isoformat()}


@require_POST
@role_required("patient")
def book(request):
    try:
        doctor_id = int(request.POST.get("doctor", ""))
    except ValueError:
        raise Http404
    doctor = get_object_or_404(DoctorProfile, pk=doctor_id, is_verified=True, user__is_active=True)
    back = reverse("patients:doctor_detail", args=[doctor.pk])
    day, start = _parse_day_and_start(request.POST)
    if day is None or start is None:
        messages.error(request, "Date aur slot dono select karo.")
        return redirect(back)
    try:
        appt = services.book_appointment(
            patient=request.user.patient_profile, doctor=doctor, day=day, start_time=start,
            reason=request.POST.get("reason", ""),
        )
    except services.BookingError as exc:
        messages.error(request, str(exc))
        return redirect(f"{back}?date={day.isoformat()}")
    if appt.status == AppointmentStatus.PENDING:
        messages.info(request, f"Slot aapke liye hold hai. {PAYMENT_HOLD_MINUTES} minute mein payment poori karo.")
        return redirect("payments:checkout", appointment_id=appt.pk)
    messages.success(request, f"Appointment confirm ho gayi. Reference: {appt.reference}")
    return redirect("appointments:detail", pk=appt.pk)


@role_required("patient")
def my_appointments(request):
    today = timezone.localdate()
    scope = "past" if request.GET.get("scope") == "past" else "upcoming"
    qs = Appointment.objects.filter(patient__user=request.user).select_related(*RELATED)
    if scope == "past":
        qs = qs.exclude(status__in=ACTIVE_STATUSES, appointment_date__gte=today).order_by("-appointment_date", "-start_time")
    else:
        qs = qs.filter(status__in=ACTIVE_STATUSES, appointment_date__gte=today).order_by("appointment_date", "start_time")
    return render(request, "appointments/list.html", {"appointments": qs[:100], "scope": scope})


@login_required
def detail(request, pk):
    appt = _own_appointment(request, pk)
    now = timezone.now()
    cancel_reason = services.cancel_block_reason(appt, request.user, now)
    resched_reason = services.reschedule_block_reason(appt, request.user, now) if request.user.role == "patient" else "n/a"
    payment = appt.payments.order_by("-created_at").first()
    ctx = {
        "appt": appt,
        "payment": payment,
        "refund": payment.refunds.order_by("-created_at").first() if payment else None,
        "can_pay": (request.user.role == "patient" and appt.status == AppointmentStatus.PENDING
                    and appt.payment_due_at is not None and appt.payment_due_at > now),
        "history": appt.history.select_related("changed_by"),
        "can_cancel": cancel_reason is None,
        "can_reschedule": resched_reason is None,
        "cancel_hint": cancel_reason if appt.status in CANCELLABLE_STATUSES else None,
        "resched_hint": resched_reason if appt.status in CANCELLABLE_STATUSES and resched_reason != "n/a" else None,
        "doctor_actions": services.available_doctor_actions(appt, request.user, now) if request.user.role == "doctor" else [],
    }
    return render(request, "appointments/detail.html", ctx)


@require_POST
@login_required
def cancel(request, pk):
    appt = _own_appointment(request, pk)
    try:
        services.cancel_appointment(appt, by_user=request.user, reason=request.POST.get("reason", ""))
        messages.success(request, "Appointment cancel ho gayi.")
    except services.BookingError as exc:
        messages.error(request, str(exc))
    return redirect("appointments:detail", pk=pk)


@role_required("patient")
def reschedule(request, pk):
    appt = get_object_or_404(Appointment.objects.select_related(*RELATED), pk=pk, patient__user=request.user)
    blocked = services.reschedule_block_reason(appt, request.user)
    if blocked:
        messages.error(request, blocked)
        return redirect("appointments:detail", pk=pk)
    if request.method == "POST":
        day, start = _parse_day_and_start(request.POST)
        if day is None or start is None:
            messages.error(request, "Date aur slot dono select karo.")
            return redirect("appointments:reschedule", pk=pk)
        try:
            services.reschedule_appointment(appt, by_user=request.user, new_day=day, new_start=start)
        except services.BookingError as exc:
            messages.error(request, str(exc))
            return redirect(f"{reverse('appointments:reschedule', args=[pk])}?date={day.isoformat()}")
        messages.success(request, "Appointment reschedule ho gayi.")
        return redirect("appointments:detail", pk=pk)
    ctx = _pick_day(appt.doctor, request.GET.get("date"), max(appt.appointment_date, timezone.localdate()))
    ctx["appt"] = appt
    return render(request, "appointments/reschedule.html", ctx)


@role_required("doctor")
def doctor_appointments(request):
    today = timezone.localdate()
    scope = request.GET.get("scope")
    qs = Appointment.objects.filter(doctor__user=request.user).select_related("patient__user")
    if scope == "upcoming":
        qs = qs.filter(appointment_date__gt=today, status__in=ACTIVE_STATUSES).order_by("appointment_date", "start_time")
    elif scope == "past":
        qs = qs.filter(appointment_date__lt=today).order_by("-appointment_date", "-start_time")
    else:
        scope = "today"
        qs = qs.filter(appointment_date=today).order_by("start_time")
    return render(request, "appointments/doctor_list.html", {"appointments": qs[:200], "scope": scope})


@require_POST
@role_required("doctor")
def update_status(request, pk):
    appt = get_object_or_404(Appointment.objects.select_related("doctor__user"), pk=pk, doctor__user=request.user)
    try:
        services.update_status_by_doctor(appt, by_user=request.user, to_status=request.POST.get("to", ""))
        messages.success(request, "Status update ho gaya.")
    except services.BookingError as exc:
        messages.error(request, str(exc))
    return redirect("appointments:detail", pk=pk)
