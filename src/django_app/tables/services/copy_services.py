from utils.singleton_meta import SingletonMeta
from tables.models import Crew, TaskContext, Task, Agent
from tables.utils.helpers import generate_new_unique_name


class BaseCopyService(metaclass=SingletonMeta):

    def copy(self, entity):
        raise NotImplementedError("Subclasses must implement this method")


class AgentCopyService(BaseCopyService):

    def copy(self, agent) -> Agent:
        """Create a copy of the given agent."""
        tags = list(agent.tags.all())
        agent_names = Agent.objects.values_list("name", flat=True)

        configured_tools = agent.configured_tools.all()
        python_code_tools = agent.python_code_tools.all()
        mcp_tools = agent.mcp_tools.all()

        new_agent = Agent(
            role=agent.role,
            goal=agent.goal,
            backstory=agent.backstory,
            max_iter=agent.max_iter,
            max_rpm=agent.max_rpm,
            max_execution_time=agent.max_execution_time,
            memory=agent.memory,
            allow_delegation=agent.allow_delegation,
            cache=agent.cache,
            allow_code_execution=agent.allow_code_execution,
            max_retry_limit=agent.max_retry_limit,
            respect_context_window=agent.respect_context_window,
            default_temperature=agent.default_temperature,
            knowledge_collection=agent.knowledge_collection,
            search_limit=agent.search_limit,
            similarity_threshold=agent.similarity_threshold,
            llm_config=agent.llm_config,
            fcm_llm_config=agent.fcm_llm_config,
            name=generate_new_unique_name(agent.name, agent_names),
        )
        new_agent.save()

        if tags:
            new_agent.tags.set(tags)
        if configured_tools:
            new_agent.configured_tools.set(configured_tools)
        if python_code_tools:
            new_agent.python_code_tools.set(python_code_tools)
        if mcp_tools:
            new_agent.mcp_tools.set(mcp_tools)

        return new_agent


class CrewCopyService(BaseCopyService):

    def copy(self, crew) -> Crew:
        """Create a copy of the given crew along with its tasks and task contexts."""
        original_agents = list(crew.agents.all())
        tags = list(crew.tags.all())
        original_tasks = list(crew.task_set.all())
        crew_names = Crew.objects.values_list("name", flat=True)

        new_crew = Crew(
            metadata=crew.metadata,
            description=crew.description,
            name=generate_new_unique_name(crew.name, crew_names),
            process=crew.process,
            memory=crew.memory,
            memory_llm_config=crew.memory_llm_config,
            embedding_config=crew.embedding_config,
            manager_llm_config=crew.manager_llm_config,
            config=crew.config,
            max_rpm=crew.max_rpm,
            cache=crew.cache,
            full_output=crew.full_output,
            planning=crew.planning,
            planning_llm_config=crew.planning_llm_config,
            default_temperature=crew.default_temperature,
            knowledge_collection=crew.knowledge_collection,
            search_limit=crew.search_limit,
            similarity_threshold=crew.similarity_threshold,
            is_template=crew.is_template,
        )
        new_crew.save()

        self._assign_agents(new_crew, original_agents)
        self._assign_tags(new_crew, tags)
        self._copy_tasks(new_crew, original_tasks)

        return new_crew

    def _assign_agents(self, new_crew: Crew, original_agents: list) -> None:
        """Assign agents to the new crew."""
        if original_agents:
            new_crew.agents.set(original_agents)

    def _assign_tags(self, new_crew: Crew, tags: list) -> None:
        """Assign tags to the new crew."""
        if tags:
            new_crew.tags.set(tags)

    def _copy_tasks(self, new_crew: Crew, original_tasks: list) -> None:
        """Copy tasks and their contexts from original tasks to the new crew."""
        task_mapping = {}
        for task in original_tasks:
            configured_tools = task.task_configured_tool_list.all()
            python_code_tools = task.task_python_code_tool_list.all()
            mcp_tools = task.task_mcp_tool_list.all()

            original_task_id = task.id

            new_task = Task(
                crew=new_crew,
                name=task.name,
                agent=task.agent,
                instructions=task.instructions,
                knowledge_query=task.knowledge_query,
                expected_output=task.expected_output,
                order=task.order,
                human_input=task.human_input,
                async_execution=task.async_execution,
                config=task.config,
                output_model=task.output_model,
            )
            new_task.save()

            if configured_tools:
                new_task.task_configured_tool_list.set(configured_tools)
            if python_code_tools:
                new_task.task_python_code_tool_list.set(python_code_tools)
            if mcp_tools:
                new_task.task_mcp_tool_list.set(mcp_tools)

            task_mapping[original_task_id] = new_task.id

        for old_task in original_tasks:
            for old_context in old_task.task_context_list.all():
                new_task_id = task_mapping.get(old_context.task_id)
                new_context_id = task_mapping.get(old_context.context_id)

                if not new_task_id or not new_context_id:
                    continue

                TaskContext.objects.create(
                    task_id=new_task_id,
                    context_id=new_context_id,
                )


class GraphCopyService(BaseCopyService):

    def copy(self, graph):
        raise NotImplementedError("Graph copying not yet implemented")
