from django.conf import settings
from django.db import models

# Consultation ho chuki/chal rahi ho tabhi record/prescription likha ja sakta hai.
CONSULTABLE_STATUSES = ("in_progress", "completed")


class MedicalRecord(models.Model):
    """Ek appointment ka ek hi record hota hai; edits isi row par hoti hain, history AuditLog mein."""

    appointment = models.OneToOneField("appointments.Appointment", on_delete=models.PROTECT, related_name="medical_record")
    chief_complaint = models.CharField(max_length=300, blank=True)
    diagnosis = models.TextField(blank=True)
    bp_systolic = models.PositiveSmallIntegerField(null=True, blank=True)
    bp_diastolic = models.PositiveSmallIntegerField(null=True, blank=True)
    pulse = models.PositiveSmallIntegerField(null=True, blank=True)
    weight_kg = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    doctor_notes = models.TextField(blank=True)
    follow_up_date = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Medical record for {self.appointment}"


class Prescription(models.Model):
    appointment = models.OneToOneField("appointments.Appointment", on_delete=models.PROTECT, related_name="prescription")
    advice = models.TextField(blank=True)
    follow_up_days = models.PositiveSmallIntegerField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Prescription for {self.appointment}"


class PrescriptionItem(models.Model):
    prescription = models.ForeignKey(Prescription, on_delete=models.CASCADE, related_name="items")
    medicine_name = models.CharField(max_length=150)
    dosage = models.CharField(max_length=60, blank=True)
    frequency = models.CharField(max_length=60, blank=True)
    duration = models.CharField(max_length=60, blank=True)
    instructions = models.CharField(max_length=200, blank=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "pk"]


class AuditLog(models.Model):
    """Kisne kya dekha/badla, medical data ke liye. Kabhi delete/edit nahi hota, sirf create."""

    class Action(models.TextChoices):
        VIEWED_RECORD = "viewed_record", "Viewed medical record"
        CREATED_RECORD = "created_record", "Created medical record"
        UPDATED_RECORD = "updated_record", "Updated medical record"
        VIEWED_PRESCRIPTION = "viewed_prescription", "Viewed prescription"
        CREATED_PRESCRIPTION = "created_prescription", "Created prescription"
        UPDATED_PRESCRIPTION = "updated_prescription", "Updated prescription"
        DOWNLOADED_PDF = "downloaded_pdf", "Downloaded prescription PDF"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=30, choices=Action.choices)
    appointment = models.ForeignKey("appointments.Appointment", null=True, on_delete=models.SET_NULL, related_name="audit_logs")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["appointment", "-created_at"])]

    def __str__(self):
        return f"{self.user} {self.action} @ {self.created_at:%Y-%m-%d %H:%M}"


def log_access(request, action, appointment):
    AuditLog.objects.create(
        user=request.user if request.user.is_authenticated else None,
        action=action, appointment=appointment,
        ip_address=request.META.get("REMOTE_ADDR"),
    )
