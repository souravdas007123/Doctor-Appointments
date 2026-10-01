from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.doctors.models import DoctorProfile

from .models import PatientProfile


def make_user(email, role, first="Test"):
    return User.objects.create_user(username=email, email=email, password="Str0ng-pass-123", role=role, first_name=first)


class DoctorVisibilityTests(TestCase):
    def setUp(self):
        self.patient = make_user("p@example.com", "patient")
        PatientProfile.objects.create(user=self.patient)
        self.verified = DoctorProfile.objects.create(user=make_user("v@example.com", "doctor", "Verified"), is_verified=True)
        self.pending = DoctorProfile.objects.create(user=make_user("u@example.com", "doctor", "Pending"), is_verified=False)

    def test_list_shows_only_verified(self):
        self.client.force_login(self.patient)
        resp = self.client.get(reverse("patients:doctor_list"))
        self.assertContains(resp, "Verified")
        self.assertNotContains(resp, "Pending")

    def test_unverified_detail_is_404(self):
        self.client.force_login(self.patient)
        self.assertEqual(self.client.get(reverse("patients:doctor_detail", args=[self.pending.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("patients:doctor_detail", args=[self.verified.pk])).status_code, 200)

    def test_doctor_cannot_use_patient_pages(self):
        self.client.force_login(self.verified.user)
        self.assertEqual(self.client.get(reverse("patients:doctor_list")).status_code, 403)

    def test_anonymous_redirected_to_login(self):
        self.assertEqual(self.client.get(reverse("patients:doctor_list")).status_code, 302)
