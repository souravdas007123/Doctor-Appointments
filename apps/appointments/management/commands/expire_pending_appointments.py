from django.core.management.base import BaseCommand

from apps.appointments.services import expire_stale_holds


class Command(BaseCommand):
    help = "Payment window nikal chuki PENDING appointments ko EXPIRED karke slot free karta hai."

    def handle(self, *args, **options):
        self.stdout.write(f"{expire_stale_holds()} hold(s) expire kiye.")
