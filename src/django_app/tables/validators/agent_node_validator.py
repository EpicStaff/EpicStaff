from collections.abc import Iterable

from utils.graph_utils import flow_location, node_label, node_list_phrase

from tables.exceptions import AgentNodeRunValidationError
from tables.models import AgentNode, TaskNode

# The node type as the flow editor's add-node menu names it.
_NODE_TYPE_LABELS = {
    AgentNode: "Agent",
    TaskNode: "Task",
}


def _label(node: AgentNode | TaskNode) -> str:
    return node_label(node_name=node.node_name, node_number=node.node_number)


class AgentNodeValidator:
    """Refuses a run whose Agent or Task nodes the agent service couldn't execute.

    Saving such a node is allowed (its agent or LLM can be deleted later, and a new
    Agent node starts without tasks), so these are checked only before a run.
    """

    def validate_runnable(
        self,
        node_list: Iterable[AgentNode | TaskNode],
        *,
        flow_name: str | None = None,
    ) -> None:
        """Refuse the run when an Agent or Task node isn't set up, naming every such node.

        Both node kinds of a flow go in one call, Agent nodes first, so one message names
        all of them, grouped by kind. Only the first failing check is reported: no agent
        chosen, then the agent has no LLM, then an Agent node has no tasks.

        Args:
            node_list: Loaded with `agent_definition` selected and an Agent node's `tasks`
                prefetched, or each node costs a query.
            flow_name: The subflow's name, named in the message; None for the flow that was run.

        Raises:
            AgentNodeRunValidationError: At least one node fails a check.
        """
        nodes = list(node_list)
        for check in (self._no_agent_message, self._no_llm_message, self._no_tasks_message):
            message = check(nodes, flow_name)
            if message:
                raise AgentNodeRunValidationError(message)

    @staticmethod
    def _no_agent_message(nodes: list[AgentNode | TaskNode], flow_name: str | None) -> str:
        labels_by_type: dict[str, list[str]] = {}
        for node in nodes:
            if node.agent_definition_id is None:
                labels_by_type.setdefault(_NODE_TYPE_LABELS[type(node)], []).append(_label(node))
        sentences = []
        for type_label, labels in labels_by_type.items():
            verb = "has" if len(labels) == 1 else "have"
            sentences.append(
                f"{node_list_phrase(type_label, labels, flow_name)} {verb} no agent chosen."
            )
        return " ".join(sentences)

    @staticmethod
    def _no_llm_message(nodes: list[AgentNode | TaskNode], flow_name: str | None) -> str:
        # One sentence per agent, naming every node that uses it: the LLM is fixed on the
        # agent, not the node. Agents come in the order of the first node using them, and
        # their nodes grouped by kind in the order of `nodes` (Agent nodes first).
        agent_names: dict[int, str] = {}
        labels_by_agent_and_type: dict[int, dict[str, list[str]]] = {}
        for node in nodes:
            agent_definition = node.agent_definition
            if agent_definition is None or agent_definition.llm_config_id is not None:
                continue
            agent_names[agent_definition.id] = agent_definition.name
            labels_by_agent_and_type.setdefault(agent_definition.id, {}).setdefault(
                _NODE_TYPE_LABELS[type(node)], []
            ).append(_label(node))
        if not labels_by_agent_and_type:
            return ""

        location = flow_location(flow_name)
        sentences = []
        for agent_id, labels_by_type in labels_by_agent_and_type.items():
            node_groups = " and ".join(
                node_list_phrase(type_label, labels, None)
                for type_label, labels in labels_by_type.items()
            )
            sentences.append(
                f'Agent "{agent_names[agent_id]}" in {node_groups}{location} has no LLM.'
            )
        if len(agent_names) == 1:
            sentences.append("Choose one for the agent on the Agents page.")
        else:
            sentences.append("Choose one for each agent on the Agents page.")
        return " ".join(sentences)

    @staticmethod
    def _no_tasks_message(nodes: list[AgentNode | TaskNode], flow_name: str | None) -> str:
        # tasks.all() reads the prefetched rows, which leave out tasks in the recycle bin.
        labels = [
            _label(node) for node in nodes if isinstance(node, AgentNode) and not node.tasks.all()
        ]
        if not labels:
            return ""
        phrase = node_list_phrase(_NODE_TYPE_LABELS[AgentNode], labels, flow_name)
        if len(labels) == 1:
            return f"{phrase} has no tasks. Add at least one task."
        return f"{phrase} have no tasks. Add at least one task to each."
