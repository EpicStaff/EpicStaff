from django.core.management.base import BaseCommand
from tables.services.graph_message_stream_consumer import GraphMessageStreamConsumer
from tables.utils.database_connections import keep_database_connections_open


class Command(BaseCommand):
    help = "Store the graph session messages crew streams through Redis"

    def handle(self, *args, **kwargs):
        keep_database_connections_open()
        GraphMessageStreamConsumer.from_settings().run()
