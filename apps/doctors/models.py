from django.conf import settings
from django.db import models
from django.utils.text import slugify


class Specialization(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=110, unique=True, blank=True)

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class DoctorProfile(models.Model):
    class Gender(models.TextChoices):
        MALE = "M", "Male"
        FEMALE = "F", "Female"
        OTHER = "O", "Other"

    class ConsultationMode(models.TextChoices):
        IN_PERSON = "in_person", "In-person"
        ONLINE = "online", "Online"
        BOTH = "both", "In-person & online"

    class SlotDuration(models.IntegerChoices):
        M15 = 15, "15 minutes"
        M30 = 30, "30 minutes"
        M45 = 45, "45 minutes"
        M60 = 60, "60 minutes"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="doctor_profile")
    specialization = models.ForeignKey(Specialization, null=True, blank=True, on_delete=models.SET_NULL, related_name="doctors")
    qualification = models.CharField(max_length=200, blank=True)
    license_number = models.CharField(max_length=50, blank=True)
    experience_years = models.PositiveSmallIntegerField(default=0)
    hospital = models.CharField(max_length=150, blank=True)
    city = models.CharField(max_length=80, blank=True)
    consultation_fee = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    gender = models.CharField(max_length=1, choices=Gender.choices, blank=True)
    consultation_mode = models.CharField(max_length=10, choices=ConsultationMode.choices, default=ConsultationMode.IN_PERSON)
    bio = models.TextField(blank=True)
    slot_duration = models.PositiveSmallIntegerField(choices=SlotDuration.choices, default=SlotDuration.M30)
    # Admin verify kare tabhi doctor patients ko dikhega
    is_verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Dr. {self.user.get_full_name() or self.user.email}"


class DoctorAvailability(models.Model):
    """Weekly recurring window, e.g. Monday 09:00-13:00. Ek din mein multiple windows ho sakti hain."""

    class Weekday(models.IntegerChoices):
        MONDAY = 0, "Monday"
        TUESDAY = 1, "Tuesday"
        WEDNESDAY = 2, "Wednesday"
        THURSDAY = 3, "Thursday"
        FRIDAY = 4, "Friday"
        SATURDAY = 5, "Saturday"
        SUNDAY = 6, "Sunday"

    doctor = models.ForeignKey(DoctorProfile, on_delete=models.CASCADE, related_name="availabilities")
    weekday = models.PositiveSmallIntegerField(choices=Weekday.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        ordering = ["weekday", "start_time"]
        constraints = [
            models.CheckConstraint(condition=models.Q(end_time__gt=models.F("start_time")), name="availability_end_after_start"),
        ]

    def __str__(self):
        return f"{self.doctor} - {self.get_weekday_display()} {self.start_time:%H:%M}-{self.end_time:%H:%M}"


class DoctorBlockedSlot(models.Model):
    """Leave ya blocked time. start_time/end_time khali = poora din leave."""

    doctor = models.ForeignKey(DoctorProfile, on_delete=models.CASCADE, related_name="blocked_slots")
    date = models.DateField()
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    reason = models.CharField(max_length=150, blank=True)

    class Meta:
        ordering = ["date", "start_time"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(start_time__isnull=True, end_time__isnull=True)
                    | models.Q(start_time__isnull=False, end_time__isnull=False, end_time__gt=models.F("start_time"))
                ),
                name="blocked_full_day_or_valid_range",
            ),
        ]

    @property
    def is_full_day(self):
        return self.start_time is None

    def __str__(self):
        return f"{self.doctor} - {self.date} ({'full day' if self.is_full_day else f'{self.start_time:%H:%M}-{self.end_time:%H:%M}'})"
