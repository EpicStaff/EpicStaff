from collections.abc import Iterable

from utils.graph_utils import flow_location, join_with_and, node_label

from tables.exceptions import FileNodeValidationError
from tables.models import AudioTranscriptionNode, FileExtractorNode

# The node type as the flow editor's add-node menu names it.
_NODE_TYPE_LABELS = {
    FileExtractorNode: "File Extractor",
    AudioTranscriptionNode: "Audio to text",
}


class FileNodeValidator:
    def validate_file_nodes(
        self,
        node_list: Iterable[FileExtractorNode | AudioTranscriptionNode],
        *,
        flow_name: str | None = None,
    ) -> None:
        """Refuse the run when any node has no input to read, naming every such node.

        Both node kinds of a flow go in one call, so one message names all of them,
        grouped by kind.

        Args:
            flow_name: The subflow's name, named in the message; None for the flow that was run.

        Raises:
            FileNodeValidationError: At least one node's Input List is empty.
        """
        names_by_type: dict[str, list[str]] = {}
        for node in node_list:
            if not node.input_map:
                names_by_type.setdefault(_NODE_TYPE_LABELS[type(node)], []).append(
                    node_label(node_name=node.node_name, node_number=node.node_number)
                )
        if not names_by_type:
            return

        location = flow_location(flow_name)
        sentences = []
        for type_label, names in names_by_type.items():
            quoted_names = join_with_and([f'"{name}"' for name in names])
            if len(names) == 1:
                sentences.append(f"{type_label} node {quoted_names}{location} has no input file.")
            else:
                sentences.append(f"{type_label} nodes {quoted_names}{location} have no input file.")
        raise FileNodeValidationError(" ".join(sentences))
