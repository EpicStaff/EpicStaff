from django.core.management.base import BaseCommand
from tables.services.dashboard.build_request_consumer import DashboardBuildRequestConsumer


class Command(BaseCommand):
    help = "Build dashboard reports that are due each time manager asks through Redis"

    def handle(self, *args, **kwargs):
        DashboardBuildRequestConsumer.from_settings().run()
