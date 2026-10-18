from datetime import time, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.appointments import services as appt_services
from apps.doctors.models import DoctorAvailability, DoctorProfile
from apps.patients.models import PatientProfile

from .models import DeliveryAttempt, Notification


def make_user(email, role, first="T", phone=""):
    return User.objects.create_user(username=email, email=email, password="Str0ng-pass-123", role=role, first_name=first, phone=phone)


class NotificationTriggerTests(TestCase):
    """CELERY_TASK_ALWAYS_EAGER=True (settings/base.py) hai, isliye .delay() yahin turant chal jaata hai."""

    def setUp(self):
        self.day = timezone.localdate() + timedelta(days=5)
        self.doctor = DoctorProfile.objects.create(user=make_user("d@x.com", "doctor", "Doc"), is_verified=True, consultation_fee=0)
        DoctorAvailability.objects.create(doctor=self.doctor, weekday=self.day.weekday(), start_time=time(9), end_time=time(12))
        self.patient = PatientProfile.objects.create(user=make_user("p@x.com", "patient", "Pat", phone="+919876543210"))

    def test_booking_notifies_patient_and_doctor(self):
        # notify() ka .delay() transaction.on_commit() ke andar hai (services.py) -- production mein
        # sahi hai (sirf real commit par chale), lekin TestCase ka transaction kabhi commit nahi hota,
        # isliye on_commit callbacks khud test karne ke liye yahan explicitly force karna padta hai.
        with self.captureOnCommitCallbacks(execute=True):
            appt = appt_services.book_appointment(patient=self.patient, doctor=self.doctor, day=self.day, start_time=time(9))
        self.assertTrue(Notification.objects.filter(recipient=self.patient.user, notification_type=Notification.Type.APPOINTMENT_CONFIRMED, appointment=appt).exists())
        self.assertTrue(Notification.objects.filter(recipient=self.doctor.user, notification_type=Notification.Type.NEW_APPOINTMENT, appointment=appt).exists())
        # Email eager mode mein turant "sent" (console backend) DeliveryAttempt bana deta hai
        self.assertTrue(DeliveryAttempt.objects.filter(channel="email", status="sent").exists())

    def test_cancel_notifies_other_party(self):
        appt = appt_services.book_appointment(patient=self.patient, doctor=self.doctor, day=self.day, start_time=time(9))
        appt_services.cancel_appointment(appt, by_user=self.patient.user)
        self.assertTrue(Notification.objects.filter(recipient=self.doctor.user, notification_type=Notification.Type.APPOINTMENT_CANCELLED).exists())
        self.assertFalse(Notification.objects.filter(recipient=self.patient.user, notification_type=Notification.Type.APPOINTMENT_CANCELLED).exists())

    def test_reschedule_notifies_doctor(self):
        appt = appt_services.book_appointment(patient=self.patient, doctor=self.doctor, day=self.day, start_time=time(9))
        appt_services.reschedule_appointment(appt, by_user=self.patient.user, new_day=self.day, new_start=time(10))
        self.assertTrue(Notification.objects.filter(recipient=self.doctor.user, notification_type=Notification.Type.APPOINTMENT_RESCHEDULED).exists())

    def test_reminder_sent_once_within_window_and_not_twice(self):
        appt = appt_services.book_appointment(patient=self.patient, doctor=self.doctor, day=self.day, start_time=time(9))
        from apps.appointments.models import Appointment
        near = timezone.now() + timedelta(hours=2)
        # appointment_date/start_time naive, LOCAL wall-clock fields hain (Appointment.starts_at unhe
        # TIME_ZONE, Asia/Kolkata, mein wapas aware karta hai). timezone.now() UTC mein aata hai (USE_TZ=True),
        # isliye .date()/.time() seedhe UTC par lagana galat local time de deta -- IST (+5:30) mein ye
        # appointment ko ~5:30 ghante "peeche" (past mein) daal deta, aur reminder kabhi "due" nahi dikhta.
        # localtime() se pehle IST mein convert karna zaroori hai.
        near_local = timezone.localtime(near)
        Appointment.objects.filter(pk=appt.pk).update(appointment_date=near_local.date())
        appt.refresh_from_db()
        appt.start_time = near_local.time()
        # end_time ko bhi aage badhana zaroori hai, warna DB ka "end_time > start_time" CHECK constraint
        # tootta hai jab test din ke kisi aise waqt chale jahan near.time() purani end_time (09:30) se aage ho
        # -- isse pehle ye test chalne ke waqt (time of day) par depend karta tha (flaky).
        appt.end_time = timezone.localtime(near + timedelta(minutes=30)).time()
        appt.save(update_fields=["start_time", "end_time"])
        sent_first = appt_services.send_due_reminders()
        sent_second = appt_services.send_due_reminders()
        self.assertEqual((sent_first, sent_second), (1, 0))
        self.assertEqual(Notification.objects.filter(notification_type=Notification.Type.APPOINTMENT_REMINDER).count(), 1)

    def test_reminder_sms_sent_when_patient_has_phone(self):
        appt = appt_services.book_appointment(patient=self.patient, doctor=self.doctor, day=self.day, start_time=time(9))
        near = timezone.now() + timedelta(hours=1)
        from apps.appointments.models import Appointment
        # UTC -> local (Asia/Kolkata) convert karna zaroori hai (dekho note upar wale test mein).
        near_local = timezone.localtime(near)
        Appointment.objects.filter(pk=appt.pk).update(appointment_date=near_local.date())
        appt.refresh_from_db()
        appt.start_time = near_local.time()
        # end_time ko bhi aage badhao -- warna CHECK constraint (end_time > start_time) time-of-day
        # ke hisaab se kabhi pass kabhi fail hota (flaky), jaisa upar wale test mein tha.
        appt.end_time = timezone.localtime(near + timedelta(minutes=30)).time()
        appt.save(update_fields=["start_time", "end_time"])
        # on_commit callback force karo (dekho upar ki note test_booking_notifies_patient_and_doctor mein)
        with self.captureOnCommitCallbacks(execute=True):
            appt_services.send_due_reminders()
        notif = Notification.objects.get(notification_type=Notification.Type.APPOINTMENT_REMINDER)
        self.assertTrue(DeliveryAttempt.objects.filter(notification=notif, channel="sms", status="sent").exists())  # patient ka phone hai

    def test_sms_skipped_when_recipient_has_no_phone(self):
        from apps.notifications.services import notify
        no_phone_patient = make_user("np@x.com", "patient", "NoPhone")   # phone="" (default)
        PatientProfile.objects.create(user=no_phone_patient)
        with self.captureOnCommitCallbacks(execute=True):
            notif = notify(no_phone_patient, Notification.Type.APPOINTMENT_REMINDER, "Reminder", "test")
        self.assertTrue(DeliveryAttempt.objects.filter(notification=notif, channel="sms", status="skipped").exists())


class NotificationViewTests(TestCase):
    def setUp(self):
        self.user = make_user("u@x.com", "patient", "U")
        PatientProfile.objects.create(user=self.user)

    def test_open_marks_read_and_redirects(self):
        n = Notification.objects.create(recipient=self.user, notification_type=Notification.Type.PAYMENT_SUCCESSFUL, title="Paid")
        self.client.force_login(self.user)
        self.client.get(reverse("notifications:open", args=[n.pk]))
        n.refresh_from_db()
        self.assertTrue(n.is_read)

    def test_other_user_cannot_open_notification(self):
        other = make_user("o@x.com", "patient", "O")
        PatientProfile.objects.create(user=other)
        n = Notification.objects.create(recipient=self.user, notification_type=Notification.Type.PAYMENT_SUCCESSFUL, title="Paid")
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("notifications:open", args=[n.pk])).status_code, 404)

    def test_mark_all_read(self):
        Notification.objects.create(recipient=self.user, notification_type=Notification.Type.PAYMENT_SUCCESSFUL, title="A")
        Notification.objects.create(recipient=self.user, notification_type=Notification.Type.PAYMENT_SUCCESSFUL, title="B")
        self.client.force_login(self.user)
        self.client.post(reverse("notifications:mark_all_read"))
        self.assertEqual(self.user.notifications.filter(is_read=False).count(), 0)
