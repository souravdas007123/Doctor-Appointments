from django.core.management.base import BaseCommand

from apps.appointments.services import send_due_reminders


class Command(BaseCommand):
    help = "Jinki appointment REMINDER_HOURS_BEFORE ke andar hai unhe reminder bhejta hai (cron/scheduler se chalao)."

    def handle(self, *args, **options):
        self.stdout.write(f"{send_due_reminders()} reminder(s) bheje.")
