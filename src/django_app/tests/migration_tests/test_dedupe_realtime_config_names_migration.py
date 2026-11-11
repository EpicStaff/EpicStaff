"""tables 0291 renames same-named realtime provider configs of one org so the unique
constraint added by 0292 can be created. The oldest row keeps its name."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from tables.migrations._helpers import plan_duplicate_renames

BEFORE = [("tables", "0290_systemoneconfig_openai_provider")]
AFTER = [("tables", "0291_dedupe_realtime_config_names")]


@pytest.mark.parametrize(
    "rows, max_length, expected",
    [
        pytest.param([(1, "a"), (2, "b")], 250, {}, id="no_duplicates"),
        pytest.param(
            [(1, "a"), (2, "a"), (3, "a")], 250, {2: "a (2)", 3: "a (3)"}, id="triplicate"
        ),
        pytest.param([(5, "a"), (3, "a")], 250, {5: "a (2)"}, id="lowest_pk_keeps_name"),
        pytest.param(
            [(1, "a"), (2, "a"), (3, "a (2)")], 250, {2: "a (3)"}, id="skips_taken_suffix"
        ),
        pytest.param([(1, "abcdef"), (2, "abcdef")], 9, {2: "abcde (2)"}, id="truncates_base"),
        pytest.param([(1, "A"), (2, "a")], 250, {}, id="case_sensitive"),
    ],
)
def test_plan_duplicate_renames(rows, max_length, expected):
    assert plan_duplicate_renames(rows, max_length=max_length) == expected


def _migrate(targets):
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


def _migrate_to_latest():
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


@pytest.mark.django_db(transaction=True)
def test_duplicate_names_are_renamed_per_org_and_table_oldest_keeps_name():
    try:
        old_apps = _migrate(BEFORE)
        organization_model = old_apps.get_model("rbac", "Organization")
        first_org = organization_model.objects.create(name="dedupe-org-1")
        second_org = organization_model.objects.create(name="dedupe-org-2")
        openai_model = old_apps.get_model("tables", "OpenAIRealtimeConfig")
        gemini_model = old_apps.get_model("tables", "GeminiRealtimeConfig")

        oldest = openai_model.objects.create(custom_name="voice", org=first_org)
        newer = openai_model.objects.create(custom_name="voice", org=first_org)
        newest = openai_model.objects.create(custom_name="voice", org=first_org)
        already_suffixed = openai_model.objects.create(custom_name="voice (2)", org=first_org)
        other_org = openai_model.objects.create(custom_name="voice", org=second_org)
        other_table = gemini_model.objects.create(custom_name="voice", org=first_org)

        new_apps = _migrate(AFTER)
        names = {
            row.pk: row.custom_name
            for row in new_apps.get_model("tables", "OpenAIRealtimeConfig").objects.all()
        }

        assert names == {
            oldest.pk: "voice",
            newer.pk: "voice (3)",
            newest.pk: "voice (4)",
            already_suffixed.pk: "voice (2)",
            other_org.pk: "voice",
        }
        assert (
            new_apps.get_model("tables", "GeminiRealtimeConfig")
            .objects.get(pk=other_table.pk)
            .custom_name
            == "voice"
        )
    finally:
        _migrate_to_latest()


@pytest.mark.django_db(transaction=True)
def test_elevenlabs_duplicates_are_renamed():
    try:
        old_apps = _migrate(BEFORE)
        organization = old_apps.get_model("rbac", "Organization").objects.create(
            name="dedupe-org-elevenlabs"
        )
        elevenlabs_model = old_apps.get_model("tables", "ElevenLabsRealtimeConfig")
        oldest = elevenlabs_model.objects.create(custom_name="voice", org=organization)
        newer = elevenlabs_model.objects.create(custom_name="voice", org=organization)

        new_apps = _migrate(AFTER)

        names = {
            row.pk: row.custom_name
            for row in new_apps.get_model("tables", "ElevenLabsRealtimeConfig").objects.all()
        }
        assert names == {oldest.pk: "voice", newer.pk: "voice (2)"}
    finally:
        _migrate_to_latest()


@pytest.mark.django_db(transaction=True)
def test_a_max_length_duplicate_name_is_renamed_within_the_column_limit():
    try:
        old_apps = _migrate(BEFORE)
        organization = old_apps.get_model("rbac", "Organization").objects.create(
            name="dedupe-org-long"
        )
        gemini_model = old_apps.get_model("tables", "GeminiRealtimeConfig")
        long_name = "x" * 250
        oldest = gemini_model.objects.create(custom_name=long_name, org=organization)
        newer = gemini_model.objects.create(custom_name=long_name, org=organization)

        new_apps = _migrate(AFTER)

        renamed = (
            new_apps.get_model("tables", "GeminiRealtimeConfig")
            .objects.get(pk=newer.pk)
            .custom_name
        )
        assert renamed == "x" * 246 + " (2)"
        assert len(renamed) == 250
        assert (
            new_apps.get_model("tables", "GeminiRealtimeConfig")
            .objects.get(pk=oldest.pk)
            .custom_name
            == long_name
        )
    finally:
        _migrate_to_latest()
