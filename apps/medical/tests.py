from datetime import time, timedelta
from io import BytesIO

from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.appointments import services as appt_services
from apps.appointments.models import AppointmentStatus
from apps.doctors.models import DoctorAvailability, DoctorProfile
from apps.patients.models import PatientProfile

from .models import AuditLog, MedicalRecord, Prescription, PrescriptionItem
from .pdf import build_prescription_pdf

S = AppointmentStatus


def make_user(email, role, first="T"):
    return User.objects.create_user(username=email, email=email, password="Str0ng-pass-123", role=role, first_name=first)


class MedicalTestBase(TestCase):
    def setUp(self):
        self.day = timezone.localdate() + timedelta(days=3)
        self.doctor = DoctorProfile.objects.create(user=make_user("d@x.com", "doctor", "Doc"), is_verified=True, consultation_fee=0)
        DoctorAvailability.objects.create(doctor=self.doctor, weekday=self.day.weekday(), start_time=time(9), end_time=time(12))
        self.patient = PatientProfile.objects.create(user=make_user("p@x.com", "patient", "Pat"))
        self.other_patient = PatientProfile.objects.create(user=make_user("p2@x.com", "patient", "Other"))
        self.other_doctor = DoctorProfile.objects.create(user=make_user("d2@x.com", "doctor", "Other"), is_verified=True)
        self.appt = appt_services.book_appointment(patient=self.patient, doctor=self.doctor, day=self.day, start_time=time(9))

    def start_consultation(self):
        self.appt.status = S.IN_PROGRESS
        self.appt.save(update_fields=["status"])


class AccessControlTests(MedicalTestBase):
    def test_record_edit_requires_in_progress_or_completed(self):
        self.client.force_login(self.doctor.user)
        resp = self.client.get(reverse("medical:record_edit", args=[self.appt.pk]), follow=True)
        self.assertRedirects(resp, reverse("appointments:detail", args=[self.appt.pk]))
        self.assertEqual(MedicalRecord.objects.count(), 0)

    def test_other_doctor_cannot_access(self):
        self.start_consultation()
        self.client.force_login(self.other_doctor.user)
        self.assertEqual(self.client.get(reverse("medical:record_edit", args=[self.appt.pk])).status_code, 404)

    def test_other_patient_cannot_view_record(self):
        self.start_consultation()
        MedicalRecord.objects.create(appointment=self.appt, diagnosis="Flu", created_by=self.doctor.user)
        self.client.force_login(self.other_patient.user)
        self.assertEqual(self.client.get(reverse("medical:record_view", args=[self.appt.pk])).status_code, 404)

    def test_patient_cannot_edit_record(self):
        self.start_consultation()
        self.client.force_login(self.patient.user)
        with self.assertRaises(PermissionDenied):
            self.client.get(reverse("medical:record_edit", args=[self.appt.pk]), follow=False)


class RecordAndPrescriptionFlowTests(MedicalTestBase):
    def test_doctor_creates_record(self):
        self.start_consultation()
        self.client.force_login(self.doctor.user)
        resp = self.client.post(reverse("medical:record_edit", args=[self.appt.pk]), {
            "chief_complaint": "Fever", "diagnosis": "Viral fever", "bp_systolic": 120, "bp_diastolic": 80,
            "pulse": 76, "weight_kg": "68.5", "doctor_notes": "Rest advised", "follow_up_date": "",
        })
        self.assertRedirects(resp, reverse("medical:record_view", args=[self.appt.pk]))
        record = MedicalRecord.objects.get(appointment=self.appt)
        self.assertEqual(record.created_by, self.doctor.user)
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.CREATED_RECORD, appointment=self.appt).exists())

    def test_patient_view_logs_audit(self):
        self.start_consultation()
        MedicalRecord.objects.create(appointment=self.appt, diagnosis="Flu", created_by=self.doctor.user)
        self.client.force_login(self.patient.user)
        self.client.get(reverse("medical:record_view", args=[self.appt.pk]))
        self.assertTrue(AuditLog.objects.filter(user=self.patient.user, action=AuditLog.Action.VIEWED_RECORD).exists())

    def test_prescription_formset_creates_items(self):
        self.start_consultation()
        self.client.force_login(self.doctor.user)
        data = {
            "advice": "Drink water", "follow_up_days": "7",
            "items-TOTAL_FORMS": "2", "items-INITIAL_FORMS": "0", "items-MIN_NUM_FORMS": "1", "items-MAX_NUM_FORMS": "1000",
            "items-0-medicine_name": "Paracetamol", "items-0-dosage": "500mg", "items-0-frequency": "2x/day",
            "items-0-duration": "5 days", "items-0-instructions": "After food",
            "items-1-medicine_name": "", "items-1-dosage": "", "items-1-frequency": "", "items-1-duration": "", "items-1-instructions": "",
        }
        resp = self.client.post(reverse("medical:prescription_edit", args=[self.appt.pk]), data)
        self.assertRedirects(resp, reverse("medical:prescription_view", args=[self.appt.pk]))
        pres = Prescription.objects.get(appointment=self.appt)
        self.assertEqual(pres.items.count(), 1)
        self.assertEqual(pres.items.first().medicine_name, "Paracetamol")

    def test_prescription_requires_at_least_one_medicine(self):
        self.start_consultation()
        self.client.force_login(self.doctor.user)
        data = {
            "advice": "", "follow_up_days": "",
            "items-TOTAL_FORMS": "1", "items-INITIAL_FORMS": "0", "items-MIN_NUM_FORMS": "1", "items-MAX_NUM_FORMS": "1000",
            "items-0-medicine_name": "", "items-0-dosage": "", "items-0-frequency": "", "items-0-duration": "", "items-0-instructions": "",
        }
        self.client.post(reverse("medical:prescription_edit", args=[self.appt.pk]), data)
        self.assertEqual(Prescription.objects.count(), 0)

    def test_pdf_download_logs_and_returns_pdf(self):
        self.start_consultation()
        pres = Prescription.objects.create(appointment=self.appt, advice="Rest", created_by=self.doctor.user)
        PrescriptionItem.objects.create(prescription=pres, medicine_name="Paracetamol", dosage="500mg")
        self.client.force_login(self.patient.user)
        resp = self.client.get(reverse("medical:prescription_pdf", args=[self.appt.pk]))
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.DOWNLOADED_PDF, user=self.patient.user).exists())


class PdfGenerationTests(MedicalTestBase):
    def test_pdf_bytes_are_generated(self):
        self.start_consultation()
        pres = Prescription.objects.create(appointment=self.appt, advice="Rest well", follow_up_days=10, created_by=self.doctor.user)
        PrescriptionItem.objects.create(prescription=pres, medicine_name="Amoxicillin", dosage="250mg", frequency="3x/day", duration="7 days")
        buf = build_prescription_pdf(pres)
        self.assertIsInstance(buf, BytesIO)
        content = buf.getvalue()
        self.assertTrue(content.startswith(b"%PDF"))
        self.assertGreater(len(content), 500)
