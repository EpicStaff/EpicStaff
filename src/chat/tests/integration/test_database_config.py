import pytest
from common.logging import error_summary
from infrastructure.database.config import make_engine
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

SECRET = "desk-identity-secret-0123456789"


async def test_a_failed_statement_does_not_quote_its_bound_values(settings):
    engine = make_engine(settings.database_url)
    try:
        # Postgres text cannot hold U+0000, so this fails exactly as a binding write with one would.
        with pytest.raises(DBAPIError) as raised:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT CAST(:secret AS text)"), {"secret": SECRET + "\x00"})
    finally:
        await engine.dispose()
    assert SECRET not in str(raised.value)


async def test_a_constraint_violation_is_summarized_by_sqlstate_and_constraint_without_its_values(settings):
    engine = make_engine(settings.database_url)
    try:
        with pytest.raises(DBAPIError) as raised:
            async with engine.connect() as connection:
                await connection.execute(text("CREATE TEMP TABLE desk (secret text CONSTRAINT uq_desk_secret UNIQUE)"))
                for _ in range(2):
                    await connection.execute(text("INSERT INTO desk VALUES (:secret)"), {"secret": SECRET})
    finally:
        await engine.dispose()
    # The server's own text quotes the duplicate value: "Key (secret)=(...) already exists".
    assert SECRET in str(raised.value.orig)
    assert error_summary(raised.value) == "IntegrityError (sqlstate 23505, constraint uq_desk_secret)"
