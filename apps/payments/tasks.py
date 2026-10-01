"""Beat schedule se chalne wala periodic task. Asal logic services.py mein hai."""
from celery import shared_task

from .models import Refund
from . import services


@shared_task
def process_pending_refunds_task():
    ids = list(Refund.objects.filter(status=Refund.Status.PENDING, gateway_refund_id__isnull=True).values_list("pk", flat=True))
    for pk in ids:
        services.process_refund(pk)
    return len(ids)
