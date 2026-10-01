from datetime import datetime

from django.conf import settings
from django.db import models
from django.utils import timezone


class AppointmentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    CONFIRMED = "confirmed", "Confirmed"
    IN_PROGRESS = "in_progress", "In progress"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"
    NO_SHOW = "no_show", "No show"
    EXPIRED = "expired", "Expired"


# Ye statuses slot ko "occupied" rakhte hain
ACTIVE_STATUSES = [AppointmentStatus.PENDING.value, AppointmentStatus.CONFIRMED.value, AppointmentStatus.IN_PROGRESS.value]
# Inhe cancel/reschedule kiya ja sakta hai
CANCELLABLE_STATUSES = [AppointmentStatus.PENDING.value, AppointmentStatus.CONFIRMED.value]


class Appointment(models.Model):
    patient = models.ForeignKey("patients.PatientProfile", on_delete=models.PROTECT, related_name="appointments")
    doctor = models.ForeignKey("doctors.DoctorProfile", on_delete=models.PROTECT, related_name="appointments")
    appointment_date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    status = models.CharField(max_length=20, choices=AppointmentStatus.choices, default=AppointmentStatus.PENDING)
    consultation_fee = models.DecimalField(max_digits=8, decimal_places=2)  # booking ke waqt ki fee (snapshot)
    reason = models.CharField(max_length=500, blank=True)
    reschedule_count = models.PositiveSmallIntegerField(default=0)
    payment_due_at = models.DateTimeField(null=True, blank=True)   # PENDING slot is time tak hold rehta hai
    reminder_sent_at = models.DateTimeField(null=True, blank=True)  # set hone ke baad dobara reminder nahi jaata
    cancelled_by = models.CharField(max_length=10, blank=True)
    cancel_reason = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["appointment_date", "start_time"]
        constraints = [
            # Double-booking ka DB-level guarantee: ek doctor ke ek slot par sirf ek ACTIVE appointment.
            models.UniqueConstraint(
                fields=["doctor", "appointment_date", "start_time"],
                condition=models.Q(status__in=ACTIVE_STATUSES),
                name="unique_active_slot_per_doctor",
            ),
            models.CheckConstraint(condition=models.Q(end_time__gt=models.F("start_time")), name="appointment_end_after_start"),
        ]
        indexes = [
            models.Index(fields=["doctor", "appointment_date"]),
            models.Index(fields=["patient", "appointment_date"]),
        ]

    @property
    def reference(self):
        return f"APT{10000 + self.pk}"

    @property
    def starts_at(self):
        return timezone.make_aware(datetime.combine(self.appointment_date, self.start_time))

    @property
    def is_active(self):
        return self.status in ACTIVE_STATUSES

    def __str__(self):
        return f"{self.reference} {self.appointment_date} {self.start_time:%H:%M} ({self.status})"


class AppointmentStatusHistory(models.Model):
    appointment = models.ForeignKey(Appointment, on_delete=models.CASCADE, related_name="history")
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]
        verbose_name_plural = "appointment status history"
