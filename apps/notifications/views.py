from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Notification


@login_required
def list_notifications(request):
    notifications = request.user.notifications.select_related("appointment")[:50]
    return render(request, "notifications/list.html", {"notifications": notifications})


@require_POST
@login_required
def mark_all_read(request):
    request.user.notifications.filter(is_read=False).update(is_read=True, read_at=timezone.now())
    return redirect("notifications:list")


@login_required
def open_notification(request, pk):
    """Notification ko read mark karke uske appointment par bhej deta hai."""
    notif = get_object_or_404(Notification, pk=pk, recipient=request.user)
    if not notif.is_read:
        notif.is_read = True
        notif.read_at = timezone.now()
        notif.save(update_fields=["is_read", "read_at"])
    if notif.appointment_id:
        return redirect("appointments:detail", pk=notif.appointment_id)
    return redirect("notifications:list")
