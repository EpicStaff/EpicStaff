from django.core.management.base import BaseCommand
from tables.services.transfer_jobs.consumer import LANE_CONSUMERS
from tables.services.transfer_jobs.export_definitions import TransferLane


class Command(BaseCommand):
    help = (
        "Run export and import jobs of one lane as they arrive through Redis; "
        "the heavy lane also runs the job sweep"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--lane",
            choices=[lane.value for lane in TransferLane],
            default=TransferLane.HEAVY.value,
        )

    def handle(self, *args, lane: str, **kwargs):
        LANE_CONSUMERS[TransferLane(lane)].from_settings().run()
