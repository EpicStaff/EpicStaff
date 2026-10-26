"""A plugin database's own settings, as stored and as set again after a restore."""

import pytest
from psycopg import sql

from es_plugins.database.backup_store import SettingEntry
from es_plugins.database.database_settings import (
    MAX_SETTING_NAME_LENGTH,
    DatabaseSetting,
    read_database_settings,
    setting_statement,
    split_list_setting,
)


@pytest.mark.parametrize(
    ("stored", "elements"),
    [
        ('"app, public"', ["app, public"]),
        ("app, public", ["app", "public"]),
        ('"$user", public', ["$user", "public"]),
        ('"we""ird", x', ['we"ird', "x"]),
        ("  a  ,b  ", ["a", "b"]),
        ('""', [""]),
        ("", []),
    ],
)
def test_a_stored_list_setting_is_split_into_its_elements(stored, elements):
    assert split_list_setting(stored) == elements


@pytest.mark.parametrize("stored", ['"unterminated', "a,", "a b", ",a", "a,,b"])
def test_a_stored_list_setting_that_is_not_a_list_is_not_split(stored):
    assert split_list_setting(stored) is None


def render(statement) -> str:
    # Composed SQL renders without a connection for identifiers and string literals.
    return statement.as_string(None)


def test_a_list_setting_is_set_again_element_by_element():
    statement = setting_statement(sql.Identifier("plugin_weather"), DatabaseSetting("search_path", '"$user", weather'))

    assert render(statement) == "ALTER DATABASE \"plugin_weather\" SET \"search_path\" = '$user', 'weather'"


def test_any_other_setting_is_set_again_as_one_literal():
    statement = setting_statement(sql.Identifier("plugin_weather"), DatabaseSetting("statement_timeout", "5s"))

    assert render(statement) == "ALTER DATABASE \"plugin_weather\" SET \"statement_timeout\" = '5s'"


def test_a_dotted_name_is_set_part_by_part():
    statement = setting_statement(sql.Identifier("plugin_weather"), DatabaseSetting("weather.mode", "x"))

    assert render(statement) == "ALTER DATABASE \"plugin_weather\" SET \"weather\".\"mode\" = 'x'"


@pytest.mark.parametrize("name", ["Search_Path", "search path", "a;b", "a..b", ".a", "a.", "1a"])
def test_a_name_that_is_not_a_setting_name_is_skipped(name):
    assert setting_statement(sql.Identifier("plugin_weather"), DatabaseSetting(name, "x")) is None


def test_a_list_setting_that_cannot_be_split_is_skipped():
    assert setting_statement(sql.Identifier("plugin_weather"), DatabaseSetting("search_path", '"open')) is None


class _Rows:
    """An admin session that answers the settings query with `entries`."""

    def __init__(self, entries):
        self._entries = entries

    async def execute(self, query, parameters):
        return self

    async def fetchall(self):
        return [(entry,) for entry in self._entries]


async def test_a_name_longer_than_a_backup_keeps_is_skipped_and_counted():
    long_name = "a" * (MAX_SETTING_NAME_LENGTH + 1)
    entries = [f"{long_name}=1", f"{'b' * MAX_SETTING_NAME_LENGTH}=2", "work_mem=8MB"]

    read = await read_database_settings(_Rows(entries), "plugin_weather")

    assert [setting.name for setting in read.settings] == ["b" * MAX_SETTING_NAME_LENGTH, "work_mem"]
    assert read.skipped == 1
    # Whatever is read fits a backup's metadata.
    assert [SettingEntry(name=setting.name, value=setting.value) for setting in read.settings]
