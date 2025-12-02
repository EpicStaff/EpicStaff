from django.db.models import QuerySet
from tables.exceptions import FileNodeValidationError
from tables.models import FileExtractorNode, AudioTranscriptionNode


class FileNodeValidator:

    DOMAIN_NAME = "variables"
    FILES_IN_DOMAIN = "files"

    def validate_file_nodes(
        self, node_list: QuerySet[FileExtractorNode | AudioTranscriptionNode]
    ) -> None:
        """
        Validates input_map of all file_extractor_nodes in the queryset.
        Raises FileNodeValidationError if any input is not valid.
        """
        for node in node_list:
            self._validate_inputs_exist(node)
            self._validate_inputs_are_files(node)

    def _validate_inputs_exist(
        self, node: FileExtractorNode | AudioTranscriptionNode
    ) -> None:
        if not node.input_map:
            raise FileNodeValidationError(
                f"FileNode requires input_map. Issue with node: {node.node_name}"
            )

    def _validate_inputs_are_files(
        self, node: FileExtractorNode | AudioTranscriptionNode
    ) -> None:
        for key, value in node.input_map.items():
            if not value.startswith(f"{self.DOMAIN_NAME}.{self.FILES_IN_DOMAIN}"):
                raise FileNodeValidationError(
                    f"FileNode requires files as input. Node: {node.node_name}; {key}: {value}"
                )
