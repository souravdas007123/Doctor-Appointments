from django.conf import settings
from django.db import models


class Payment(models.Model):
    class Status(models.TextChoices):
        CREATED = "created", "Awaiting payment"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed / expired"
        REFUND_PENDING = "refund_pending", "Refund pending"
        REFUNDED = "refunded", "Refunded"

    appointment = models.ForeignKey("appointments.Appointment", on_delete=models.PROTECT, related_name="payments")
    patient = models.ForeignKey("patients.PatientProfile", on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    currency = models.CharField(max_length=3, default="INR")
    gateway = models.CharField(max_length=20, default="razorpay")
    gateway_order_id = models.CharField(max_length=64, unique=True)
    gateway_payment_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.CREATED)
    failure_reason = models.CharField(max_length=300, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.gateway_order_id} ₹{self.amount} ({self.status})"


class Refund(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSED = "processed", "Processed"
        FAILED = "failed", "Failed"

    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="refunds")
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    gateway_refund_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
    reason = models.CharField(max_length=200, blank=True)
    failure_reason = models.CharField(max_length=300, blank=True)
    initiated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class WebhookEvent(models.Model):
    """Razorpay ek event kai baar bhej sakta hai; event_id se duplicates pehchante hain."""
    event_id = models.CharField(max_length=80, unique=True)
    event_type = models.CharField(max_length=60)
    processed = models.BooleanField(default=False)
    received_at = models.DateTimeField(auto_now_add=True)
