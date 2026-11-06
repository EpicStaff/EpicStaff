from django.core.management.base import BaseCommand
from tables.services.transfer_jobs.consumer import TransferJobConsumer


class Command(BaseCommand):
    help = "Run export and import jobs, and the job sweep, as they arrive through Redis"

    def handle(self, *args, **kwargs):
        TransferJobConsumer.from_settings().run()
