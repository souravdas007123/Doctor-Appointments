from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.db import transaction

from apps.doctors.models import DoctorProfile
from apps.patients.models import PatientProfile

from .models import User


class EmailLoginForm(AuthenticationForm):
    username = forms.CharField(
        label="Email", widget=forms.EmailInput(attrs={"autofocus": True})
    )


class SignupForm(UserCreationForm):
    role = forms.ChoiceField(
        choices=[(User.Role.PATIENT, "Patient"), (User.Role.DOCTOR, "Doctor")],
        label="I am a",
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("first_name", "last_name", "email", "phone", "role")

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Is email se account pehle se hai.")
        return email

    @transaction.atomic
    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = user.email          # email hi login id hai
        user.role = self.cleaned_data["role"]
        user.save()
        if user.role == User.Role.DOCTOR:
            DoctorProfile.objects.create(user=user)
        else:
            PatientProfile.objects.create(user=user)
        return user
