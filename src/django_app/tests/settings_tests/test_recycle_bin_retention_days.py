import pytest
from django.core.exceptions import ImproperlyConfigured

from django_app.settings.base import read_recycle_bin_retention_days
from src.shared.envtools import Env, EnvironmentNotFoundError

# Same reason as test_env_bool.py: nothing here touches the database, but the
# session-scoped autouse flush in tests/conftest.py needs the test database set up.
pytestmark = pytest.mark.django_db

VARIABLE = "DJANGO_RECYCLE_BIN_RETENTION_DAYS"
MESSAGE = "DJANGO_RECYCLE_BIN_RETENTION_DAYS must be a whole number, at least 1."


@pytest.mark.parametrize(("value", "expected"), [("1", 1), ("30", 30), (" 7 ", 7)])
def test_reads_a_whole_number_of_days(value, expected):
    assert read_recycle_bin_retention_days(Env({VARIABLE: value})) == expected


@pytest.mark.parametrize("value", ["abc", "", "1.5", "0", "-1", "none"])
def test_rejects_a_value_that_is_not_a_whole_number_of_at_least_one(value):
    with pytest.raises(ImproperlyConfigured) as error:
        read_recycle_bin_retention_days(Env({VARIABLE: value}))

    assert str(error.value) == MESSAGE


def test_a_missing_variable_still_names_itself():
    with pytest.raises(EnvironmentNotFoundError, match=VARIABLE):
        read_recycle_bin_retention_days(Env({}))
