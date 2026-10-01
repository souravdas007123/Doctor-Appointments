from datetime import time, timedelta

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.doctors.models import DoctorAvailability, DoctorProfile
from apps.doctors.slots import get_available_slots
from apps.patients.models import PatientProfile

from . import services
from .models import Appointment, AppointmentStatus


def make_user(email, role, first="T"):
    return User.objects.create_user(username=email, email=email, password="Str0ng-pass-123", role=role, first_name=first)


class BookingTestBase(TestCase):
    def setUp(self):
        self.day = timezone.localdate() + timedelta(days=7)
        self.doctor = DoctorProfile.objects.create(user=make_user("d@x.com", "doctor", "Doc"), is_verified=True, consultation_fee=0)
        DoctorAvailability.objects.create(doctor=self.doctor, weekday=self.day.weekday(), start_time=time(9), end_time=time(12))
        self.p1 = PatientProfile.objects.create(user=make_user("p1@x.com", "patient", "One"))
        self.p2 = PatientProfile.objects.create(user=make_user("p2@x.com", "patient", "Two"))

    def book(self, patient=None, start=time(10)):
        return services.book_appointment(patient=patient or self.p1, doctor=self.doctor, day=self.day, start_time=start)


class BookingServiceTests(BookingTestBase):
    def test_book_success(self):
        appt = self.book()
        self.assertEqual(appt.status, AppointmentStatus.CONFIRMED)
        self.assertEqual(appt.consultation_fee, 0)
        self.assertEqual(appt.history.count(), 1)

    def test_same_slot_cannot_be_booked_twice(self):
        self.book()
        with self.assertRaises(services.BookingError):
            self.book(patient=self.p2)

    def test_booked_slot_hidden_from_availability(self):
        self.book()
        self.assertNotIn((time(10), time(10, 30)), get_available_slots(self.doctor, self.day))

    def test_db_constraint_is_the_backstop(self):
        appt = self.book()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Appointment.objects.create(
                patient=self.p2, doctor=self.doctor, appointment_date=self.day, start_time=appt.start_time,
                end_time=appt.end_time, status=AppointmentStatus.CONFIRMED, consultation_fee=800)

    def test_invalid_slot_rejected(self):
        with self.assertRaises(services.BookingError):
            self.book(start=time(13))          # availability ke bahar

    def test_cancelled_slot_can_be_rebooked(self):
        appt = self.book()
        services.cancel_appointment(appt, by_user=self.p1.user)
        appt.refresh_from_db()
        self.assertEqual(appt.status, AppointmentStatus.CANCELLED)
        self.assertTrue(self.book(patient=self.p2))

    def test_cancel_notice_window(self):
        appt = self.book()
        self.assertIsNotNone(services.cancel_block_reason(appt, self.p1.user, now=appt.starts_at - timedelta(hours=1)))
        self.assertIsNone(services.cancel_block_reason(appt, self.p1.user, now=appt.starts_at - timedelta(hours=5)))

    def test_other_patient_cannot_cancel(self):
        appt = self.book()
        with self.assertRaises(services.BookingError):
            services.cancel_appointment(appt, by_user=self.p2.user)

    def test_doctor_can_cancel(self):
        appt = self.book()
        services.cancel_appointment(appt, by_user=self.doctor.user, reason="Emergency")
        appt.refresh_from_db()
        self.assertEqual(appt.cancelled_by, "doctor")

    def test_reschedule_and_limit(self):
        appt = self.book()
        services.reschedule_appointment(appt, by_user=self.p1.user, new_day=self.day, new_start=time(10, 30))
        appt.refresh_from_db()
        self.assertEqual((appt.start_time, appt.reschedule_count), (time(10, 30), 1))
        self.assertIn((time(10), time(10, 30)), get_available_slots(self.doctor, self.day))
        services.reschedule_appointment(appt, by_user=self.p1.user, new_day=self.day, new_start=time(11))
        with self.assertRaises(services.BookingError):
            services.reschedule_appointment(appt, by_user=self.p1.user, new_day=self.day, new_start=time(11, 30))

    def test_doctor_cannot_start_consultation_too_early(self):
        appt = self.book()
        with self.assertRaises(services.BookingError):
            services.update_status_by_doctor(appt, by_user=self.doctor.user, to_status="in_progress")


class BookingViewTests(BookingTestBase):
    def post_booking(self):
        return self.client.post(reverse("appointments:book"), {
            "doctor": self.doctor.pk, "date": self.day.isoformat(), "start": "10:00", "reason": "checkup"})

    def test_patient_books_and_other_patient_cannot_view(self):
        self.client.force_login(self.p1.user)
        resp = self.post_booking()
        appt = Appointment.objects.get()
        self.assertRedirects(resp, reverse("appointments:detail", args=[appt.pk]))
        self.client.force_login(self.p2.user)
        self.assertEqual(self.client.get(reverse("appointments:detail", args=[appt.pk])).status_code, 404)

    def test_unverified_doctor_cannot_be_booked(self):
        DoctorProfile.objects.filter(pk=self.doctor.pk).update(is_verified=False)
        self.client.force_login(self.p1.user)
        self.assertEqual(self.post_booking().status_code, 404)
        self.assertEqual(Appointment.objects.count(), 0)
