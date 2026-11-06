"""How the File Extractor and Audio to text nodes report a file they couldn't use.

Both nodes run code crew generates. That code includes `NODE_FILE_FAILURE_SOURCE`, which
raises `NodeFileFailure` with a JSON report of what went wrong. The sandbox writes it as
its last stderr line, "NodeFileFailure on line <N>: <report>", and crew reads the report
back rather than guessing from an error's text. The report's raw error text goes only to
the log. The source goes after the nodes' own code, so an error crew doesn't report this
way keeps the line number it has always shown.
"""

import json
import re
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any

from foundation.utils.error_reference import log_with_reference
from loguru import logger
from services.graph.exceptions import NodeFileError


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
import json as _node_file_json

from epicstaff_storage import StoragePermissionError as _NodeFilePermissionError
from epicstaff_storage import storage as _node_file_storage


class NodeFileFailure(Exception):
    pass


def fail_on_file(kind, file_data_path, error):
    report = {{
        "kind": kind,
        "path": str(file_data_path),
        "detail": f"{{type(error).__name__}}: {{error}}",
    }}
    raise NodeFileFailure(_node_file_json.dumps(report)) from None


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

_REPORT_LINE = re.compile(r"NodeFileFailure on line \d+: (?P<report>\{.*\})")

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


def node_file_error(
    result: dict[str, Any], *, kind_name: str, node_label: str, session_id: int
) -> NodeFileError | None:
    """Return the error for a file the node's generated code reported, or None if it reported none.

    Logs the report's raw error text, under the reference the message cites when the
    storage service couldn't be reached.

    Args:
        result: What `RunPythonCodeService.run_code` returned for the node's code.
        kind_name: Names the node kind in the message, e.g. "File Extractor".
    """
    report = _read_report(result["stderr"])
    if report is None:
        return None
    kind, path, detail = report
    reference = None
    log_text = (
        "{kind_name} node {node_label} couldn't use {path}: {detail} "
        "(session_id={session_id}, kind={kind})"
    )
    if kind is NodeFileFailureKind.STORAGE_UNAVAILABLE:
        reference = log_with_reference(
            log_text,
            kind_name=kind_name,
            node_label=node_label,
            path=path,
            detail=detail,
            session_id=session_id,
            kind=kind,
        )
    else:
        logger.warning(
            log_text,
            kind_name=kind_name,
            node_label=node_label,
            path=path,
            detail=detail,
            session_id=session_id,
            kind=kind,
        )
    message = _TEXTS[kind].format(
        kind_name=kind_name, label=node_label, file=_file_name(path), reference=reference
    )
    return NodeFileError(message, correlation_id=reference)


def _read_report(stderr: str) -> tuple[NodeFileFailureKind, str, str] | None:
    lines = stderr.strip().splitlines()
    if not lines:
        return None
    match = _REPORT_LINE.fullmatch(lines[-1])
    if match is None:
        return None
    try:
        report = json.loads(match["report"])
        kind = NodeFileFailureKind(report["kind"])
        path = report["path"]
        detail = report["detail"]
    except (ValueError, TypeError, KeyError):
        return None
    if not isinstance(path, str) or not isinstance(detail, str):
        return None
    return kind, path, detail


def _file_name(path: str) -> str:
    """Return the name the user knows the file by: its storage path's last part."""
    return PurePosixPath(path).name or path
