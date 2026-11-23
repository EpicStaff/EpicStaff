from django.db.models import QuerySet
from utils.graph_utils import node_label

from tables.exceptions import FileNodeValidationError
from tables.models import AudioTranscriptionNode, FileExtractorNode

# The node names the editor shows.
_NODE_KINDS = {
    FileExtractorNode: "File Extractor",
    AudioTranscriptionNode: "Audio to text",
}


class FileNodeValidator:
    def validate_file_nodes(
        self,
        node_list: QuerySet[FileExtractorNode | AudioTranscriptionNode],
        *,
        flow_name: str | None = None,
    ) -> None:
        """Refuse the run when a file node has nothing mapped to its input.

        `flow_name` names a subflow in the error; None for the flow the user ran.

        Raises:
            FileNodeValidationError: For the first node with no input.
        """
        for node in node_list:
            self._validate_inputs_exist(node, flow_name)

    def _validate_inputs_exist(
        self, node: FileExtractorNode | AudioTranscriptionNode, flow_name: str | None
    ) -> None:
        if not node.input_map:
            raise FileNodeValidationError(
                node_kind=_NODE_KINDS[type(node)],
                node_label=node_label(node_name=node.node_name, node_number=node.node_number),
                flow_name=flow_name,
            )
