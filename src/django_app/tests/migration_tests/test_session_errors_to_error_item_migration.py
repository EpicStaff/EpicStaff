"""tables 0297 rewrites saved session errors into error items {code, detail, attr, context}.

Invariants: an error card's `details`, an older card's plain `error` and a session's plain
`status_data.error` become an item with code `unknown`; a non-empty string is kept word for word as `detail`, any other
value gets a fixed text. Rows of other message types and errors already stored as items
are not touched, a second run changes nothing, and going back restores the plain text.
"""

import uuid
from importlib import import_module

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

BEFORE = ("tables", "0296_merge_20261118_1445")
AFTER = ("tables", "0297_session_errors_to_error_item")
migration_module = import_module(f"tables.migrations.{AFTER[1]}")

OLDER_FORMAT_DETAIL = "This error was recorded in an older format."


def _migrate(target):
    MigrationExecutor(connection).migrate([target])
    return MigrationExecutor(connection).loader.project_state([target]).apps


def _unknown_item(detail):
    return {"code": "unknown", "detail": detail, "attr": None, "context": None}


@pytest.fixture
def restore_latest_schema():
    yield
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


@pytest.fixture
def before_apps(restore_latest_schema):
    return _migrate(BEFORE)


class _Rows:
    def __init__(self, apps):
        self.session_model = apps.get_model("tables", "Session")
        self.message_model = apps.get_model("tables", "GraphSessionMessage")

    def session(self, status_data=None):
        return self.session_model.objects.create(
            status="error", status_updated_at=timezone.now(), status_data=status_data or {}
        ).pk

    def message(self, session_id, message_data):
        return self.message_model.objects.create(
            session_id=session_id,
            created_at=timezone.now(),
            message_data=message_data,
            uuid=uuid.uuid4(),
        ).pk

    def message_data(self, message_id):
        return self.message_model.objects.get(pk=message_id).message_data

    def status_data(self, session_id):
        return self.session_model.objects.get(pk=session_id).status_data


@pytest.mark.django_db(transaction=True)
def test_string_details_become_the_detail_of_an_unknown_item(before_apps):
    rows = _Rows(before_apps)
    session_id = rows.session()
    message_id = rows.message(
        session_id,
        {
            "message_type": "error",
            "details": 'Node "Save lead #3" failed. (reference: 4f2a)',
            "subgraph_execution_ids": ["run-1"],
        },
    )

    rows = _Rows(_migrate(AFTER))

    assert rows.message_data(message_id) == {
        "message_type": "error",
        "error": _unknown_item('Node "Save lead #3" failed. (reference: 4f2a)'),
        "subgraph_execution_ids": ["run-1"],
    }


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "details",
    [
        pytest.param({"error": "Traceback ...", "host": "10.0.0.5"}, id="object"),
        pytest.param(["first", "second"], id="list"),
        pytest.param(None, id="null"),
        pytest.param("", id="empty-string"),
        pytest.param(42, id="number"),
    ],
)
def test_details_that_are_not_a_non_empty_string_get_the_fixed_text(before_apps, details):
    rows = _Rows(before_apps)
    message_id = rows.message(rows.session(), {"message_type": "error", "details": details})

    rows = _Rows(_migrate(AFTER))

    assert rows.message_data(message_id) == {
        "message_type": "error",
        "error": _unknown_item(OLDER_FORMAT_DETAIL),
    }


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("old_error", "expected_detail"),
    [
        pytest.param("Variable 'x' is not defined", "Variable 'x' is not defined", id="string"),
        pytest.param("", OLDER_FORMAT_DETAIL, id="empty-string"),
        pytest.param(None, OLDER_FORMAT_DETAIL, id="null"),
        pytest.param(["boom"], OLDER_FORMAT_DETAIL, id="list"),
        pytest.param(42, OLDER_FORMAT_DETAIL, id="number"),
    ],
)
def test_an_older_card_with_a_plain_error_becomes_an_unknown_item(before_apps, old_error, expected_detail):
    rows = _Rows(before_apps)
    message_id = rows.message(
        rows.session(), {"message_type": "error", "error": old_error, "subgraph_execution_ids": ["run-1"]}
    )

    rows = _Rows(_migrate(AFTER))

    assert rows.message_data(message_id) == {
        "message_type": "error",
        "error": _unknown_item(expected_detail),
        "subgraph_execution_ids": ["run-1"],
    }


@pytest.mark.django_db(transaction=True)
def test_rows_that_are_not_old_error_cards_are_not_touched(before_apps):
    rows = _Rows(before_apps)
    session_id = rows.session()
    untouched = {
        rows.message(session_id, data): data
        for data in (
            {"message_type": "finish", "details": "not an error card", "output": 1},
            {"message_type": "python", "python_code_execution_data": {"stderr": "boom"}},
            {"message_type": "extracted_chunks", "error": "search timed out", "chunks": []},
            {
                "message_type": "error",
                "error": {"code": "node_failed", "detail": 'Node "a" failed.', "attr": None, "context": None},
            },
            {"output_map": {"result": 1}},
        )
    }

    rows = _Rows(_migrate(AFTER))

    assert {message_id: rows.message_data(message_id) for message_id in untouched} == untouched


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("old_error", "expected_detail"),
    [
        pytest.param("The flow failed.", "The flow failed.", id="string"),
        pytest.param("", OLDER_FORMAT_DETAIL, id="empty-string"),
        pytest.param(None, OLDER_FORMAT_DETAIL, id="null"),
        pytest.param(["boom"], OLDER_FORMAT_DETAIL, id="list"),
    ],
)
def test_a_plain_session_status_error_becomes_an_unknown_item(before_apps, old_error, expected_detail):
    rows = _Rows(before_apps)
    session_id = rows.session({"error": old_error, "total_token_usage": 12})

    rows = _Rows(_migrate(AFTER))

    assert rows.status_data(session_id) == {
        "error": _unknown_item(expected_detail),
        "total_token_usage": 12,
    }


@pytest.mark.django_db(transaction=True)
def test_session_status_without_a_plain_error_is_not_touched(before_apps):
    rows = _Rows(before_apps)
    item = {"code": "flow_failed", "detail": "The flow failed.", "attr": None, "context": None}
    untouched = {
        rows.session(status_data): status_data
        for status_data in (
            {"variables": {"city": "Berlin"}, "total_token_usage": 3},
            {"reason": "stopped by the user"},
            {"error": item},
            {},
        )
    }

    rows = _Rows(_migrate(AFTER))

    assert {session_id: rows.status_data(session_id) for session_id in untouched} == untouched


@pytest.mark.django_db(transaction=True)
def test_running_the_migration_again_changes_nothing(before_apps):
    rows = _Rows(before_apps)
    session_id = rows.session({"error": "The flow failed."})
    message_ids = [
        rows.message(session_id, {"message_type": "error", "details": {"raw": "x"}}),
        rows.message(session_id, {"message_type": "error", "error": "The node timed out."}),
    ]
    after_apps = _migrate(AFTER)
    rows = _Rows(after_apps)
    migrated = ([rows.message_data(message_id) for message_id in message_ids], rows.status_data(session_id))

    with connection.schema_editor(atomic=False) as schema_editor:
        migration_module.errors_to_error_items(after_apps, schema_editor)

    assert ([rows.message_data(message_id) for message_id in message_ids], rows.status_data(session_id)) == migrated


@pytest.mark.django_db(transaction=True)
def test_every_row_is_migrated_across_several_id_ranges(before_apps, monkeypatch):
    monkeypatch.setattr(migration_module, "BATCH_SIZE", 2)
    rows = _Rows(before_apps)
    session_ids = []
    message_ids = []
    for index in range(5):
        session_id = rows.session({"error": f"failure {index}"})
        session_ids.append(session_id)
        message_ids.append(rows.message(session_id, {"message_type": "error", "details": f"failure {index}"}))
        # Rows that are not errors sit between the error rows, so ranges hold a mix.
        rows.message(session_id, {"message_type": "start", "input": {}})

    rows = _Rows(_migrate(AFTER))

    assert [rows.message_data(message_id)["error"]["detail"] for message_id in message_ids] == [
        f"failure {index}" for index in range(5)
    ]
    assert [rows.status_data(session_id)["error"]["detail"] for session_id in session_ids] == [
        f"failure {index}" for index in range(5)
    ]


@pytest.mark.django_db(transaction=True)
def test_rows_after_an_id_gap_wider_than_one_range_are_migrated(before_apps, monkeypatch):
    monkeypatch.setattr(migration_module, "BATCH_SIZE", 2)
    rows = _Rows(before_apps)
    session_ids = [rows.session({"error": f"failure {index}"}) for index in range(8)]
    message_ids = [
        rows.message(session_id, {"message_type": "error", "details": f"failure {index}"})
        for index, session_id in enumerate(session_ids)
    ]
    # Leaves a gap of five ids in each table, so whole ranges between the ends hold no rows.
    rows.session_model.objects.filter(pk__in=session_ids[1:6]).delete()
    rows.message_model.objects.filter(pk__in=message_ids[1:6]).delete()
    kept = [0, 6, 7]

    rows = _Rows(_migrate(AFTER))

    expected = [_unknown_item(f"failure {index}") for index in kept]
    assert [rows.message_data(message_ids[index])["error"] for index in kept] == expected
    assert [rows.status_data(session_ids[index])["error"] for index in kept] == expected


@pytest.mark.django_db(transaction=True)
def test_going_back_restores_the_error_text(before_apps):
    rows = _Rows(before_apps)
    session_id = rows.session({"error": "The flow failed.", "total_token_usage": 7})
    string_card = rows.message(session_id, {"message_type": "error", "details": "Variable 'x' is not defined"})
    object_card = rows.message(session_id, {"message_type": "error", "details": {"raw": "secret"}})
    plain_error_card = rows.message(session_id, {"message_type": "error", "error": "The node timed out."})
    _migrate(AFTER)
    # Written by the new crew after the migration, with its own code.
    new_card = rows.message(
        session_id,
        {
            "message_type": "error",
            "error": {"code": "node_failed", "detail": 'Node "a" failed.', "attr": None, "context": None},
        },
    )

    rows = _Rows(_migrate(BEFORE))

    assert rows.message_data(string_card) == {
        "message_type": "error",
        "details": "Variable 'x' is not defined",
    }
    # The original structure is gone: it comes back as the fixed text.
    assert rows.message_data(object_card) == {"message_type": "error", "details": OLDER_FORMAT_DETAIL}
    # An older plain-error card comes back in the `details` shape, not as a plain `error`.
    assert rows.message_data(plain_error_card) == {"message_type": "error", "details": "The node timed out."}
    assert rows.message_data(new_card) == {"message_type": "error", "details": 'Node "a" failed.'}
    assert rows.status_data(session_id) == {"error": "The flow failed.", "total_token_usage": 7}


@pytest.mark.django_db(transaction=True)
def test_going_back_keeps_a_session_error_item_without_detail_as_null(before_apps):
    rows = _Rows(before_apps)
    session_id = rows.session()
    _migrate(AFTER)
    rows.session_model.objects.filter(pk=session_id).update(status_data={"error": {"code": "flow_failed"}})

    rows = _Rows(_migrate(BEFORE))

    assert rows.status_data(session_id) == {"error": None}


@pytest.mark.django_db(transaction=True)
def test_going_back_keeps_an_error_card_item_without_detail_as_null(before_apps):
    rows = _Rows(before_apps)
    message_id = rows.message(rows.session(), {"message_type": "start", "input": {}})
    _migrate(AFTER)
    rows.message_model.objects.filter(pk=message_id).update(
        message_data={"message_type": "error", "error": {"code": "node_failed"}}
    )

    rows = _Rows(_migrate(BEFORE))

    # JSON null inside the object, never a NULL column.
    assert rows.message_data(message_id) == {"message_type": "error", "details": None}
