"""A temporary storage account belongs to exactly one owner: a session, a code
test run, or a realtime chat (the `exactly_one_fk_is_not_null` constraint)."""

from itertools import combinations

import pytest
from django.db import IntegrityError, transaction

from rbac.models import Organization
from storage_credentials.models import TemporaryStorageAccount
from tables.models import Graph, PythonCodeResult, RealtimeAgentChat, Session

OWNERS = ("session", "python_code_result", "realtime_agent_chat")


@pytest.fixture
def owners(db):
    org = Organization.objects.create(name="Test Organization")
    return {
        "session": Session.objects.create(
            graph=Graph.objects.create(name="test_graph", org=org), status=Session.SessionStatus.RUN
        ),
        "python_code_result": PythonCodeResult.objects.create(org=org, execution_id="test_execution_123"),
        "realtime_agent_chat": RealtimeAgentChat.objects.create(connection_key="test_connection_key"),
    }


@pytest.mark.parametrize(
    "owner_fields",
    [combo for size in range(len(OWNERS) + 1) for combo in combinations(OWNERS, size)],
    ids=lambda combo: "+".join(combo) or "none",
)
def test_an_account_has_exactly_one_owner(owners, owner_fields):
    create = lambda: TemporaryStorageAccount.objects.create(  # noqa: E731
        access_key="test-key", **{field: owners[field] for field in owner_fields}
    )

    if len(owner_fields) == 1:
        assert create().pk is not None
    else:
        with pytest.raises(IntegrityError), transaction.atomic():
            create()
