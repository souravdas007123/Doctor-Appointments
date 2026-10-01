from django.db import transaction

from .models import Notification
from .tasks import send_notification_task


def notify(user, notification_type, title, message="", appointment=None):
    """In-app notification turant banti hai; email/SMS commit ke baad async (ya eager mode mein turant) jaati hai."""
    notification = Notification.objects.create(
        recipient=user, notification_type=notification_type, title=title[:150], message=message[:500], appointment=appointment)
    transaction.on_commit(lambda: send_notification_task.delay(notification.pk))
    return notification
