# NL2SQL Tool

from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import create_sql_agent
from langchain_openai import ChatOpenAI

class NL2SQLTool:
    def __init__(self):
        self.db_uri = state["variables"]["DB_URI"]
        self.openai_api_key = state["variables"]["OPENAI_API_KEY"]
        self.read_only = state["variables"]["READ_ONLY"]

    def _create_agent(self):
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, api_key=self.openai_api_key)
        db = SQLDatabase.from_uri(self.db_uri)

        crud_policy = (
            "You may execute SELECT, INSERT, UPDATE, DELETE, and DROP statements."
            if not self.read_only
            else "You must NEVER execute INSERT, UPDATE, DELETE, or DROP statements. If the user asks to modify the database, just inform them that you are in read-only mode."
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
    nl2sql = NL2SQLTool()
    return nl2sql.run_query(query_text)