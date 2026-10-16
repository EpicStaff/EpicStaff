from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from tables.models import Graph


@pytest.mark.django_db
def test_prints_what_it_purged_then_nothing(default_org, settings):
    settings.RECYCLE_BIN_RETENTION_DAYS = 7
    for name in ("One", "Two"):
        graph = Graph.objects.create(org=default_org, name=name)
        graph.delete()
        Graph.all_objects.filter(pk=graph.pk).update(soft_deleted_at=timezone.now() - timedelta(days=8))

    first, second = StringIO(), StringIO()
    call_command("purge_recycle_bin", stdout=first)
    call_command("purge_recycle_bin", stdout=second)

    assert "Purged 2 tables.Graph" in first.getvalue()
    assert "Nothing to purge." in second.getvalue()
