from django import forms
from django.forms import inlineformset_factory

from .models import MedicalRecord, Prescription, PrescriptionItem


class MedicalRecordForm(forms.ModelForm):
    class Meta:
        model = MedicalRecord
        fields = ("chief_complaint", "diagnosis", "bp_systolic", "bp_diastolic", "pulse", "weight_kg",
                  "doctor_notes", "follow_up_date")
        widgets = {
            "diagnosis": forms.Textarea(attrs={"rows": 3}),
            "doctor_notes": forms.Textarea(attrs={"rows": 4}),
            "follow_up_date": forms.DateInput(attrs={"type": "date"}),
        }
        labels = {"bp_systolic": "BP systolic", "bp_diastolic": "BP diastolic"}


class PrescriptionForm(forms.ModelForm):
    class Meta:
        model = Prescription
        fields = ("advice", "follow_up_days")
        widgets = {"advice": forms.Textarea(attrs={"rows": 3})}
        labels = {"follow_up_days": "Follow-up (days)"}


PrescriptionItemFormSet = inlineformset_factory(
    Prescription, PrescriptionItem,
    fields=("medicine_name", "dosage", "frequency", "duration", "instructions"),
    extra=1, can_delete=True, min_num=1, validate_min=True,
)
