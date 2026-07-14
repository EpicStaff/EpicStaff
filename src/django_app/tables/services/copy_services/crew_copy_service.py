from tables.import_export.utils import ensure_unique_identifier
from tables.models.crew_models import (
    Crew,
    Task,
    TaskConfiguredTools,
    TaskContext,
    TaskMcpTools,
    TaskPythonCodeToolConfigs,
    TaskPythonCodeTools,
)
from tables.services.copy_services.base_copy_service import BaseCopyService


class CrewCopyService(BaseCopyService):
    """Copy service for Crew entities.

    Duplicates all scalar fields. Agents are re-linked (not cloned).
    Tasks are fully cloned with a two-pass approach: the first pass creates
    tasks and builds an ID map, the second pass remaps TaskContext dependencies.
    """

    def copy(
        self, crew: Crew, name: str | None = None, org_id: int | None = None
    ) -> Crew:
        existing_names = Crew.objects.values_list("name", flat=True)
        new_name = ensure_unique_identifier(
            base_name=name if name else crew.name,
            existing_names=existing_names,
        )

        new_crew = Crew.objects.create(
            name=new_name,
            description=crew.description,
            process=crew.process,
            memory=crew.memory,
            max_rpm=crew.max_rpm,
            cache=crew.cache,
            full_output=crew.full_output,
            planning=crew.planning,
            default_temperature=crew.default_temperature,
            metadata=crew.metadata,
            config=crew.config,
            memory_llm_config=crew.memory_llm_config,
            manager_llm_config=crew.manager_llm_config,
            planning_llm_config=crew.planning_llm_config,
            embedding_config=crew.embedding_config,
            org_id=org_id if org_id is not None else crew.org_id,
        )

        new_crew.agents.set(crew.agents.all())

        old_tasks = list(crew.task_set.order_by("order", "id"))
        task_id_map: dict[int, Task] = {}

        for old_task in old_tasks:
            new_task = Task.objects.create(
                crew=new_crew,
                name=old_task.name,
                agent=old_task.agent,
                instructions=old_task.instructions,
                knowledge_query=old_task.knowledge_query,
                expected_output=old_task.expected_output,
                order=old_task.order,
                human_input=old_task.human_input,
                async_execution=old_task.async_execution,
                config=old_task.config,
                output_model=old_task.output_model,
            )
            task_id_map[old_task.id] = new_task

            for row in old_task.task_configured_tool_list.all():
                TaskConfiguredTools.objects.create(task=new_task, tool=row.tool)
            for row in old_task.task_python_code_tool_list.all():
                TaskPythonCodeTools.objects.create(task=new_task, tool=row.tool)
            for row in old_task.task_python_code_tool_config_list.all():
                TaskPythonCodeToolConfigs.objects.create(task=new_task, tool=row.tool)
            for row in old_task.task_mcp_tool_list.all():
                TaskMcpTools.objects.create(task=new_task, tool=row.tool)

        for old_task in old_tasks:
            new_task = task_id_map[old_task.id]
            for ctx_row in old_task.task_context_list.all():
                mapped_context = task_id_map.get(ctx_row.context_id)
                if mapped_context:
                    TaskContext.objects.create(task=new_task, context=mapped_context)

        return new_crew
