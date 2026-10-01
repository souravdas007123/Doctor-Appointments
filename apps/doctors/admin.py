from django.contrib import admin
from django.utils import timezone

from .models import DoctorAvailability, DoctorBlockedSlot, DoctorProfile, Specialization


@admin.register(Specialization)
class SpecializationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    search_fields = ("name",)


@admin.register(DoctorProfile)
class DoctorProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "specialization", "city", "is_verified", "created_at")
    list_filter = ("is_verified", "specialization")
    search_fields = ("user__email", "user__first_name", "license_number")
    actions = ["approve_doctors"]

    @admin.action(description="Selected doctors ko verify karo")
    def approve_doctors(self, request, queryset):
        queryset.update(is_verified=True, verified_at=timezone.now())


@admin.register(DoctorAvailability)
class DoctorAvailabilityAdmin(admin.ModelAdmin):
    list_display = ("doctor", "weekday", "start_time", "end_time")
    list_filter = ("weekday",)


@admin.register(DoctorBlockedSlot)
class DoctorBlockedSlotAdmin(admin.ModelAdmin):
    list_display = ("doctor", "date", "start_time", "end_time", "reason")
    list_filter = ("date",)
