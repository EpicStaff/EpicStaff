from django.core.management.base import BaseCommand
from tables.services.session_callbacks.sender import SessionCallbackSender


class Command(BaseCommand):
    help = "Deliver pending session completion callbacks with retries."

    def handle(self, *args, **options):
        SessionCallbackSender().run_forever()
