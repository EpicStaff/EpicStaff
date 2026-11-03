from collections.abc import Iterable

from utils.graph_utils import join_with_and, node_label, node_list_phrase

from tables.exceptions import (
    ClassificationDecisionTableNodeRunValidationError,
    DecisionTableNodeRunValidationError,
)
from tables.models.graph_models import (
    ClassificationConditionGroup,
    ClassificationDecisionTableNode,
    ClassificationDecisionTablePrompt,
    ConditionGroup,
    DecisionTableNode,
)

# The node types as the flow editor's add-node menu names them.
_DECISION_TABLE_LABEL = "Decision Table"
_CLASSIFICATION_TABLE_LABEL = "Classification Table"

# Crew evaluates a simple group through its list of conditions and a complex group through
# its own expression; any other group type is never evaluated (`ConditionGroupData.group_type`
# in shared).
_SIMPLE_GROUP_TYPE = "simple"
_COMPLEX_GROUP_TYPE = "complex"


def _label(node: DecisionTableNode | ClassificationDecisionTableNode) -> str:
    return node_label(node_name=node.node_name, node_number=node.node_number)


def _quoted_names(noun: str, names: list[str]) -> str:
    """Name things for a message: 'Condition "A"', 'Conditions "A" and "B"'."""
    plural = "" if len(names) == 1 else "s"
    quoted_names = [f'"{name}"' for name in names]
    return f"{noun}{plural} {join_with_and(quoted_names)}"


def _verb(names: list[str]) -> str:
    return "has" if len(names) == 1 else "have"


def _without_error_route(
    nodes: Iterable[DecisionTableNode | ClassificationDecisionTableNode],
) -> list[DecisionTableNode | ClassificationDecisionTableNode]:
    # A node with an error route sends a failure there, so the run is the user's to
    # handle; only a node without one fails the session.
    return [node for node in nodes if node.next_error_node_id is None]


def _in_order(
    groups: Iterable[ConditionGroup | ClassificationConditionGroup],
) -> list[ConditionGroup | ClassificationConditionGroup]:
    # The groups' own ordering is by `order` alone; `id` keeps ties stable.
    return sorted(groups, key=lambda group: (group.order, group.id))


class DecisionTableNodeValidator:
    """Refuses a run whose Decision Table nodes have a condition crew fails to evaluate.

    Only a blank expression is refused, because crew fails on it, and only in a node
    without an error route: a node with one sends the failure there. Everything crew runs
    without failing is left alone: a table without conditions takes the default route, a
    condition without a next node goes on to the next condition, an empty simple group
    matches, and a complex group without an expression never matches. Saving any of
    these is allowed, so this is checked only before a run. A blank expression is refused
    even where this run might not reach it, since it is never intended.
    """

    def validate_runnable(
        self, node_list: Iterable[DecisionTableNode], *, flow_name: str | None = None
    ) -> None:
        """Refuse the run when a condition has a blank expression, naming every such condition.

        Nodes with an error route are skipped.

        Args:
            node_list: Loaded with `condition_groups__conditions` prefetched, or each node
                costs a query.
            flow_name: The subflow's name, named in the message; None for the flow that was run.

        Raises:
            DecisionTableNodeRunValidationError: At least one condition has a blank expression.
        """
        # One sentence per node, naming every failing condition in the table's order.
        sentences = []
        for node in _without_error_route(node_list):
            # condition_groups.all() reads the prefetched rows, which leave out the recycle bin.
            names = [
                group.group_name
                for group in _in_order(node.condition_groups.all())
                if self._has_blank_expression(group)
            ]
            if names:
                node_phrase = node_list_phrase(_DECISION_TABLE_LABEL, [_label(node)], flow_name)
                sentences.append(
                    f"{_quoted_names('Condition', names)} in {node_phrase} "
                    f"{_verb(names)} no expression."
                )
        if sentences:
            raise DecisionTableNodeRunValidationError(" ".join(sentences))

    @staticmethod
    def _has_blank_expression(group: ConditionGroup) -> bool:
        # Crew compiles a blank expression, which fails as a syntax error. A complex
        # group's None expression is skipped without failing, so only a string counts.
        if group.group_type == _SIMPLE_GROUP_TYPE:
            return any(not condition.condition.strip() for condition in group.conditions.all())
        if group.group_type == _COMPLEX_GROUP_TYPE:
            return group.expression is not None and not group.expression.strip()
        return False


class ClassificationDecisionTableNodeValidator:
    """Refuses a run whose Classification Table nodes would call a prompt without an LLM.

    Only what crew fails on is refused, and only in a node without an error route: a
    node with one sends the failure there. A disabled row (`dock_visible` off) never runs,
    and crew skips a row's prompt that is in the recycle bin, so neither is checked. A
    row without an expression or a next node is valid here: crew matches it
    unconditionally, and routes it by its continue flag or the node's default route. A
    prompt without an LLM is refused even where this run might not reach its row.
    """

    def validate_runnable(
        self, node_list: Iterable[ClassificationDecisionTableNode], *, flow_name: str | None = None
    ) -> None:
        """Refuse the run when a prompt a row uses has no LLM, naming every such prompt.

        Nodes with an error route are skipped.

        Args:
            node_list: Loaded with `default_llm_config` selected and `prompt_configs` and
                `condition_groups` prefetched, or each node costs queries.
            flow_name: The subflow's name, named in the message; None for the flow that was run.

        Raises:
            ClassificationDecisionTableNodeRunValidationError: A used prompt has no LLM.
        """
        message = self._no_llm_message(_without_error_route(node_list), flow_name)
        if message:
            raise ClassificationDecisionTableNodeRunValidationError(message)

    @staticmethod
    def _enabled_groups(
        node: ClassificationDecisionTableNode,
    ) -> list[ClassificationConditionGroup]:
        return [group for group in _in_order(node.condition_groups.all()) if group.dock_visible]

    @staticmethod
    def _live_prompts(
        node: ClassificationDecisionTableNode,
    ) -> dict[int, ClassificationDecisionTablePrompt]:
        # prompt_configs.all() reads the prefetched rows, which leave out the recycle bin.
        return {prompt.id: prompt for prompt in node.prompt_configs.all()}

    @staticmethod
    def _has_llm(
        prompt: ClassificationDecisionTablePrompt, node: ClassificationDecisionTableNode
    ) -> bool:
        # Resolved as the converter resolves it for crew: the prompt's own LLM wins even
        # when it has no model, and only a prompt without one falls back to the node's.
        llm_config = prompt.llm_config or node.default_llm_config
        return llm_config is not None and llm_config.model_id is not None

    @classmethod
    def _no_llm_message(
        cls, nodes: list[ClassificationDecisionTableNode], flow_name: str | None
    ) -> str:
        # One sentence per node, naming its prompts in the order rows first use them.
        sentences = []
        prompt_count = 0
        for node in nodes:
            live_prompts = cls._live_prompts(node)
            used_prompts = {
                group.prompt_id: live_prompts[group.prompt_id]
                for group in cls._enabled_groups(node)
                if group.prompt_id in live_prompts
            }
            names = [
                prompt.prompt_key
                for prompt in used_prompts.values()
                if not cls._has_llm(prompt, node)
            ]
            if names:
                prompt_count += len(names)
                node_phrase = node_list_phrase(
                    _CLASSIFICATION_TABLE_LABEL, [_label(node)], flow_name
                )
                sentences.append(
                    f"{_quoted_names('Prompt', names)} in {node_phrase} {_verb(names)} no LLM."
                )
        if not sentences:
            return ""
        if len(sentences) > 1:
            sentences.append("Choose one for each, or set a default LLM for each node.")
        elif prompt_count > 1:
            sentences.append("Choose one for each, or set a default LLM for the node.")
        else:
            sentences.append("Choose one for it, or set a default LLM for the node.")
        return " ".join(sentences)
