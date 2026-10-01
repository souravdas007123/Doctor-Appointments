"""Slot generation. generate_slots() pure function hai (DB nahi chhoota), isliye easily testable."""
from datetime import date, datetime, timedelta

_DAY = date(2000, 1, 1)


def _dt(t):
    return datetime.combine(_DAY, t)


def generate_slots(windows, duration_minutes, blocks=()):
    """
    windows: [(start_time, end_time), ...]  doctor ki availability
    blocks:  [(start_time, end_time), ...]  blocked ranges; (None, None) = poora din leave
    Return:  [(slot_start, slot_end), ...]  sorted, blocks se overlap wale hataye hue
    """
    if any(b[0] is None for b in blocks):
        return []
    step = timedelta(minutes=duration_minutes)
    slots = []
    for w_start, w_end in sorted(windows):
        cur, end = _dt(w_start), _dt(w_end)
        while cur + step <= end:
            s, e = cur.time(), (cur + step).time()
            if not any(s < b_end and e > b_start for b_start, b_end in blocks):
                slots.append((s, e))
            cur += step
    return slots


def drop_past_slots(slots, day, now):
    """now = naive local datetime. Guzri hui date ke slots nahi, aaj ke shuru ho chuke slots nahi."""
    if day < now.date():
        return []
    if day == now.date():
        return [sl for sl in slots if sl[0] > now.time()]
    return slots


def get_available_slots(doctor, day):
    """Doctor ke liye given date ke slots (blocked time, leave aur booked appointments hata kar)."""
    from django.utils import timezone

    from apps.appointments.models import ACTIVE_STATUSES, Appointment, AppointmentStatus
    from .models import DoctorAvailability, DoctorBlockedSlot

    windows = list(
        DoctorAvailability.objects.filter(doctor=doctor, weekday=day.weekday())
        .values_list("start_time", "end_time")
    )
    blocks = list(
        DoctorBlockedSlot.objects.filter(doctor=doctor, date=day)
        .values_list("start_time", "end_time")
    )
    # Pehle se booked (active) appointments bhi blocked ranges ki tarah treat hote hain
    blocks += list(
        Appointment.objects.filter(doctor=doctor, appointment_date=day, status__in=ACTIVE_STATUSES)
        .exclude(status=AppointmentStatus.PENDING, payment_due_at__lt=timezone.now())   # expired unpaid hold slot nahi rokta
        .values_list("start_time", "end_time")
    )
    now = timezone.localtime().replace(tzinfo=None)
    return drop_past_slots(generate_slots(windows, doctor.slot_duration, blocks), day, now)
