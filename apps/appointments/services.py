"""
Booking engine. Views yahan ke functions call karte hain; rules yahin enforce hote hain.

Double-booking se bachav (2 layer):
  1. transaction.atomic + doctor row par select_for_update  -> ek doctor ki bookings serialize hoti hain.
     (SQLite mein row-lock no-op hai, par SQLite writes waise bhi serialize karta hai. Production mein PostgreSQL.)
  2. DB partial unique constraint (unique_active_slot_per_doctor) -> lock kisi wajah se chuk bhi jaye to
     duplicate insert IntegrityError se rukta hai.
Lock order hamesha: doctor -> patient -> appointment (deadlock se bachne ke liye).
"""
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.doctors.models import DoctorProfile
from apps.doctors.slots import get_available_slots
from apps.notifications.models import Notification
from apps.notifications.services import notify
from apps.patients.models import PatientProfile
from apps.payments import services as payment_services

from .models import (
    ACTIVE_STATUSES,
    CANCELLABLE_STATUSES,
    Appointment,
    AppointmentStatus,
    AppointmentStatusHistory,
)
from .rules import (
    CHECKIN_MINUTES_BEFORE,
    MAX_BOOKING_DAYS,
    MAX_RESCHEDULES,
    MIN_NOTICE_HOURS,
    PAYMENT_HOLD_MINUTES,
    REMINDER_HOURS_BEFORE,
)

S = AppointmentStatus
NOT_YOURS = "Ye appointment aapki nahi hai."

DOCTOR_TRANSITIONS = {
    S.IN_PROGRESS.value: {S.CONFIRMED.value},
    S.COMPLETED.value: {S.IN_PROGRESS.value},
    S.NO_SHOW.value: {S.CONFIRMED.value},
}
DOCTOR_ACTION_LABELS = {
    S.IN_PROGRESS.value: "Start consultation",
    S.COMPLETED.value: "Mark completed",
    S.NO_SHOW.value: "Mark no-show",
}


class BookingError(Exception):
    """User ko dikhane layak message ke saath."""


# ---------- rule checks (read-only, views bhi use karte hain) ----------

def cancel_block_reason(appt, user, now=None):
    now = now or timezone.now()
    if appt.status not in CANCELLABLE_STATUSES:
        return "Ye appointment ab cancel nahi ho sakti."
    if user.role == "patient":
        if appt.patient.user_id != user.id:
            return NOT_YOURS
        if appt.starts_at - now < timedelta(hours=MIN_NOTICE_HOURS):
            return f"Appointment se {MIN_NOTICE_HOURS} ghante pehle tak hi cancel ho sakti hai."
    elif user.role == "doctor":
        if appt.doctor.user_id != user.id:
            return NOT_YOURS
        if appt.starts_at <= now:
            return "Shuru ho chuki appointment cancel nahi ho sakti."
    else:
        return NOT_YOURS
    return None


def reschedule_block_reason(appt, user, now=None):
    now = now or timezone.now()
    if user.role != "patient" or appt.patient.user_id != user.id:
        return NOT_YOURS
    if appt.status == S.PENDING:
        return "Reschedule se pehle payment poori karo."
    if appt.status not in CANCELLABLE_STATUSES:
        return "Ye appointment ab reschedule nahi ho sakti."
    if appt.reschedule_count >= MAX_RESCHEDULES:
        return f"Ek appointment sirf {MAX_RESCHEDULES} baar reschedule ho sakti hai."
    if appt.starts_at - now < timedelta(hours=MIN_NOTICE_HOURS):
        return f"Appointment se {MIN_NOTICE_HOURS} ghante pehle tak hi reschedule ho sakti hai."
    return None


def status_block_reason(appt, user, to_status, now=None):
    now = now or timezone.now()
    if user.role != "doctor" or appt.doctor.user_id != user.id:
        return NOT_YOURS
    allowed_from = DOCTOR_TRANSITIONS.get(to_status)
    if allowed_from is None or appt.status not in allowed_from:
        return "Ye status change is appointment ke liye allowed nahi hai."
    if to_status == S.IN_PROGRESS.value and now < appt.starts_at - timedelta(minutes=CHECKIN_MINUTES_BEFORE):
        return f"Consultation appointment se {CHECKIN_MINUTES_BEFORE} minute pehle se shuru ho sakti hai."
    if to_status == S.NO_SHOW.value and now < appt.starts_at:
        return "No-show appointment time ke baad hi mark ho sakta hai."
    return None


def available_doctor_actions(appt, user, now=None):
    return [(to, label) for to, label in DOCTOR_ACTION_LABELS.items()
            if status_block_reason(appt, user, to, now) is None]


# ---------- helpers ----------

def _validate_day(day):
    today = timezone.localdate()
    if day < today:
        raise BookingError("Past date ke liye booking nahi ho sakti.")
    if day > today + timedelta(days=MAX_BOOKING_DAYS):
        raise BookingError(f"Sirf agle {MAX_BOOKING_DAYS} din ke liye booking ho sakti hai.")


def _find_slot(doctor, day, start_time):
    for slot in get_available_slots(doctor, day):     # fresh DB state: booked/blocked/past slots already hate hue
        if slot[0] == start_time:
            return slot
    raise BookingError("Ye slot ab available nahi hai. Doosra slot chuno.")


def _patient_conflict(patient_id, day, start, end, exclude_pk=None):
    qs = Appointment.objects.filter(
        patient_id=patient_id, appointment_date=day, status__in=ACTIVE_STATUSES,
        start_time__lt=end, end_time__gt=start,
    )
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return qs.exists()


def _log(appt, from_status, to_status, user, note=""):
    AppointmentStatusHistory.objects.create(
        appointment=appt, from_status=from_status, to_status=to_status, changed_by=user, note=note[:300])


# ---------- actions ----------

def book_appointment(*, patient, doctor, day, start_time, reason=""):
    _validate_day(day)
    with transaction.atomic():
        doc = DoctorProfile.objects.select_for_update().get(pk=doctor.pk)
        PatientProfile.objects.select_for_update().get(pk=patient.pk)
        if not (doc.is_verified and doc.user.is_active):
            raise BookingError("Ye doctor abhi available nahi hai.")
        expire_stale_holds(doctor=doc, day=day)      # expired unpaid holds hatao, warna unique constraint rokega
        start, end = _find_slot(doc, day, start_time)
        if _patient_conflict(patient.pk, day, start, end):
            raise BookingError("Is time par aapki doosri appointment pehle se hai.")
        # Fee > 0 => PENDING (slot payment_due_at tak hold), payment ke baad CONFIRMED. Free => seedha CONFIRMED.
        status = S.PENDING if doc.consultation_fee > 0 else S.CONFIRMED
        due = timezone.now() + timedelta(minutes=PAYMENT_HOLD_MINUTES) if status == S.PENDING else None
        try:
            with transaction.atomic():   # savepoint: IntegrityError ke baad outer transaction safe rahe
                appt = Appointment.objects.create(
                    patient=patient, doctor=doc, appointment_date=day, start_time=start, end_time=end,
                    status=status, payment_due_at=due, consultation_fee=doc.consultation_fee, reason=reason.strip()[:500],
                )
        except IntegrityError:
            raise BookingError("Ye slot abhi kisi aur ne book kar liya. Doosra slot chuno.")
        _log(appt, "", status, patient.user, "Booked - payment pending" if status == S.PENDING else "Booked")
        if status == S.CONFIRMED:
            _notify_booking_confirmed(appt)
    return appt


def _notify_booking_confirmed(appt):
    when = f"{appt.appointment_date:%d %b %Y}, {appt.start_time:%I:%M %p}"
    notify(appt.patient.user, Notification.Type.APPOINTMENT_CONFIRMED, "Appointment confirmed",
           f"Dr. {appt.doctor.user.get_full_name() or appt.doctor.user.email} · {when}", appointment=appt)
    notify(appt.doctor.user, Notification.Type.NEW_APPOINTMENT, "New appointment booked",
           f"{appt.patient.user.get_full_name() or appt.patient.user.email} · {when}", appointment=appt)


def cancel_appointment(appointment, *, by_user, reason=""):
    with transaction.atomic():
        appt = Appointment.objects.select_for_update().get(pk=appointment.pk)
        blocked = cancel_block_reason(appt, by_user)
        if blocked:
            raise BookingError(blocked)
        old = appt.status
        appt.status = S.CANCELLED
        appt.cancelled_by = by_user.role
        appt.cancel_reason = reason.strip()[:300]
        appt.save(update_fields=["status", "cancelled_by", "cancel_reason", "updated_at"])
        _log(appt, old, S.CANCELLED, by_user, f"Cancelled by {by_user.role}. {appt.cancel_reason}")
        payment_services.close_open_payments(appt, "Appointment cancelled")
        payment_services.request_refund_for_appointment(appt, initiated_by=by_user, reason=f"Appointment cancelled by {by_user.role}")
        other = appt.doctor.user if by_user.role == "patient" else appt.patient.user
        notify(other, Notification.Type.APPOINTMENT_CANCELLED, "Appointment cancelled",
               f"{appt.appointment_date:%d %b %Y}, {appt.start_time:%I:%M %p} ki appointment cancel ho gayi.", appointment=appt)
    return appt


def reschedule_appointment(appointment, *, by_user, new_day, new_start):
    _validate_day(new_day)
    with transaction.atomic():
        doc = DoctorProfile.objects.select_for_update().get(pk=appointment.doctor_id)
        PatientProfile.objects.select_for_update().get(pk=appointment.patient_id)
        appt = Appointment.objects.select_for_update().get(pk=appointment.pk)
        blocked = reschedule_block_reason(appt, by_user)
        if blocked:
            raise BookingError(blocked)
        start, end = _find_slot(doc, new_day, new_start)
        if _patient_conflict(appt.patient_id, new_day, start, end, exclude_pk=appt.pk):
            raise BookingError("Is time par aapki doosri appointment pehle se hai.")
        old = f"{appt.appointment_date} {appt.start_time:%H:%M}"
        appt.appointment_date, appt.start_time, appt.end_time = new_day, start, end
        appt.reschedule_count += 1
        try:
            with transaction.atomic():
                appt.save(update_fields=["appointment_date", "start_time", "end_time", "reschedule_count", "updated_at"])
        except IntegrityError:
            raise BookingError("Ye slot abhi kisi aur ne book kar liya. Doosra slot chuno.")
        _log(appt, appt.status, appt.status, by_user, f"Rescheduled from {old} to {new_day} {start:%H:%M}")
        notify(appt.doctor.user, Notification.Type.APPOINTMENT_RESCHEDULED, "Appointment rescheduled",
               f"{appt.patient.user.get_full_name() or appt.patient.user.email} · naya time: {new_day:%d %b}, {start:%I:%M %p}",
               appointment=appt)
    return appt


def update_status_by_doctor(appointment, *, by_user, to_status):
    with transaction.atomic():
        appt = Appointment.objects.select_for_update().get(pk=appointment.pk)
        blocked = status_block_reason(appt, by_user, to_status)
        if blocked:
            raise BookingError(blocked)
        old = appt.status
        appt.status = to_status
        appt.save(update_fields=["status", "updated_at"])
        _log(appt, old, to_status, by_user)
    return appt


def expire_stale_holds(*, doctor=None, day=None):
    """Payment window nikal chuki PENDING appointments ko EXPIRED karo (slot free). Booking se pehle aur command se chalta hai."""
    qs = Appointment.objects.filter(status=S.PENDING, payment_due_at__lt=timezone.now())
    if doctor is not None:
        qs = qs.filter(doctor=doctor)
    if day is not None:
        qs = qs.filter(appointment_date=day)
    count = 0
    with transaction.atomic():
        for appt in qs.select_for_update():
            appt.status = S.EXPIRED
            appt.save(update_fields=["status", "updated_at"])
            payment_services.close_open_payments(appt, "Payment window expired")
            _log(appt, S.PENDING, S.EXPIRED, None, "Payment window expired")
            count += 1
    return count


def send_due_reminders():
    """CONFIRMED appointments jo REMINDER_HOURS_BEFORE ke andar shuru hone wali hain, unhe ek hi baar reminder."""
    now = timezone.now()
    cutoff = now + timedelta(hours=REMINDER_HOURS_BEFORE)
    candidates = (
        Appointment.objects.filter(status=S.CONFIRMED, reminder_sent_at__isnull=True,
                                    appointment_date__range=[now.date(), cutoff.date()])
        .select_related("patient__user", "doctor__user")
    )
    sent = 0
    for appt in candidates:
        if not (now < appt.starts_at <= cutoff):
            continue
        claimed = Appointment.objects.filter(pk=appt.pk, reminder_sent_at__isnull=True).update(reminder_sent_at=now)
        if not claimed:            # ek aur worker/run pehle claim kar chuka
            continue
        notify(appt.patient.user, Notification.Type.APPOINTMENT_REMINDER, "Appointment reminder",
               f"Dr. {appt.doctor.user.get_full_name() or appt.doctor.user.email} · "
               f"{appt.appointment_date:%d %b}, {appt.start_time:%I:%M %p}", appointment=appt)
        sent += 1
    return sent
