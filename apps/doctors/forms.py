from django import forms
from django.utils import timezone

from .models import DoctorAvailability, DoctorBlockedSlot, DoctorProfile

TIME = forms.TimeInput(attrs={"type": "time"}, format="%H:%M")


class DoctorProfileForm(forms.ModelForm):
    class Meta:
        model = DoctorProfile
        fields = (
            "specialization", "qualification", "license_number", "experience_years",
            "gender", "hospital", "city", "consultation_fee", "consultation_mode", "slot_duration", "bio",
        )
        widgets = {"bio": forms.Textarea(attrs={"rows": 4})}
        labels = {"slot_duration": "Consultation duration", "consultation_fee": "Consultation fee (₹)"}


class AvailabilityForm(forms.ModelForm):
    class Meta:
        model = DoctorAvailability
        fields = ("weekday", "start_time", "end_time")
        widgets = {"start_time": TIME, "end_time": TIME}

    def __init__(self, *args, doctor, **kwargs):
        super().__init__(*args, **kwargs)
        self.doctor = doctor

    def clean(self):
        data = super().clean()
        weekday, start, end = data.get("weekday"), data.get("start_time"), data.get("end_time")
        if weekday is None or not start or not end:
            return data
        if end <= start:
            raise forms.ValidationError("End time, start time ke baad hona chahiye.")
        overlap = DoctorAvailability.objects.filter(
            doctor=self.doctor, weekday=weekday, start_time__lt=end, end_time__gt=start
        ).exists()
        if overlap:
            raise forms.ValidationError("Is din ki koi aur window is time se overlap kar rahi hai.")
        return data

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.doctor = self.doctor
        if commit:
            obj.save()
        return obj


class BlockedSlotForm(forms.ModelForm):
    class Meta:
        model = DoctorBlockedSlot
        fields = ("date", "start_time", "end_time", "reason")
        widgets = {"date": forms.DateInput(attrs={"type": "date"}), "start_time": TIME, "end_time": TIME}
        help_texts = {"start_time": "Poore din ki leave ke liye start/end khali chhodo."}

    def __init__(self, *args, doctor, **kwargs):
        super().__init__(*args, **kwargs)
        self.doctor = doctor

    def clean_date(self):
        d = self.cleaned_data["date"]
        if d < timezone.localdate():
            raise forms.ValidationError("Past date block nahi ho sakti.")
        return d

    def clean(self):
        data = super().clean()
        start, end = data.get("start_time"), data.get("end_time")
        if bool(start) != bool(end):
            raise forms.ValidationError("Start aur end dono bharo, ya dono khali chhodo.")
        if start and end and end <= start:
            raise forms.ValidationError("End time, start time ke baad hona chahiye.")
        return data

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.doctor = self.doctor
        if commit:
            obj.save()
        return obj
