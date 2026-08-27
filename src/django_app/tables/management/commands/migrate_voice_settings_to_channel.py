from django.core.management.base import BaseCommand
from django.db import IntegrityError, transaction

from tables.constants.organization_constants import DEFAULT_ORGANIZATION_NAME
from tables.models import Organization, RealtimeChannel, Secret, TwilioChannel, VoiceSettings
from tables.services.secrets.secret_resolver import secret_resolver


class Command(BaseCommand):
    help = (
        "One-time migration of the deprecated global VoiceSettings singleton onto "
        "RealtimeChannel + TwilioChannel. Does not modify or delete VoiceSettings."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Compute and print what would happen without writing to the database.",
        )

    def handle(self, *args, **options):
        dry_run: bool = options["dry_run"]

        voice_settings = VoiceSettings.load()

        if (
            voice_settings.voice_agent_id is None
            and voice_settings.voice_agent_definition_id is None
        ) or voice_settings.twilio_account_sid_secret_id is None:
            self.stdout.write(
                self.style.WARNING(
                    "Nothing to migrate: legacy VoiceSettings has no destination "
                    "agent configured and/or no twilio_account_sid_secret set. "
                    "No changes made."
                )
            )
            return

        if (
            voice_settings.voice_agent_id is not None
            and voice_settings.voice_agent_definition_id is not None
        ):
            self.stderr.write(
                self.style.ERROR(
                    "Legacy VoiceSettings has BOTH voice_agent and "
                    "voice_agent_definition set. A RealtimeChannel may target at "
                    "most one destination. Aborting -- resolve this ambiguity in "
                    "VoiceSettings manually before re-running this command."
                )
            )
            return

        try:
            default_org = Organization.objects.get(name=DEFAULT_ORGANIZATION_NAME)
        except Organization.DoesNotExist:
            self.stderr.write(
                self.style.ERROR(
                    f"Default organization '{DEFAULT_ORGANIZATION_NAME}' does not "
                    "exist. Aborting."
                )
            )
            return

        account_sid_secret: Secret | None = voice_settings.twilio_account_sid_secret
        auth_token_secret: Secret | None = voice_settings.twilio_auth_token_secret

        # The earlier guard (line ~30) only checked the FK id on VoiceSettings.
        # The referenced Secret row could still have been deleted concurrently
        # (on_delete=SET_NULL updates the FK id, but there's a race window
        # between VoiceSettings.load() above and this property access), so we
        # must not assume account_sid_secret is non-None before using it.
        if account_sid_secret is None:
            self.stderr.write(
                self.style.ERROR(
                    "VoiceSettings.twilio_account_sid_secret_id is set but the "
                    "referenced Secret row no longer exists (it may have been "
                    "deleted concurrently with this command running). Aborting "
                    "-- re-run this command to re-evaluate the current state."
                )
            )
            return

        # Secrets that need `org` reassigned before account_sid can be
        # resolved (secret_resolver.resolve() scopes its query by org_id).
        # In dry-run mode nothing is appended here -- we only print intent.
        reassignments: list[Secret] = []
        for label, secret in (
            ("twilio_account_sid_secret", account_sid_secret),
            ("twilio_auth_token_secret", auth_token_secret),
        ):
            if secret is None:
                continue
            if secret.org_id == default_org.id:
                self.stdout.write(
                    f"{label} (Secret id={secret.id}) already belongs to org "
                    f"'{default_org.name}' -- no reassignment needed."
                )
            else:
                self.stdout.write(
                    f"{label} (Secret id={secret.id}) belongs to org_id="
                    f"{secret.org_id} -- {'would reassign' if dry_run else 'reassigning'} "
                    f"to org '{default_org.name}' (id={default_org.id})."
                )
                if not dry_run:
                    secret.org = default_org
                    reassignments.append(secret)

        if dry_run:
            destination = (
                f"realtime_agent id={voice_settings.voice_agent_id}"
                if voice_settings.voice_agent_id is not None
                else f"realtime_agent_definition id={voice_settings.voice_agent_definition_id}"
            )
            self.stdout.write(
                "Dry-run: would create RealtimeChannel(name='Migrated from legacy "
                f"VoiceSettings', org='{default_org.name}', {destination}, "
                "is_active=True) and a linked TwilioChannel(account_sid=<resolved "
                f"from Secret id={account_sid_secret.id}, name={account_sid_secret.name!r}>, "
                f"auth_token_secret_id={auth_token_secret.id if auth_token_secret else None})."
            )
            self.stdout.write(
                "Dry-run: plaintext account_sid is not resolved or printed here "
                "to avoid leaking credentials into command output/logs -- verify "
                f"the value by name (Secret id={account_sid_secret.id}, "
                f"name={account_sid_secret.name!r}) if needed."
            )
            self.stdout.write(
                self.style.SUCCESS(
                    "Dry-run complete. No database rows were created or modified."
                )
            )
            return

        # Everything that writes to the database -- Secret org reassignment
        # AND RealtimeChannel/TwilioChannel creation -- must be one atomic
        # unit. If channel creation fails after secrets were reassigned (or
        # vice versa), a rerun would see a half-migrated state.
        current_secret: Secret | None = None

        def _do_migration():
            nonlocal current_secret
            for secret in reassignments:
                current_secret = secret
                secret.save(update_fields=["org"])
            current_secret = None

            account_sid = secret_resolver.resolve(
                secret_id=account_sid_secret.id,
                org_id=default_org.id,
                context="VoiceSettings.twilio_account_sid",
            )

            channel = RealtimeChannel.objects.create(
                name="Migrated from legacy VoiceSettings",
                org=default_org,
                realtime_agent=voice_settings.voice_agent,
                realtime_agent_definition=voice_settings.voice_agent_definition,
                is_active=True,
            )
            TwilioChannel.objects.create(
                channel=channel,
                account_sid=account_sid,
                auth_token_secret=auth_token_secret,
            )
            return channel

        # The IntegrityError catch is deliberately OUTSIDE transaction.atomic():
        # an exception raised inside atomic() marks the transaction as broken,
        # so we let atomic()'s own exception propagation trigger the rollback
        # first, then catch here purely to print an operator-facing message
        # and exit cleanly (no partial writes either way).
        try:
            with transaction.atomic():
                channel = _do_migration()
        except IntegrityError as exc:
            if current_secret is not None:
                self.stderr.write(
                    self.style.ERROR(
                        f"Cannot reassign Secret id={current_secret.id} "
                        f"name={current_secret.name!r} to org "
                        f"'{default_org.name}' (id={default_org.id}): a Secret "
                        "with that name already exists in the target org "
                        "(unique_secret_name_per_org constraint). Aborting -- "
                        "no changes were made. Resolve the naming collision "
                        "manually before re-running this command."
                    )
                )
            else:
                self.stderr.write(
                    self.style.ERROR(
                        f"Migration failed due to a database integrity error: "
                        f"{exc}. Aborting -- no changes were made."
                    )
                )
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Migration complete. New channel_token: {channel.token}"
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Next step: repoint the Twilio phone number's voice webhook to "
                f"/voice/{channel.token} (via the configure-webhook/ endpoint or "
                "the Twilio console). The legacy VoiceSettings row was left untouched."
            )
        )
