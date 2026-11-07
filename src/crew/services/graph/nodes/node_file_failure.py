"""How the File Extractor and Audio to text nodes report a file they couldn't use.

Both nodes run code crew generates. Its `main` returns an envelope rather than the node's
output: ``{"value": <output>, "file_failure": null}``, or ``{"value": null,
"file_failure": {"kind", "path", "detail"}}`` when the code raised `NodeFileFailure`
(from `NODE_FILE_FAILURE_SOURCE`) for a file it couldn't use. Crew reads the report from
the envelope rather than guessing from an error's text. The report's raw error text goes
only to the log, never to the node's output or its Python message. The source goes after
the nodes' own code, so an error crew doesn't report this way keeps the line number it
has always shown.
"""

import json
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any

from foundation.utils.error_reference import log_with_reference
from loguru import logger
from pydantic import BaseModel
from services.graph.exceptions import NodeFileError
from services.graph.nodes.python_node import CodeResultReading, PythonNode
from src.shared.models import CodeResultData


class NodeFileFailureKind(StrEnum):
    UNSUPPORTED = "unsupported"
    DAMAGED = "damaged"
    LEGACY_WORD = "legacy_word"
    NO_ACCESS = "no_access"
    NOT_FOUND = "not_found"
    STORAGE_UNAVAILABLE = "storage_unavailable"
    UNPROCESSABLE = "unprocessable"


# Generated code: `read_storage_file` reads a file the way `storage.read_bytes` does, and
# `fail_on_file` reports a file the node couldn't use. Storage raises
# StoragePermissionError for a path the flow may not use, FileNotFoundError for a missing
# file, and RuntimeError or OSError when it can't reach the storage service at all.
NODE_FILE_FAILURE_SOURCE = f"""
from epicstaff_storage import StoragePermissionError as _NodeFilePermissionError
from epicstaff_storage import storage as _node_file_storage


class NodeFileFailure(Exception):
    def __init__(self, kind, path, detail):
        super().__init__(kind)
        self.kind = kind
        self.path = path
        self.detail = detail


def fail_on_file(kind, file_data_path, error):
    raise NodeFileFailure(
        kind, str(file_data_path), f"{{type(error).__name__}}: {{error}}"
    ) from None


def read_storage_file(file_data_path):
    try:
        return _node_file_storage.read_bytes(file_data_path)
    except _NodeFilePermissionError as error:
        fail_on_file("{NodeFileFailureKind.NO_ACCESS}", file_data_path, error)
    except FileNotFoundError as error:
        fail_on_file("{NodeFileFailureKind.NOT_FOUND}", file_data_path, error)
    except (RuntimeError, OSError) as error:
        fail_on_file("{NodeFileFailureKind.STORAGE_UNAVAILABLE}", file_data_path, error)
"""

_TEXTS = {
    NodeFileFailureKind.UNSUPPORTED: (
        '{kind_name} node "{label}" can\'t read "{file}": this file type isn\'t supported.'
    ),
    NodeFileFailureKind.DAMAGED: (
        '{kind_name} node "{label}" can\'t read "{file}". Check that the file isn\'t damaged.'
    ),
    NodeFileFailureKind.LEGACY_WORD: (
        '{kind_name} node "{label}" can\'t read "{file}". Save it as .docx and try again.'
    ),
    NodeFileFailureKind.NO_ACCESS: (
        '{kind_name} node "{label}" can\'t open "{file}": this flow has no access to it.'
    ),
    NodeFileFailureKind.NOT_FOUND: '{kind_name} node "{label}" can\'t find "{file}" in storage.',
    NodeFileFailureKind.STORAGE_UNAVAILABLE: (
        '{kind_name} node "{label}" couldn\'t reach file storage. '
        "Try again or contact your administrator (reference: {reference})."
    ),
    NodeFileFailureKind.UNPROCESSABLE: (
        '{kind_name} node "{label}" can\'t process "{file}". '
        "Check that it's a valid audio or video file."
    ),
}


def node_file_main_source(arg_names: list[str], content_function: str) -> str:
    """Return the generated `main`, which calls `content_function` and returns the envelope.

    Args:
        arg_names: The node's input names; `main` takes each and passes it on by name.
        content_function: The name of the generated function that reads the files.
    """
    arguments = ", ".join(f"{name}={name}" for name in arg_names)
    return f"""def main({", ".join(arg_names)}):
    try:
        return {{"value": {content_function}({arguments}), "file_failure": None}}
    except NodeFileFailure as failure:
        report = {{"kind": failure.kind, "path": failure.path, "detail": failure.detail}}
        return {{"value": None, "file_failure": report}}
"""


class NodeFileFailureReport(BaseModel):
    kind: NodeFileFailureKind
    path: str
    detail: str


class NodeFileEnvelope(BaseModel):
    """What the generated `main` returns: the node's output, or the file it couldn't use."""

    value: Any
    file_failure: NodeFileFailureReport | None


def node_file_error(
    report: NodeFileFailureReport, *, kind_name: str, node_label: str, session_id: int
) -> NodeFileError:
    """Return the error for a file the node's generated code reported.

    Logs the report's raw error text, under the reference the message cites when the
    storage service couldn't be reached.

    Args:
        kind_name: Names the node kind in the message, e.g. "File Extractor".
    """
    log_text = (
        "{kind_name} node {node_label} couldn't use {path}: {detail} "
        "(session_id={session_id}, kind={kind})"
    )
    log_arguments = {
        "kind_name": kind_name,
        "node_label": node_label,
        "path": report.path,
        "detail": report.detail,
        "session_id": session_id,
        "kind": report.kind,
    }
    reference = None
    if report.kind is NodeFileFailureKind.STORAGE_UNAVAILABLE:
        reference = log_with_reference(log_text, **log_arguments)
    else:
        logger.warning(log_text, **log_arguments)
    message = _TEXTS[report.kind].format(
        kind_name=kind_name, label=node_label, file=_file_name(report.path), reference=reference
    )
    return NodeFileError(message, reference=reference)


class FileReadingNode(PythonNode):
    """A code node whose generated code reads files from storage and returns the envelope.

    The node's output is the envelope's value. Its Python message shows that value, or,
    when a file couldn't be used, the node's error in place of stderr, so the report's
    raw error text never reaches the message.
    """

    def _read_result(self, result: CodeResultData) -> CodeResultReading:
        if result.returncode != 0:
            return super()._read_result(result)
        envelope = NodeFileEnvelope.model_validate_json(result.result_data)
        shown_result = result.model_dump()
        if envelope.file_failure is None:
            return CodeResultReading(
                error=None,
                shown_result={**shown_result, "result_data": json.dumps(envelope.value)},
                output=lambda: envelope.value,
            )
        error = node_file_error(
            envelope.file_failure,
            kind_name=self.KIND_NAME,
            node_label=self.node_label,
            session_id=self.session_id,
        )
        # The code returned, but the node failed: the message shows a failed run, as it
        # did when the generated code still raised. The shown dict is not a
        # CodeResultData: don't branch on its `failure`, which stays None here.
        return CodeResultReading(
            error=error,
            shown_result={
                **shown_result,
                "result_data": None,
                "stderr": str(error),
                "returncode": 1,
            },
            output=lambda: None,
        )


def _file_name(path: str) -> str:
    """Return the name the user knows the file by: its storage path's last part."""
    return PurePosixPath(path).name or path
