from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        PATIENT = "patient", "Patient"
        DOCTOR = "doctor", "Doctor"
        ADMIN = "admin", "Admin"

    email = models.EmailField("email address", unique=True)
    phone = models.CharField(max_length=15, blank=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.PATIENT)

    def save(self, *args, **kwargs):
        # `createsuperuser` (aur admin panel se "superuser" tick karna) apna koi `role` nahi set karta,
        # isliye wo yahan model ke default "patient" par hi reh jaata, bina kisi PatientProfile ke --
        # role_required("patient") decorator ko ye pass ho jaata aur patient-only pages (jo
        # request.user.patient_profile access karte hain) 500 crash karte. Superuser hamesha
        # role=admin hona chahiye, chahe wo createsuperuser se bane ya admin panel se promote ho.
        if self.is_superuser:
            self.role = self.Role.ADMIN
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.get_full_name() or self.email} ({self.role})"
