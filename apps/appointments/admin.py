from django.contrib import admin

from .models import Appointment, AppointmentStatusHistory


class HistoryInline(admin.TabularInline):
    model = AppointmentStatusHistory
    extra = 0
    can_delete = False
    readonly_fields = ("from_status", "to_status", "changed_by", "note", "created_at")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ("id", "doctor", "patient", "appointment_date", "start_time", "status", "consultation_fee")
    list_filter = ("status", "appointment_date")
    search_fields = ("doctor__user__email", "patient__user__email")
    inlines = [HistoryInline]
