from django.contrib import admin

from .models import AuditLog, MedicalRecord, Prescription, PrescriptionItem


class PrescriptionItemInline(admin.TabularInline):
    model = PrescriptionItem
    extra = 0


@admin.register(MedicalRecord)
class MedicalRecordAdmin(admin.ModelAdmin):
    list_display = ("appointment", "created_by", "follow_up_date", "created_at")
    search_fields = ("appointment__patient__user__email", "appointment__doctor__user__email")
    readonly_fields = ("created_by", "created_at", "updated_at")


@admin.register(Prescription)
class PrescriptionAdmin(admin.ModelAdmin):
    list_display = ("appointment", "created_by", "follow_up_days", "created_at")
    inlines = [PrescriptionItemInline]
    readonly_fields = ("created_by", "created_at", "updated_at")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "action", "appointment", "ip_address")
    list_filter = ("action",)
    search_fields = ("user__email",)
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
