from django.core.management.base import BaseCommand

from plugins.identity.signing_keys import RETIRED_KEY_RETENTION, PluginSigningKeyService


class Command(BaseCommand):
    help = (
        "Make a new key sign plugin gateway contexts. The previous keys are retired and stay "
        "in the published key set for 24 hours."
    )

    def handle(self, *args, **options):
        created = PluginSigningKeyService().rotate()
        hours = int(RETIRED_KEY_RETENTION.total_seconds() // 3600)
        self.stdout.write(
            f"Plugin contexts are now signed with key {created.kid}; "
            f"the previous keys stay published for {hours} hours."
        )
