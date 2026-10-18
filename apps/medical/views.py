from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.appointments.models import Appointment
from apps.notifications.models import Notification
from apps.notifications.services import notify

from .forms import MedicalRecordForm, PrescriptionForm, PrescriptionItemFormSet
from .models import (
    CONSULTABLE_STATUSES,
    AuditLog,
    MedicalRecord,
    Prescription,
    log_access,
)
from .pdf import build_prescription_pdf


def _appointment_for_user(request, appointment_id):
    """Object-level access: sirf isi appointment ka doctor ya patient. Kisi aur ko 404."""
    qs = Appointment.objects.select_related("doctor__user", "doctor__specialization", "patient__user")
    if request.user.role == "doctor":
        return get_object_or_404(qs, pk=appointment_id, doctor__user=request.user)
    if request.user.role == "patient":
        return get_object_or_404(qs, pk=appointment_id, patient__user=request.user)
    raise PermissionDenied


def _require_consultable(request, appt):
    if appt.status not in CONSULTABLE_STATUSES:
        messages.error(request, "Consultation shuru hone ke baad hi record/prescription likha ja sakta hai.")
        return False
    return True


def record_view(request, appointment_id):
    appt = _appointment_for_user(request, appointment_id)
    record = MedicalRecord.objects.filter(appointment=appt).first()
    if record is None:
        if request.user.role == "doctor" and appt.status in CONSULTABLE_STATUSES:
            return redirect("medical:record_edit", appointment_id=appt.pk)
        messages.info(request, "Is appointment ka abhi tak koi medical record nahi bana hai.")
        return redirect("appointments:detail", pk=appt.pk)
    log_access(request, AuditLog.Action.VIEWED_RECORD, appt)
    return render(request, "medical/record_view.html", {"appt": appt, "record": record})


def record_edit(request, appointment_id):
    if request.user.role != "doctor":
        raise PermissionDenied
    appt = _appointment_for_user(request, appointment_id)
    if not _require_consultable(request, appt):
        return redirect("appointments:detail", pk=appt.pk)
    record = MedicalRecord.objects.filter(appointment=appt).first()
    is_new = record is None
    form = MedicalRecordForm(request.POST or None, instance=record)
    if request.method == "POST" and form.is_valid():
        record = form.save(commit=False)
        record.appointment = appt
        if is_new:
            record.created_by = request.user
        record.save()
        log_access(request, AuditLog.Action.CREATED_RECORD if is_new else AuditLog.Action.UPDATED_RECORD, appt)
        messages.success(request, "Medical record save ho gaya.")
        return redirect("medical:record_view", appointment_id=appt.pk)
    return render(request, "medical/record_edit.html", {"appt": appt, "form": form, "is_new": is_new})


def prescription_view(request, appointment_id):
    appt = _appointment_for_user(request, appointment_id)
    prescription = Prescription.objects.filter(appointment=appt).prefetch_related("items").first()
    if prescription is None:
        if request.user.role == "doctor" and appt.status in CONSULTABLE_STATUSES:
            return redirect("medical:prescription_edit", appointment_id=appt.pk)
        messages.info(request, "Is appointment ki abhi tak koi prescription nahi bani hai.")
        return redirect("appointments:detail", pk=appt.pk)
    log_access(request, AuditLog.Action.VIEWED_PRESCRIPTION, appt)
    return render(request, "medical/prescription_view.html", {"appt": appt, "prescription": prescription})


def prescription_edit(request, appointment_id):
    if request.user.role != "doctor":
        raise PermissionDenied
    appt = _appointment_for_user(request, appointment_id)
    if not _require_consultable(request, appt):
        return redirect("appointments:detail", pk=appt.pk)
    prescription = Prescription.objects.filter(appointment=appt).first()
    is_new = prescription is None
    form = PrescriptionForm(request.POST or None, instance=prescription)
    formset = PrescriptionItemFormSet(request.POST or None, instance=prescription)
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        prescription = form.save(commit=False)
        prescription.appointment = appt
        if is_new:
            prescription.created_by = request.user
        prescription.save()
        formset.instance = prescription
        formset.save()
        log_access(request, AuditLog.Action.CREATED_PRESCRIPTION if is_new else AuditLog.Action.UPDATED_PRESCRIPTION, appt)
        if is_new:
            notify(appt.patient.user, Notification.Type.PRESCRIPTION_AVAILABLE, "Prescription available",
                   f"Dr. {appt.doctor.user.get_full_name() or appt.doctor.user.email} · {appt.appointment_date:%d %b %Y}", appointment=appt)
        messages.success(request, "Prescription save ho gayi.")
        return redirect("medical:prescription_view", appointment_id=appt.pk)
    return render(request, "medical/prescription_edit.html", {"appt": appt, "form": form, "formset": formset, "is_new": is_new})


def prescription_pdf(request, appointment_id):
    appt = _appointment_for_user(request, appointment_id)
    prescription = get_object_or_404(Prescription.objects.prefetch_related("items"), appointment=appt)
    log_access(request, AuditLog.Action.DOWNLOADED_PDF, appt)
    buf = build_prescription_pdf(prescription)
    return FileResponse(buf, as_attachment=True, filename=f"prescription-{appt.reference}.pdf")
