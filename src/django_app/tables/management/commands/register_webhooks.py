from django.core.management.base import BaseCommand

from tables.services.webhook_trigger_service import WebhookTriggerService

class Command(BaseCommand):
    help = "Register webhooks"

    def handle(self, *args, **kwargs):
        WebhookTriggerService().register_webhooks()