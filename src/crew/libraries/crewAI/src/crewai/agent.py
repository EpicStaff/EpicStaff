import shutil
import subprocess
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import Field, InstanceOf, PrivateAttr, model_validator

from crewai.agents import CacheHandler
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai.agents.crew_agent_executor import (
    CrewAgentExecutor,
    KNOWLEDGE_KEYWORD,
    END_OF_KNOWLEDGE_KEYWORD,
    EMPTY_KNOWLEDGE_KEYWORD,
)
from crewai.llm import LLM
from crewai.memory.contextual.contextual_memory import ContextualMemory
from crewai.memory.contextual.user_input_contextual_memory import (
    UserInputContextualMemory,
)
from crewai.task import Task
from crewai.tools import BaseTool
from crewai.tools.agent_tools.agent_tools import AgentTools
from crewai.tools.base_tool import Tool
from crewai.utilities import Converter, Prompts
from crewai.utilities.constants import TRAINED_AGENTS_DATA_FILE, TRAINING_DATA_FILE
from crewai.utilities.converter import generate_model_description
from crewai.utilities.llm_utils import create_llm
from crewai.utilities.token_counter_callback import TokenCalcHandler
from crewai.utilities.training_handler import CrewTrainingHandler

from crewai.prompts.knowledge_query_generation_prompt import (
    KNOWLEDGE_QUERY_GENERATION_PROMPT,
)
from textwrap import dedent
from contextlib import contextmanager

agentops = None

from loguru import logger

try:
    import agentops  # type: ignore # Name "agentops" is already defined
    from agentops import track_agent  # type: ignore
except ImportError:

    def track_agent():
        def noop(f):
            return f

        return noop


@contextmanager
def temporary_temperature(llm: LLM, temp: float):
    """Temporarily set LLM temperature for knowledge query generation, restoring original value after."""
    original = llm.temperature
    llm.temperature = temp
    try:
        yield
    finally:
        llm.temperature = original


@track_agent()
class Agent(BaseAgent):
    """Represents an agent in a system.

    Each agent has a role, a goal, a backstory, and an optional language model (llm).
    The agent can also have memory, can operate in verbose mode, and can delegate tasks to other agents.

    Attributes:
            agent_executor: An instance of the CrewAgentExecutor class.
            role: The role of the agent.
            goal: The objective of the agent.
            backstory: The backstory of the agent.
            config: Dict representation of agent configuration.
            llm: The language model that will run the agent.
            function_calling_llm: The language model that will handle the tool calling for this agent, it overrides the crew function_calling_llm.
            max_iter: Maximum number of iterations for an agent to execute a task.
            memory: Whether the agent should have memory or not.
            max_rpm: Maximum number of requests per minute for the agent execution to be respected.
            verbose: Whether the agent execution should be in verbose mode.
            allow_delegation: Whether the agent is allowed to delegate tasks to other agents.
            tools: Tools at agents disposal
            step_callback: Callback to be executed after each step of the agent execution.

            knowledge_collection_id: A unique identifier of the knowledgecollection instance for agent. Now fields "knowledge_sources" and "knowledge" are unnecessary.
    """

    _times_executed: int = PrivateAttr(default=0)
    max_execution_time: Optional[int] = Field(
        default=None,
        description="Maximum execution time for an agent to execute a task",
    )
    agent_ops_agent_name: str = None  # type: ignore # Incompatible types in assignment (expression has type "None", variable has type "str")
    agent_ops_agent_id: str = None  # type: ignore # Incompatible types in assignment (expression has type "None", variable has type "str")
    cache_handler: InstanceOf[CacheHandler] = Field(
        default=None, description="An instance of the CacheHandler class."
    )
    step_callback: Optional[Any] = Field(
        default=None,
        description="Callback to be executed after each step of the agent execution.",
    )
    use_system_prompt: Optional[bool] = Field(
        default=True,
        description="Use system prompt for the agent.",
    )
    llm: Union[str, InstanceOf[LLM], Any] = Field(
        description="Language model that will run the agent.", default=None
    )
    function_calling_llm: Optional[Union[str, InstanceOf[LLM], Any]] = Field(
        description="Language model that will run the agent.", default=None
    )
    system_template: Optional[str] = Field(
        default=None, description="System format for the agent."
    )
    prompt_template: Optional[str] = Field(
        default=None, description="Prompt format for the agent."
    )
    response_template: Optional[str] = Field(
        default=None, description="Response format for the agent."
    )
    tools_results: Optional[List[Any]] = Field(
        default=[], description="Results of the tools used by the agent."
    )
    allow_code_execution: Optional[bool] = Field(
        default=False, description="Enable code execution for the agent."
    )
    respect_context_window: bool = Field(
        default=True,
        description="Keep messages under the context window size by summarizing content.",
    )
    max_iter: int = Field(
        default=20,
        description="Maximum number of iterations for an agent to execute a task before giving it's best answer",
    )
    max_retry_limit: int = Field(
        default=2,
        description="Maximum number of retries for an agent to execute a task when an error occurs.",
    )
    multimodal: bool = Field(
        default=False,
        description="Whether the agent is multimodal.",
    )
    code_execution_mode: Literal["safe", "unsafe"] = Field(
        default="safe",
        description="Mode for code execution: 'safe' (using Docker) or 'unsafe' (direct execution).",
    )
    embedder: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Embedder configuration for the agent.",
    )
    ask_human_input_callback: Optional[Any] = Field(
        default=None,
        description="Callback to be executed after Agent action if user_input is true",
    )
    search_knowledges: Optional[Any] = Field(
        default=None,
        description="KnowledgeSearchService method for searching in knowledge module with redis pub/sub",
    )
    user_input_contextual_memory: Optional[Any] = Field(
        default=None,
        description="user_input_contextual_memory",
    )

    @model_validator(mode="after")
    def post_init_setup(self):
        self.agent_ops_agent_name = self.role

        self.llm = create_llm(self.llm)
        if self.function_calling_llm and not isinstance(self.function_calling_llm, LLM):
            self.function_calling_llm = create_llm(self.function_calling_llm)

        if not self.agent_executor:
            self._setup_agent_executor()

        if self.allow_code_execution:
            self._validate_docker_installation()

        return self

    def _setup_agent_executor(self):
        if not self.cache_handler:
            self.cache_handler = CacheHandler()
        self.set_cache_handler(self.cache_handler)

    def _extract_knowledges(self, knowledge_snippets: list) -> str:
        snippet = "\n_______\n".join(knowledge_snippets)
        return snippet

    def execute_task(
        self,
        task: Task,
        context: Optional[str] = None,
        tools: Optional[List[BaseTool]] = None,
    ) -> str:
        """Execute a task with the agent.

        Args:
            task: Task to execute.
            context: Context to execute the task in.
            tools: Tools to use for the task.

        Returns:
            Output of the agent
        """
        if self.tools_handler:
            self.tools_handler.last_used_tool = {}  # type: ignore # Incompatible types in assignment (expression has type "dict[Never, Never]", variable has type "ToolCalling")

        task_prompt = task.prompt()

        # If the task requires output in JSON or Pydantic format,
        # append specific instructions to the task prompt to ensure
        # that the final answer does not include any code block markers
        if task.output_json or task.output_pydantic:
            # Generate the schema based on the output format
            if task.output_json:
                # schema = json.dumps(task.output_json, indent=2)
                schema = generate_model_description(task.output_json)

            elif task.output_pydantic:
                schema = generate_model_description(task.output_pydantic)

            task_prompt += "\n" + self.i18n.slice("formatted_task_instructions").format(
                output_format=schema
            )

        if self.crew and self.crew.memory:
            contextual_memory = ContextualMemory(
                self.crew.memory_config,
                self.crew._short_term_memory,
                self.crew._long_term_memory,
                self.crew._entity_memory,
                self.crew._user_memory,
            )
            memory = contextual_memory.build_context_for_task(task, context)
            if memory.strip() != "":
                task_prompt += self.i18n.slice("memory").format(memory=memory)
            self.user_input_contextual_memory = UserInputContextualMemory(
                memory_config=self.crew.memory_config, um=self.crew._user_memory
            )

        if context:
            task_prompt = self.i18n.slice("task_with_context").format(
                task=task_prompt, context=context
            )

        agent_knowledge_snippet = ""
        crew_knowledge_snippet = ""

        if self.knowledge_collection_id:
            source = f"Agent {self.role}'s"
            knowledge_query = self._get_knowledge_query(task, context, source=source)
            agent_knowledges = self.search_knowledges(
                sender="ag",
                knowledge_collection_id=self.knowledge_collection_id,
                query=knowledge_query,
                search_limit=self.search_limit,
                similarity_threshold=self.similarity_threshold,
            )
            agent_knowledge_snippet = self._extract_knowledges(agent_knowledges)
            task_prompt += (
                f"{KNOWLEDGE_KEYWORD} \n\n{agent_knowledge_snippet}"
                if agent_knowledge_snippet
                else ""
            )

        if self.crew:
            if self.crew.knowledge_collection_id:
                source = f"Crew {self.crew}"
                knowledge_query = self._get_knowledge_query(
                    task, context, source=source
                )
                crew_knowledges = self.search_knowledges(
                    sender="cr",
                    knowledge_collection_id=self.crew.knowledge_collection_id,
                    query=knowledge_query,
                    search_limit=self.crew.search_limit,
                    similarity_threshold=self.crew.similarity_threshold,
                )
                crew_knowledge_snippet = self._extract_knowledges(crew_knowledges)
                if crew_knowledge_snippet:
                    if not agent_knowledge_snippet:
                        task_prompt += (
                            f"{KNOWLEDGE_KEYWORD} \n\n{crew_knowledge_snippet}"
                        )
                    else:
                        task_prompt += f"\n{crew_knowledge_snippet}"

        if agent_knowledge_snippet or crew_knowledge_snippet:
            task_prompt += f"\n{END_OF_KNOWLEDGE_KEYWORD}"

        if not agent_knowledge_snippet and not crew_knowledge_snippet:
            task_prompt += f"\n{EMPTY_KNOWLEDGE_KEYWORD}\n"

        tools = tools or self.tools or []
        self.create_agent_executor(tools=tools, task=task)

        if self.crew and self.crew._train:
            task_prompt = self._training_handler(task_prompt=task_prompt)
        else:
            task_prompt = self._use_trained_data(task_prompt=task_prompt)

        try:
            result = self.agent_executor.invoke(
                {
                    "input": task_prompt,
                    "tool_names": self.agent_executor.tools_names,
                    "tools": self.agent_executor.tools_description,
                    "ask_for_human_input": task.human_input,
                }
            )["output"]
        except Exception as e:
            if e.__class__.__module__.startswith("litellm"):
                # Do not retry on litellm errors
                raise e
            self._times_executed += 1
            if self._times_executed > self.max_retry_limit:
                raise e
            result = self.execute_task(task, context, tools)

        if self.max_rpm and self._rpm_controller:
            self._rpm_controller.stop_rpm_counter()

        # If there was any tool in self.tools_results that had result_as_answer
        # set to True, return the results of the last tool that had
        # result_as_answer set to True
        for tool_result in self.tools_results:  # type: ignore # Item "None" of "list[Any] | None" has no attribute "__iter__" (not iterable)
            if tool_result.get("result_as_answer", False):
                result = tool_result["result"]

        return result

    def create_agent_executor(
        self, tools: Optional[List[BaseTool]] = None, task=None
    ) -> None:
        """Create an agent executor for the agent.

        Returns:
            An instance of the CrewAgentExecutor class.
        """
        tools = tools or self.tools or []
        parsed_tools = self._parse_tools(tools)

        prompt = Prompts(
            agent=self,
            tools=tools,
            i18n=self.i18n,
            use_system_prompt=self.use_system_prompt,
            system_template=self.system_template,
            prompt_template=self.prompt_template,
            response_template=self.response_template,
        ).task_execution()

        stop_words = [self.i18n.slice("observation")]

        if self.response_template:
            stop_words.append(
                self.response_template.split("{{ .Response }}")[1].strip()
            )

        self.agent_executor = CrewAgentExecutor(
            llm=self.llm,
            task=task,
            agent=self,
            crew=self.crew,
            tools=parsed_tools,
            prompt=prompt,
            original_tools=tools,
            stop_words=stop_words,
            max_iter=self.max_iter,
            tools_handler=self.tools_handler,
            tools_names=self.__tools_names(parsed_tools),
            tools_description=self._render_text_description_and_args(parsed_tools),
            step_callback=self.step_callback,
            function_calling_llm=self.function_calling_llm,
            respect_context_window=self.respect_context_window,
            request_within_rpm_limit=(
                self._rpm_controller.check_or_wait if self._rpm_controller else None
            ),
            callbacks=[TokenCalcHandler(self._token_process)],
            ask_human_input_callback=self.ask_human_input_callback,
            user_input_contextual_memory=self.user_input_contextual_memory,
        )

    def get_delegation_tools(self, agents: List[BaseAgent]):
        agent_tools = AgentTools(agents=agents)
        tools = agent_tools.tools()
        return tools

    def get_multimodal_tools(self) -> List[Tool]:
        from crewai.tools.agent_tools.add_image_tool import AddImageTool

        return [AddImageTool()]

    def get_code_execution_tools(self):
        try:
            from crewai_tools import CodeInterpreterTool

            # Set the unsafe_mode based on the code_execution_mode attribute
            unsafe_mode = self.code_execution_mode == "unsafe"
            return [CodeInterpreterTool(unsafe_mode=unsafe_mode)]
        except ModuleNotFoundError:
            self._logger.log(
                "info", "Coding tools not available. Install crewai_tools. "
            )

    def get_output_converter(self, llm, text, model, instructions):
        return Converter(llm=llm, text=text, model=model, instructions=instructions)

    def _parse_tools(self, tools: List[Any]) -> List[Any]:  # type: ignore
        """Parse tools to be used for the task."""
        tools_list = []
        try:
            # tentatively try to import from crewai_tools import BaseTool as CrewAITool
            from crewai.tools import BaseTool as CrewAITool

            for tool in tools:
                if isinstance(tool, CrewAITool):
                    tools_list.append(tool.to_structured_tool())
                else:
                    tools_list.append(tool)
        except ModuleNotFoundError:
            tools_list = []
            for tool in tools:
                tools_list.append(tool)

        return tools_list

    def _training_handler(self, task_prompt: str) -> str:
        """Handle training data for the agent task prompt to improve output on Training."""
        if data := CrewTrainingHandler(TRAINING_DATA_FILE).load():
            agent_id = str(self.id)

            if data.get(agent_id):
                human_feedbacks = [
                    i["human_feedback"] for i in data.get(agent_id, {}).values()
                ]
                task_prompt += (
                    "\n\nYou MUST follow these instructions: \n "
                    + "\n - ".join(human_feedbacks)
                )

        return task_prompt

    def _get_knowledge_query(
        self, task: Task, context: Optional[str], source: str
    ) -> str:
        """Return a knowledge query, using task.knowledge_query if available, else generate one."""
        if task.knowledge_query:
            query = task.knowledge_query
            logger.info(f"{source} knowledge query: {query}")
        else:
            query = self._generate_knowledge_query(
                task=task, previous_tasks_context=context
            )
            logger.info(f"{source} knowledge query (autogenerated): {query}")
        return query

    def _generate_knowledge_query(
        self, task: Task, previous_tasks_context: str | None
    ) -> str:
        """
        Generate a concise knowledge query for a task, optionally enhanced
        by previous tasks context. Uses agent metadata to refine phrasing.

        Args:
            task (Task): Task with 'description' and 'expected_output'.
            previous_tasks_context (str | None): Optional context to enhance the query.

        Returns:
            str: Knowledge query ready for embedding.
        """

        if previous_tasks_context:
            previous_context_block = (
                f"- **Previous task context:** {previous_tasks_context}"
            )
            previous_context_guidelines = dedent(
                """
                - **Previous task context (if provided)** → Use this only as a **secondary enhancer**:  
                    * Integrate details that logically extend, refine, or clarify the current task.  
                    * Ignore any unrelated or redundant parts completely.
            """
            )
        else:
            previous_context_block = ""
            previous_context_guidelines = ""

        prompt = KNOWLEDGE_QUERY_GENERATION_PROMPT.format(
            role=self.role,
            goal=self.goal,
            backstory=self.backstory,
            description=task.description,
            expected_output=task.expected_output,
            previous_context_block=previous_context_block,
            previous_context_guidelines=previous_context_guidelines,
        )

        with temporary_temperature(self.llm, temp=0.0):
            knowledge_query = self.llm.call(prompt)
        return knowledge_query

    def _use_trained_data(self, task_prompt: str) -> str:
        """Use trained data for the agent task prompt to improve output."""
        if data := CrewTrainingHandler(TRAINED_AGENTS_DATA_FILE).load():
            if trained_data_output := data.get(self.role):
                task_prompt += (
                    "\n\nYou MUST follow these instructions: \n - "
                    + "\n - ".join(trained_data_output["suggestions"])
                )
        return task_prompt

    def _render_text_description(self, tools: List[Any]) -> str:
        """Render the tool name and description in plain text.

        Output will be in the format of:

        .. code-block:: markdown

            search: This tool is used for search
            calculator: This tool is used for math
        """
        description = "\n".join(
            [
                f"Tool name: {tool.name}\nTool description:\n{tool.description}"
                for tool in tools
            ]
        )

        return description

    def _render_text_description_and_args(self, tools: List[BaseTool]) -> str:
        """Render the tool name, description, and args in plain text.

            Output will be in the format of:

            .. code-block:: markdown

            search: This tool is used for search, args: {"query": {"type": "string"}}
            calculator: This tool is used for math, \
            args: {"expression": {"type": "string"}}
        """
        tool_strings = []
        for tool in tools:
            tool_strings.append(tool.description)

        return "\n".join(tool_strings)

    def _validate_docker_installation(self) -> None:
        """Check if Docker is installed and running."""
        if not shutil.which("docker"):
            raise RuntimeError(
                f"Docker is not installed. Please install Docker to use code execution with agent: {self.role}"
            )

        try:
            subprocess.run(
                ["docker", "info"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except subprocess.CalledProcessError:
            raise RuntimeError(
                f"Docker is not running. Please start Docker to use code execution with agent: {self.role}"
            )

    @staticmethod
    def __tools_names(tools) -> str:
        return ", ".join([t.name for t in tools])

    def __repr__(self):
        return f"Agent(role={self.role}, goal={self.goal}, backstory={self.backstory})"
