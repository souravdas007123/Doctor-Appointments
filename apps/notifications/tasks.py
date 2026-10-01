"""
Celery tasks. Dev mein CELERY_TASK_ALWAYS_EAGER=True hai, isliye Redis/worker ke bina bhi
.delay() call turant, isi process mein chal jaati hai (settings/base.py dekho).
"""
import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail

from .gateways import SMSConfigError, SMSError, get_sms_gateway
from .models import DeliveryAttempt, Notification
from .rules import CHANNELS_BY_TYPE, DEFAULT_CHANNELS

logger = logging.getLogger(__name__)


def _send_email(notification, user):
    if not user.email:
        DeliveryAttempt.objects.create(notification=notification, channel="email", status="skipped", error="No email on file")
        return
    try:
        send_mail(notification.title, notification.message, settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)
        DeliveryAttempt.objects.create(notification=notification, channel="email", status="sent")
    except Exception as exc:  # SMTP ki koi bhi galti user ka flow na roke
        logger.warning("Email notification %s failed: %s", notification.pk, exc)
        DeliveryAttempt.objects.create(notification=notification, channel="email", status="failed", error=str(exc)[:300])


def _send_sms(notification, user):
    if not user.phone:
        DeliveryAttempt.objects.create(notification=notification, channel="sms", status="skipped", error="No phone on file")
        return
    try:
        gateway = get_sms_gateway()
        gateway.send(user.phone, f"{notification.title}: {notification.message}"[:300])
        DeliveryAttempt.objects.create(notification=notification, channel="sms", status="sent")
    except (SMSError, SMSConfigError) as exc:
        logger.warning("SMS notification %s failed: %s", notification.pk, exc)
        DeliveryAttempt.objects.create(notification=notification, channel="sms", status="failed", error=str(exc)[:300])


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_notification_task(self, notification_id):
    try:
        notification = Notification.objects.select_related("recipient").get(pk=notification_id)
    except Notification.DoesNotExist:
        return
    channels = CHANNELS_BY_TYPE.get(notification.notification_type, DEFAULT_CHANNELS)
    user = notification.recipient
    if "email" in channels:
        _send_email(notification, user)
    if "sms" in channels:
        _send_sms(notification, user)
