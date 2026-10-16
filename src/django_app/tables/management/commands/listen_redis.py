from django.core.management.base import BaseCommand
from tables.services.redis_pubsub import RedisPubSub


# TODO: test this.
class Command(BaseCommand):
    help = "Listen for messages on a Redis channel"

    # TODO: reload listen_for_messages if it raises Exception. while True, try, except
    def handle(self, *args, **kwargs):
        RedisPubSub().listen_for_redis_messages_worker()
