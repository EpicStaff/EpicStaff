import pytest


@pytest.fixture(scope="session", autouse=True)
def flush_test_db_once():
    pass
