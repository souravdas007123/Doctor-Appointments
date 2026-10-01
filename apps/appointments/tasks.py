"""Beat schedule se chalne wale periodic tasks. Asal logic services.py mein hai (command-line se bhi testable)."""
from celery import shared_task

from . import services


@shared_task
def expire_stale_holds_task():
    return services.expire_stale_holds()


@shared_task
def send_appointment_reminders_task():
    return services.send_due_reminders()
