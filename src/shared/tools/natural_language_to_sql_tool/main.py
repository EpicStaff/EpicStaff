# Natural Language To SQL Tool


import re

from epicstaff_common import require_setting, resolve_setting, safe_error_message
from sqlalchemy import create_engine, event
from sqlalchemy.exc import SQLAlchemyError
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import create_sql_agent
from langchain_litellm import ChatLiteLLM

DEFAULT_MODEL = "gpt-4o-mini"

READ_ONLY_SESSION_STATEMENTS = {
    "postgresql": "SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY",
    "mysql": "SET SESSION TRANSACTION READ ONLY",
}
READ_ONLY_TRANSACTION_STATEMENT = "SET TRANSACTION READ ONLY"
READ_ONLY_QUERY_START = re.compile(r"(SELECT|WITH)\b", re.IGNORECASE)


class ReadOnlyQueryRejected(SQLAlchemyError):
    """A SQLAlchemyError, so LangChain's run_no_throw hands the message to the agent."""


def _reject_unless_single_select(query: str) -> None:
    # Checks the raw text instead of parsing it: a SQL parser reads a different dialect
    # than the server (MySQL runs /*! */ comments, Postgres nests /* */ and ignores
    # backslash escapes). Starting with SELECT or WITH and holding no semicolon leaves
    # one SELECT or DML statement, and the read-only transaction blocks the DML.
    statement = query.strip().removesuffix(";").strip()
    if ";" in statement or not READ_ONLY_QUERY_START.match(statement):
        raise ReadOnlyQueryRejected(
            "Read-only mode accepts exactly one SELECT (or WITH ... SELECT) statement, with no semicolon inside it."
        )


class ReadOnlySQLDatabase(SQLDatabase):
    def run(self, command, *args, **kwargs):
        _reject_unless_single_select(str(command))
        return super().run(command, *args, **kwargs)


class NaturalLanguageToSQLTool:
    def __init__(self):
        self.db_uri = require_setting(globals(), "db_uri")
        self.api_key = require_setting(globals(), "api_key")
        self.model = resolve_setting(globals(), "model", DEFAULT_MODEL)
        self.read_only = resolve_setting(globals(), "read_only", True)

    def _create_engine(self):
        engine = create_engine(self.db_uri)

        if self.read_only:
            session_statement = READ_ONLY_SESSION_STATEMENTS.get(engine.dialect.name)
            if session_statement is None:
                raise RuntimeError(
                    f"Read-only mode is not supported for the '{engine.dialect.name}' database dialect."
                )

            # Keep both: MySQL DDL commits implicitly, ending the per-transaction READ ONLY,
            # so only the session default blocks it; a query can flip the session default,
            # so only the per-transaction statement holds then.
            @event.listens_for(engine, "connect")
            def _start_read_only_session(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute(session_statement)
                cursor.close()
                dbapi_connection.commit()

            @event.listens_for(engine, "begin")
            def _start_read_only_transaction(connection):
                connection.exec_driver_sql(READ_ONLY_TRANSACTION_STATEMENT)

        return engine

    def _create_agent(self):
        llm = ChatLiteLLM(model=self.model, temperature=0, api_key=self.api_key)
        engine = self._create_engine()
        db = ReadOnlySQLDatabase(engine) if self.read_only else SQLDatabase(engine)

        crud_policy = (
            "You may execute SELECT, INSERT, UPDATE, DELETE, and DROP statements."
            if not self.read_only
            else "You are in read-only mode: each query must be exactly one SELECT statement, and anything else is rejected. If the user asks to modify the database, inform them that you are in read-only mode."
        )

        agent_executor = create_sql_agent(
            llm=llm,
            db=db,
            prefix=f"You are an intelligent SQL assistant connected to a live {db.dialect} database.\n{crud_policy}\nAlways generate syntactically correct SQL queries. Always return the answer as plain text without quotes or code blocks.\n",
            handle_parsing_errors=True,
        )
        return agent_executor

    def run_query(self, query_text):
        agent = self._create_agent()
        result = agent.invoke({"input": query_text})
        return result["output"]


def main(query_text, **kwargs):
    try:
        nl2sql = NaturalLanguageToSQLTool()
        return nl2sql.run_query(query_text)
    except Exception as error:
        return f"Error executing tool: {safe_error_message(error)}"
