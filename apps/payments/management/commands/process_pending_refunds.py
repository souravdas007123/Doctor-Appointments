from django.core.management.base import BaseCommand

from apps.payments import services
from apps.payments.models import Refund


class Command(BaseCommand):
    help = "PENDING refunds ko gateway ko bhejta hai (cron/scheduler se har few minutes chalao)."

    def handle(self, *args, **options):
        ids = list(Refund.objects.filter(status=Refund.Status.PENDING, gateway_refund_id__isnull=True).values_list("pk", flat=True))
        for pk in ids:
            services.process_refund(pk)
        self.stdout.write(f"{len(ids)} pending refund(s) process kiye.")
