from django.core.management.base import BaseCommand
from tables.services.graph_message_stream_consumer import GraphMessageStreamConsumer


class Command(BaseCommand):
    help = "Store the graph session messages crew streams through Redis"

    def handle(self, *args, **kwargs):
        GraphMessageStreamConsumer.from_settings().run()
