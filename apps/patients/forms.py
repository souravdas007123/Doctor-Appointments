from django import forms
from django.db.models import Q
from django.utils import timezone

from apps.appointments.rules import MAX_BOOKING_DAYS
from apps.doctors.models import DoctorProfile, Specialization

from .models import PatientProfile

BLOOD_GROUPS = [("", "Not sure")] + [(g, g) for g in ("A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-")]


class PatientProfileForm(forms.ModelForm):
    blood_group = forms.ChoiceField(choices=BLOOD_GROUPS, required=False)

    class Meta:
        model = PatientProfile
        fields = ("date_of_birth", "gender", "blood_group", "address")
        widgets = {"date_of_birth": forms.DateInput(attrs={"type": "date"}), "address": forms.Textarea(attrs={"rows": 3})}

    def clean_date_of_birth(self):
        dob = self.cleaned_data.get("date_of_birth")
        if dob and dob > timezone.localdate():
            raise forms.ValidationError("Date of birth future mein nahi ho sakti.")
        return dob


class DoctorSearchForm(forms.Form):
    q = forms.CharField(required=False, label="Search", widget=forms.TextInput(attrs={"placeholder": "Name, hospital ya speciality"}))
    specialization = forms.ModelChoiceField(queryset=Specialization.objects.none(), required=False, empty_label="All specialities")
    city = forms.ChoiceField(required=False)
    gender = forms.ChoiceField(required=False, choices=[("", "Any")] + DoctorProfile.Gender.choices)
    mode = forms.ChoiceField(
        required=False, label="Consultation",
        choices=[("", "Any"), ("in_person", "In-person"), ("online", "Online")],
    )
    max_fee = forms.DecimalField(required=False, min_value=0, label="Max fee (₹)")
    min_experience = forms.IntegerField(required=False, min_value=0, label="Min experience (years)")
    date = forms.DateField(required=False, label="Available on", widget=forms.DateInput(attrs={"type": "date"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        verified = DoctorProfile.objects.filter(is_verified=True, user__is_active=True)
        self.fields["specialization"].queryset = Specialization.objects.filter(doctors__in=verified).distinct()
        cities = verified.exclude(city="").order_by("city").values_list("city", flat=True).distinct()
        self.fields["city"].choices = [("", "All cities")] + [(c, c) for c in cities]

    def clean_date(self):
        d = self.cleaned_data.get("date")
        if d:
            today = timezone.localdate()
            if d < today:
                raise forms.ValidationError("Past date select nahi ho sakti.")
            if (d - today).days > MAX_BOOKING_DAYS:
                raise forms.ValidationError(f"Sirf agle {MAX_BOOKING_DAYS} din ke slots dikh sakte hain.")
        return d

    def filter(self, qs):
        """Valid cleaned_data ke hisaab se queryset filter karta hai."""
        cd = self.cleaned_data
        if cd.get("q"):
            q = cd["q"]
            qs = qs.filter(
                Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q)
                | Q(hospital__icontains=q) | Q(specialization__name__icontains=q)
            )
        if cd.get("specialization"):
            qs = qs.filter(specialization=cd["specialization"])
        if cd.get("city"):
            qs = qs.filter(city__iexact=cd["city"])
        if cd.get("gender"):
            qs = qs.filter(gender=cd["gender"])
        if cd.get("mode"):
            qs = qs.filter(Q(consultation_mode=cd["mode"]) | Q(consultation_mode="both"))
        if cd.get("max_fee") is not None:
            qs = qs.filter(consultation_fee__lte=cd["max_fee"])
        if cd.get("min_experience") is not None:
            qs = qs.filter(experience_years__gte=cd["min_experience"])
        return qs
