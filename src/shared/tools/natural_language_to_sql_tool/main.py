# Natural Language To SQL Tool

from sqlalchemy import create_engine, event
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import create_sql_agent
from langchain_openai import ChatOpenAI

READ_ONLY_SESSION_STATEMENTS = {
    "postgresql": "SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY",
    "mysql": "SET SESSION TRANSACTION READ ONLY",
}


class NaturalLanguageToSQLTool:
    def __init__(self):
        self.db_uri = state["variables"]["DB_URI"]
        self.openai_api_key = state["variables"]["OPENAI_API_KEY"]
        self.read_only = state["variables"]["READ_ONLY"]

    def _create_engine(self):
        engine = create_engine(self.db_uri)

        if self.read_only:
            statement = READ_ONLY_SESSION_STATEMENTS.get(engine.dialect.name)
            if statement is None:
                raise RuntimeError(
                    f"Read-only mode is not supported for the '{engine.dialect.name}' database dialect."
                )

            @event.listens_for(engine, "connect")
            def _enforce_read_only(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute(statement)
                cursor.close()

        return engine

    def _create_agent(self):
        # TODO chould we parametrize that? at least model?
        llm = ChatOpenAI(
            model="gpt-4o-mini", temperature=0, api_key=self.openai_api_key
        )
        engine = self._create_engine()
        db = SQLDatabase(engine)

        crud_policy = (
            "You may execute SELECT, INSERT, UPDATE, DELETE, and DROP statements."
            if not self.read_only
            else "You are in read-only mode: the database connection itself rejects INSERT, UPDATE, DELETE, and DROP statements. If the user asks to modify the database, inform them that you are in read-only mode."
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


def main(query_text):
    nl2sql = NaturalLanguageToSQLTool()
    return nl2sql.run_query(query_text)
