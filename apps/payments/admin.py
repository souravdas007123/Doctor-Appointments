from django.contrib import admin, messages

from . import services
from .models import Payment, Refund, WebhookEvent


class RefundInline(admin.TabularInline):
    model = Refund
    extra = 0
    can_delete = False
    readonly_fields = ("amount", "status", "gateway_refund_id", "reason", "failure_reason", "created_at", "processed_at")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("gateway_order_id", "appointment", "amount", "status", "paid_at", "created_at")
    list_filter = ("status",)
    search_fields = ("gateway_order_id", "gateway_payment_id", "patient__user__email")
    readonly_fields = [f.name for f in Payment._meta.fields]
    inlines = [RefundInline]

    def has_add_permission(self, request):
        return False


@admin.register(Refund)
class RefundAdmin(admin.ModelAdmin):
    list_display = ("id", "payment", "amount", "status", "failure_reason", "created_at")
    list_filter = ("status",)
    actions = ["retry_pending"]

    @admin.action(description="Pending refunds dobara gateway ko bhejo")
    def retry_pending(self, request, queryset):
        n = 0
        for refund in queryset.filter(status=Refund.Status.PENDING):
            services.process_refund(refund.pk)
            n += 1
        self.message_user(request, f"{n} refund(s) process kiye.", messages.INFO)


admin.site.register(WebhookEvent)
