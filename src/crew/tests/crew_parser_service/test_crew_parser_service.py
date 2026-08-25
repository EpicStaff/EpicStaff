from services.crew.crew_parser_service import CrewParserService
from crewai import Crew


class TestCrewParserService:
    def test_parse_crew(
        self,
        fake_crew_data,
        crew_callback_factory,
        mock_redis_service,
        python_code_executor_service,
        knowledge_search_service,
    ):
        (
            crew_callback_factory,
            task_callback_mock,
            step_callback_mock,
            user_callback_mock,
        ) = crew_callback_factory
        crew_parser_service = CrewParserService(
            redis_service=mock_redis_service,
            python_code_executor_service=python_code_executor_service,
            knowledge_search_service=knowledge_search_service,
        )
        # TODO: set OPENAI_API_KEY from OPENAI_KEY for gitlab
        import os

        os.environ["OPENAI_API_KEY"] = os.environ.get("OPENAI_API_KEY") or "MOCK_KEY"

        inputs = {
            "text": "What is the capital of France?",
        }
        session_id = 123
        crew = crew_parser_service.parse_crew(
            crew_data=fake_crew_data,
            crew_callback_factory=crew_callback_factory,
            inputs=inputs,
            session_id=session_id,
        )

        assert isinstance(crew, Crew)

        assert crew.tasks[0].callback == task_callback_mock
        assert crew.agents[0].step_callback == step_callback_mock
        assert crew.agents[0].ask_human_input_callback == user_callback_mock
