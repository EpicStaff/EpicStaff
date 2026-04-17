from django.db import transaction
from tables.models.knowledge_models.naive_rag_models import (
    NaiveRag,
    AgentNaiveRag,
    NaiveRagSearchConfig,
)
from tables.models.knowledge_models.graphrag_models import (
    GraphRag,
    AgentGraphRag,
    GraphRagBasicSearchConfig,
    GraphRagLocalSearchConfig,
)
from tables.models.crew_models import Agent
from tables.exceptions import (
    NaiveRagNotFoundException,
    GraphRagNotFoundException,
    AgentMissingCollectionException,
    RagCollectionMismatchException,
    UnknownRagTypeException,
)


class RagAssignmentService:
    """
    Service for managing RAG assignments to agents.
    Supports polymorphic RAG types (naive, graph, etc.) with type-specific delegation.
    """

    @staticmethod
    def validate_rag_assignment(agent: Agent, rag_type: str, rag_id: int):
        """
        Validate that RAG can be assigned to agent.

        Validates:
        - RAG exists
        - RAG belongs to agent's knowledge_collection
        """
        if not agent.knowledge_collection:
            raise AgentMissingCollectionException()

        if rag_type == "naive":
            try:
                naive_rag = NaiveRag.objects.select_related(
                    "base_rag_type__source_collection"
                ).get(naive_rag_id=rag_id)
            except NaiveRag.DoesNotExist:
                raise NaiveRagNotFoundException(rag_id)

            # Validate RAG belongs to agent's collection
            if naive_rag.base_rag_type.source_collection != agent.knowledge_collection:
                raise RagCollectionMismatchException(
                    "naive", rag_id, agent.knowledge_collection.collection_id
                )

            # TODO: add status validation
            return naive_rag

        elif rag_type == "graph":
            try:
                graph_rag = GraphRag.objects.select_related(
                    "base_rag_type__source_collection"
                ).get(graph_rag_id=rag_id)
            except GraphRag.DoesNotExist:
                raise GraphRagNotFoundException(rag_id)

            # Validate RAG belongs to agent's collection
            if graph_rag.base_rag_type.source_collection != agent.knowledge_collection:
                raise RagCollectionMismatchException(
                    "graph", rag_id, agent.knowledge_collection.collection_id
                )

            return graph_rag

        else:
            raise UnknownRagTypeException(rag_type)

    @staticmethod
    @transaction.atomic
    def assign_rag_to_agent(agent: Agent, rag_type: str, rag_id: int):
        """
        Polymorphic RAG assignment. Delegates to type-specific methods.
        """
        # Validate assignment
        rag_instance = RagAssignmentService.validate_rag_assignment(
            agent, rag_type, rag_id
        )

        if rag_type == "naive":
            return RagAssignmentService.assign_naive_rag_to_agent(agent, rag_id)
        elif rag_type == "graph":
            return RagAssignmentService.assign_graph_rag_to_agent(agent, rag_id)
        else:
            raise UnknownRagTypeException(rag_type)

    @staticmethod
    def get_assigned_rag_info(agent: Agent) -> dict | None:
        """
        Get currently assigned RAG information in polymorphic format.
        """
        # Check NaiveRag assignment
        naive_rag = RagAssignmentService.get_agent_naive_rag(agent)
        if naive_rag:
            return {
                "rag_type": "naive",
                "rag_id": naive_rag.naive_rag_id,
                "rag_status": naive_rag.rag_status,
            }

        # Check GraphRag assignment
        graph_rag = RagAssignmentService.get_agent_graph_rag(agent)
        if graph_rag:
            return {
                "rag_type": "graph",
                "rag_id": graph_rag.graph_rag_id,
                "rag_status": graph_rag.rag_status,
            }

        return None

    @staticmethod
    @transaction.atomic
    def unassign_all_rags_from_agent(agent: Agent):
        """
        Unassign ALL RAG types from agent (polymorphic).
        Keeps search configs intact.

        Args:
            agent: Agent instance
        """
        # Unassign NaiveRag
        RagAssignmentService.unassign_naive_rag_from_agent(agent)

        # Unassign GraphRag
        RagAssignmentService.unassign_graph_rag_from_agent(agent)

    @staticmethod
    def get_available_naive_rags_for_agent(agent: Agent):
        """
        Get all COMPLETED NaiveRags belonging to agent's knowledge_collection.
        Returns empty queryset if agent has no collection.
        """
        if not agent.knowledge_collection:
            return NaiveRag.objects.none()
        # validate status rag_status=NaiveRag.NaiveRagStatus.COMPLETED)
        return NaiveRag.objects.filter(
            base_rag_type__source_collection=agent.knowledge_collection
        ).select_related("base_rag_type", "embedder")

    @staticmethod
    @transaction.atomic
    def assign_naive_rag_to_agent(agent: Agent, naive_rag_id: int):
        """
        Create AgentNaiveRag link + NaiveRagSearchConfig with defaults.

        NOTE: This method does NOT validate. Use assign_rag_to_agent() for validation.
        This is called internally after validation.
        """
        naive_rag = NaiveRag.objects.select_related(
            "base_rag_type__source_collection"
        ).get(naive_rag_id=naive_rag_id)

        # Validation: RAG must belong to agent's collection
        if naive_rag.base_rag_type.source_collection != agent.knowledge_collection:
            raise RagCollectionMismatchException(
                "naive", naive_rag_id, agent.knowledge_collection.collection_id
            )

        RagAssignmentService.unassign_naive_rag_from_agent(agent)

        # Create M2M link
        AgentNaiveRag.objects.create(agent=agent, naive_rag=naive_rag)

        return naive_rag

    @staticmethod
    def get_agent_naive_rag(agent: Agent) -> NaiveRag | None:
        """Get currently assigned NaiveRag (or None)."""
        try:
            return agent.agent_naive_rags.select_related("naive_rag").get().naive_rag
        except AgentNaiveRag.DoesNotExist:
            return None

    @staticmethod
    @transaction.atomic
    def unassign_naive_rag_from_agent(agent: Agent):
        """Remove NaiveRag assignment (keeps search config)."""
        AgentNaiveRag.objects.filter(agent=agent).delete()

    # GraphRag methods

    @staticmethod
    def get_available_graph_rags_for_agent(agent: Agent):
        """
        Get all GraphRags belonging to agent's knowledge_collection.
        Returns empty queryset if agent has no collection.
        """
        if not agent.knowledge_collection:
            return GraphRag.objects.none()

        return GraphRag.objects.filter(
            base_rag_type__source_collection=agent.knowledge_collection
        ).select_related("base_rag_type", "embedder", "llm")

    @staticmethod
    @transaction.atomic
    def assign_graph_rag_to_agent(agent: Agent, graph_rag_id: int):
        """
        Create AgentGraphRag link.

        NOTE: This method does NOT validate. Use assign_rag_to_agent() for validation.
        This is called internally after validation.
        """
        graph_rag = GraphRag.objects.select_related(
            "base_rag_type__source_collection"
        ).get(graph_rag_id=graph_rag_id)

        # Validation: RAG must belong to agent's collection
        if graph_rag.base_rag_type.source_collection != agent.knowledge_collection:
            raise RagCollectionMismatchException(
                "graph", graph_rag_id, agent.knowledge_collection.collection_id
            )

        RagAssignmentService.unassign_graph_rag_from_agent(agent)

        # Create M2M link
        AgentGraphRag.objects.create(agent=agent, graph_rag=graph_rag)

        # Create both search configs with defaults
        GraphRagBasicSearchConfig.objects.get_or_create(agent=agent)
        GraphRagLocalSearchConfig.objects.get_or_create(agent=agent)

        return graph_rag

    @staticmethod
    def get_agent_graph_rag(agent: Agent) -> GraphRag | None:
        """Get currently assigned GraphRag (or None)."""
        try:
            return agent.agent_graph_rags.select_related("graph_rag").get().graph_rag
        except AgentGraphRag.DoesNotExist:
            return None

    @staticmethod
    @transaction.atomic
    def unassign_graph_rag_from_agent(agent: Agent):
        """Remove GraphRag assignment."""
        AgentGraphRag.objects.filter(agent=agent).delete()


class SearchConfigService:
    """
    Service for managing search configurations for different RAG types.
    Handles both read (get) and write (create/update/apply) operations.
    """

    # Read methods

    @staticmethod
    def get_search_configs(agent: Agent) -> dict | None:
        """
        Get all RAG search configurations in unified nested format.

        Returns:
            {
                "naive": {"search_limit": 3, "similarity_threshold": 0.2},
                "graph": {
                    "search_method": "basic",
                    "basic": {"prompt": null, "k": 10, "max_context_tokens": 12000},
                    "local": {"prompt": null, "text_unit_prop": 0.5, ...},
                },
            }
            or None if no configs exist.
        """
        configs = {}

        naive_config = SearchConfigService.get_naive_search_config(agent)
        if naive_config is not None:
            configs["naive"] = naive_config

        graph_config = SearchConfigService.get_graph_search_configs(agent)
        if graph_config is not None:
            configs["graph"] = graph_config

        return configs if configs else None

    @staticmethod
    def get_naive_search_config(agent: Agent) -> dict | None:
        """Get naive RAG search config as dict, or None if not exists."""

        config = NaiveRagSearchConfig.objects.filter(agent=agent).first()
        if config is None:
            return None
        return {
            "search_limit": config.search_limit,
            "similarity_threshold": round(float(config.similarity_threshold), 2),
        }

    @staticmethod
    def get_graph_search_configs(agent: Agent) -> dict | None:
        """
        Get graph RAG search configs in nested format.
        Search configs are independent from RAG assignment — returned
        whenever they exist in DB regardless of AgentGraphRag link.

        Returns None only if neither basic nor local config exists.

        Returns:
            {
                "search_method": "basic",
                "basic": {"prompt": null, "k": 10, "max_context_tokens": 12000},
                "local": {"prompt": null, "text_unit_prop": 0.5, ...},
            }
        """
        basic = GraphRagBasicSearchConfig.objects.filter(agent=agent).first()
        local = GraphRagLocalSearchConfig.objects.filter(agent=agent).first()

        if basic is None and local is None:
            return None

        # search_method from AgentGraphRag if assigned, null if no graph rag
        agent_graph_rag = agent.agent_graph_rags.first()
        search_method = agent_graph_rag.search_method if agent_graph_rag else None

        result = {"search_method": search_method}

        if basic is not None:
            result["basic"] = {
                "prompt": basic.prompt,
                "k": basic.k,
                "max_context_tokens": basic.max_context_tokens,
            }
        else:
            result["basic"] = None

        if local is not None:
            result["local"] = {
                "prompt": local.prompt,
                "text_unit_prop": local.text_unit_prop,
                "community_prop": local.community_prop,
                "conversation_history_max_turns": local.conversation_history_max_turns,
                "top_k_entities": local.top_k_entities,
                "top_k_relationships": local.top_k_relationships,
                "max_context_tokens": local.max_context_tokens,
            }
        else:
            result["local"] = None

        return result

    # Write methods

    @staticmethod
    def apply_search_configs(agent: Agent, search_configs_data: dict):
        """
        Apply search config updates from validated serializer data.
        Handles both naive and graph configs.
        """
        for rag_type, config in search_configs_data.items():
            if rag_type == "naive":
                SearchConfigService.update_search_config(agent, **config)
            elif rag_type == "graph":
                SearchConfigService.apply_graph_search_configs(agent, config)

    @staticmethod
    def apply_graph_search_configs(agent: Agent, config: dict):
        """
        Apply graph search config from validated serializer data.
        Handles search_method, basic config, and local config independently.
        """
        search_method = config.get("search_method")
        if search_method:
            SearchConfigService.update_graph_search_method(agent, search_method)

        basic_config = config.get("basic")
        if basic_config:
            SearchConfigService.update_graph_basic_search_config(agent, **basic_config)

        local_config = config.get("local")
        if local_config:
            SearchConfigService.update_graph_local_search_config(agent, **local_config)

    @staticmethod
    def create_default_search_config(agent: Agent) -> NaiveRagSearchConfig:
        """
        Create search config with default values from model.
        """
        config, created = NaiveRagSearchConfig.objects.get_or_create(agent=agent)
        return config

    @staticmethod
    def get_config_for_agent(agent: Agent) -> NaiveRagSearchConfig | None:
        """Get search config or None."""
        try:
            return agent.naive_search_config
        except NaiveRagSearchConfig.DoesNotExist:
            return None

    @staticmethod
    def update_search_config(
        agent: Agent, search_limit=None, similarity_threshold=None
    ):
        """
        Update agent's search config. Creates if doesn't exist.
        Only updates provided fields (partial update).
        """
        config, created = NaiveRagSearchConfig.objects.get_or_create(agent=agent)

        # Update fields if provided (works for both created and existing configs)
        if search_limit is not None:
            config.search_limit = search_limit
        if similarity_threshold is not None:
            config.similarity_threshold = similarity_threshold

        if search_limit is not None or similarity_threshold is not None:
            config.save()

        return config

    # Graph RAG search config methods

    @staticmethod
    def create_default_graph_search_configs(agent: Agent):
        """Create both basic and local search configs with defaults."""
        GraphRagBasicSearchConfig.objects.get_or_create(agent=agent)
        GraphRagLocalSearchConfig.objects.get_or_create(agent=agent)

    @staticmethod
    def update_graph_search_method(agent: Agent, search_method: str):
        """Update the active search_method on AgentGraphRag."""
        AgentGraphRag.objects.filter(agent=agent).update(search_method=search_method)

    @staticmethod
    def update_graph_basic_search_config(agent: Agent, **kwargs):
        """Update basic search config. Creates if doesn't exist."""
        config, _ = GraphRagBasicSearchConfig.objects.get_or_create(agent=agent)
        valid_fields = ("prompt", "k", "max_context_tokens")
        updated = False
        for field, value in kwargs.items():
            if field in valid_fields and value is not None:
                setattr(config, field, value)
                updated = True
        if updated:
            config.save()
        return config

    @staticmethod
    def update_graph_local_search_config(agent: Agent, **kwargs):
        """Update local search config. Creates if doesn't exist."""
        config, _ = GraphRagLocalSearchConfig.objects.get_or_create(agent=agent)
        valid_fields = (
            "prompt",
            "text_unit_prop",
            "community_prop",
            "conversation_history_max_turns",
            "top_k_entities",
            "top_k_relationships",
            "max_context_tokens",
        )
        updated = False
        for field, value in kwargs.items():
            if field in valid_fields and value is not None:
                setattr(config, field, value)
                updated = True
        if updated:
            config.save()
        return config
