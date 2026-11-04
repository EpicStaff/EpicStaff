from django.core.management.base import BaseCommand
from tables.services.recycle_bin.purge_request_consumer import RecycleBinPurgeRequestConsumer


class Command(BaseCommand):
    help = "Run the recycle-bin purge each time manager requests it through Redis"

    def handle(self, *args, **kwargs):
        RecycleBinPurgeRequestConsumer.from_settings().run()
