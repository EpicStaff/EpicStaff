"""Pin `GRAPH_LINKED_TO_TYPE_CHOICES` to knowledge_new's `GraphOutputTableEnum`.

The Django side keeps a hand-copied tuple of table names so the serializer can reject
unknown `linked_to_type` values without taking a runtime dependency on knowledge_new.
That copy drifts silently — a new table added to the enum does not break any build. This
test is the contract: Django's choices must be exactly the enum's values, nothing more,
nothing less.
"""

from src.shared.enums.knowledge_new import GraphOutputTableEnum
from tables.constants.knowledge_constants import GRAPH_LINKED_TO_TYPE_CHOICES


def test_graph_linked_to_type_choices_match_graph_output_table_enum():
    assert set(GRAPH_LINKED_TO_TYPE_CHOICES) == {member.value for member in GraphOutputTableEnum}
