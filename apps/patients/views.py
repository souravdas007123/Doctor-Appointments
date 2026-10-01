from datetime import date, timedelta

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.accounts.decorators import role_required
from apps.appointments.models import ACTIVE_STATUSES, Appointment, AppointmentStatus
from apps.medical.models import MedicalRecord, Prescription
from apps.doctors.models import DoctorAvailability, DoctorProfile
from apps.doctors.slots import get_available_slots

from .forms import MAX_BOOKING_DAYS, DoctorSearchForm, PatientProfileForm

PAGE_SIZE = 10


def _verified_doctors():
    """Patients ko sirf verified + active doctors dikhte hain. Har doctor query yahin se guzarti hai."""
    return (
        DoctorProfile.objects.filter(is_verified=True, user__is_active=True)
        .select_related("user", "specialization")
        .order_by("user__first_name", "user__last_name", "pk")
    )


@role_required("patient")
def dashboard(request):
    today = timezone.localdate()
    mine = Appointment.objects.filter(patient__user=request.user)
    upcoming = Q(status__in=ACTIVE_STATUSES, appointment_date__gte=today)
    stats = mine.aggregate(
        upcoming=Count("pk", filter=upcoming),
        completed=Count("pk", filter=Q(status=AppointmentStatus.COMPLETED)),
        cancelled=Count("pk", filter=Q(status=AppointmentStatus.CANCELLED)),
    )
    next_appointments = (
        mine.filter(upcoming).select_related("doctor__user", "doctor__specialization")
        .order_by("appointment_date", "start_time")[:3]
    )
    return render(request, "patients/dashboard.html", {"stats": stats, "next_appointments": next_appointments})


@role_required("patient")
def profile_edit(request):
    form = PatientProfileForm(request.POST or None, instance=request.user.patient_profile)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profile save ho gaya.")
        return redirect("patients:profile")
    return render(request, "patients/profile.html", {"form": form})


@role_required("patient")
def doctor_list(request):
    form = DoctorSearchForm(request.GET or None)
    doctors = _verified_doctors()
    day = None
    if form.is_bound:
        form.is_valid()                      # invalid fields cleaned_data se bahar rehte hain
        doctors = form.filter(doctors)
        day = form.cleaned_data.get("date")
    if day:
        # NOTE: har doctor ke liye slots nikalte hain. Chhote/medium catalog ke liye theek hai;
        # bade scale par isse ek precomputed availability query se replace karna hoga.
        doctors = [d for d in doctors if get_available_slots(d, day)]
    page = Paginator(doctors, PAGE_SIZE).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "patients/doctor_list.html", {
        "form": form, "page": page, "querystring": params.urlencode(), "day": day,
    })


@role_required("patient")
def doctor_detail(request, pk):
    doctor = get_object_or_404(_verified_doctors(), pk=pk)   # unverified doctor => 404
    today = timezone.localdate()
    last_day = today + timedelta(days=MAX_BOOKING_DAYS)
    day, error = today, None
    raw = request.GET.get("date")
    if raw:
        try:
            day = date.fromisoformat(raw)
        except ValueError:
            error = "Date galat hai. Dobara select karo."
            day = today
    if day < today:
        error, day = "Past date ke slots nahi hote. Aaj ki date dikha raha hoon.", today
    slots = []
    if day > last_day:
        error = f"Sirf agle {MAX_BOOKING_DAYS} din ke slots dikh sakte hain."
    else:
        slots = get_available_slots(doctor, day)

    windows = list(doctor.availabilities.all())
    week = [(label, [w for w in windows if w.weekday == value]) for value, label in DoctorAvailability.Weekday.choices]
    return render(request, "patients/doctor_detail.html", {
        "doctor": doctor, "day": day, "slots": slots, "error": error, "week": week,
        "min_date": today.isoformat(), "max_date": last_day.isoformat(),
    })


@role_required("patient")
def medical_records(request):
    records = (MedicalRecord.objects.filter(appointment__patient__user=request.user)
               .select_related("appointment__doctor__user").order_by("-created_at"))
    return render(request, "patients/medical_records.html", {"records": records})


@role_required("patient")
def prescriptions(request):
    items = (Prescription.objects.filter(appointment__patient__user=request.user)
             .select_related("appointment__doctor__user").order_by("-created_at"))
    return render(request, "patients/prescriptions.html", {"prescriptions": items})
