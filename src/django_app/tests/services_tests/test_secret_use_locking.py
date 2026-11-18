"""`SecretUseCheckedViewSetMixin.secret_use_check_locks_rows`: a check that locks the rows it
reads (`select_for_update`) runs in one transaction with the save, so the locks hold until
the write commits; without the flag the mixin opens no transaction.

pytest-django runs every test inside a transaction, so the savepoints opened inside it
are what tell the two apart.
"""

import pytest
from django.db import connection
from rest_framework import mixins
from tables.views.secret_use import SecretUseCheckedViewSetMixin


class _RecordingSerializer:
    """Stands in for a validated serializer; records the open savepoints when saved."""

    def __init__(self, log: list):
        self._log = log
        self.instance = None
        self.validated_data = {}

    def save(self, **kwargs):
        self._log.append(("save", list(connection.savepoint_ids)))


def _viewset(log: list, *, locks_rows: bool):
    def check(actor, instance, data):
        log.append(("check", list(connection.savepoint_ids)))

    viewset_class = type(
        "_ViewSet",
        (SecretUseCheckedViewSetMixin, mixins.CreateModelMixin, mixins.UpdateModelMixin),
        {"secret_use_check": check, "secret_use_check_locks_rows": locks_rows},
    )
    viewset = viewset_class()
    viewset.request = None
    return viewset


@pytest.mark.django_db
@pytest.mark.parametrize("action", ["create", "update"])
def test_mixin_runs_check_and_save_in_one_atomic_block(action):
    log = []
    savepoints_before = list(connection.savepoint_ids)

    getattr(_viewset(log, locks_rows=True), f"perform_{action}")(_RecordingSerializer(log))

    (check_step, check_savepoints), (save_step, save_savepoints) = log
    assert (check_step, save_step) == ("check", "save")
    # One savepoint opened for the write, and the same one still open at the save.
    assert len(check_savepoints) == len(savepoints_before) + 1
    assert save_savepoints == check_savepoints
    assert list(connection.savepoint_ids) == savepoints_before


@pytest.mark.django_db
@pytest.mark.parametrize("action", ["create", "update"])
def test_mixin_without_row_locks_opens_no_transaction(action):
    # A save with side effects outside the database (a TelegramTriggerNode's post_save
    # calls the Telegram API) must not run inside a transaction the mixin opened.
    log = []
    savepoints_before = list(connection.savepoint_ids)

    getattr(_viewset(log, locks_rows=False), f"perform_{action}")(_RecordingSerializer(log))

    assert log == [("check", savepoints_before), ("save", savepoints_before)]
