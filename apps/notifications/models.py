from django.conf import settings
from django.db import models


class Notification(models.Model):
    class Type(models.TextChoices):
        APPOINTMENT_CONFIRMED = "appointment_confirmed", "Appointment confirmed"
        APPOINTMENT_REMINDER = "appointment_reminder", "Appointment reminder"
        APPOINTMENT_RESCHEDULED = "appointment_rescheduled", "Appointment rescheduled"
        APPOINTMENT_CANCELLED = "appointment_cancelled", "Appointment cancelled"
        NEW_APPOINTMENT = "new_appointment", "New appointment"
        PAYMENT_SUCCESSFUL = "payment_successful", "Payment successful"
        PAYMENT_RECEIVED = "payment_received", "Payment received"
        PRESCRIPTION_AVAILABLE = "prescription_available", "Prescription available"

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    notification_type = models.CharField(max_length=30, choices=Type.choices)
    title = models.CharField(max_length=150)
    message = models.CharField(max_length=500, blank=True)
    appointment = models.ForeignKey("appointments.Appointment", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["recipient", "is_read"])]

    def __str__(self):
        return f"{self.get_notification_type_display()} -> {self.recipient}"


class DeliveryAttempt(models.Model):
    """Email/SMS bhejne ki har koshish ka record, debugging ke liye."""

    class Channel(models.TextChoices):
        EMAIL = "email", "Email"
        SMS = "sms", "SMS"

    class Status(models.TextChoices):
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"

    notification = models.ForeignKey(Notification, on_delete=models.CASCADE, related_name="delivery_attempts")
    channel = models.CharField(max_length=10, choices=Channel.choices)
    status = models.CharField(max_length=10, choices=Status.choices)
    error = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
