from datetime import timedelta

from django.db import migrations
from django.db.models import F, Max, OuterRef, Subquery
from django.db.models.functions import Coalesce

TERMINAL_STATUSES = ["end", "error", "expired", "stop"]


def backfill_finished_at(apps, schema_editor):
    Session = apps.get_model("tables", "Session")
    GraphSessionMessage = apps.get_model("tables", "GraphSessionMessage")

    last_message_created_at = (
        GraphSessionMessage.objects.filter(session_id=OuterRef("pk"))
        .values("session_id")
        .annotate(last_created_at=Max("created_at"))
        .values("last_created_at")
    )
    Session.objects.filter(
        status__in=TERMINAL_STATUSES, finished_at__isnull=True
    ).update(finished_at=Coalesce(Subquery(last_message_created_at), F("created_at")))

    Session.objects.filter(finished_at=F("created_at")).update(
        finished_at=F("created_at") + timedelta(minutes=1)
    )


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0250_alter_sessionprincipal_api_key_alter_agent_org_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_finished_at, migrations.RunPython.noop),
    ]
