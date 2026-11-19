from services.graph.events import StopEvent
from services.graph.exceptions import NodeConfigurationError
from services.graph.nodes.generated_code_node import GeneratedCodeNode
from services.run_python_code_service import RunPythonCodeService
from src.shared.models import PythonCodeData
from src.shared.models.storage_scope import StorageCredentials
from utils.node_label import runtime_node_name_to_label


class FileContentExtractorNode(GeneratedCodeNode):
    TYPE = "FILE_EXTRACTOR"
    LABEL = "File Extractor node"

    def __init__(
        self,
        session_id: int,
        node_name: str,
        stop_event: StopEvent,
        input_map: dict,
        output_variable_path: str,
        python_code_executor_service: RunPythonCodeService,
        storage_allowed_paths: list[str] | None = None,
        storage_org_prefix: str | None = None,
        org_id: int | None = None,
        storage_credentials: StorageCredentials | None = None,
    ):
        node = f'{self.LABEL} "{runtime_node_name_to_label(node_name)}"'
        if not input_map:
            raise NodeConfigurationError(f"{node} has no input file.")

        arg_names = input_map.keys()
        # TODO: this code imports pdfplumber and python-docx. Libraries now come
        # only from the venv, and this node declares none, so it runs in the
        # sandbox's default venv and fails there until it is given its own.
        code_data = PythonCodeData(
            code=_extractor_code(node, arg_names),
            entrypoint="main",
            use_storage=True,
            storage_allowed_paths=storage_allowed_paths,
            storage_org_prefix=storage_org_prefix,
            session_id=session_id,
            org_id=org_id,
        )

        super().__init__(
            session_id=session_id,
            node_name=node_name,
            stop_event=stop_event,
            input_map=input_map,
            output_variable_path=output_variable_path,
            python_code_executor_service=python_code_executor_service,
            python_code_data=code_data,
            storage_credentials=storage_credentials,
        )


def _extractor_code(node: str, arg_names) -> str:
    """Return the sandbox code that extracts the text of each input file.

    The code is ours, not the user's, so it reports its own failures: it exits 0 and
    returns `{"node.failure": <fact>, "node.debug": <traceback and the libraries' stderr>}`, and
    GeneratedCodeNode logs `debug` and streams only the fact. The fact names a known
    problem with the file or storage, or reads `<node> failed.` for anything else. On
    success the libraries' stderr is passed on.
    """
    arguments = ", ".join(arg_names)
    files = ", ".join(f"{name!r}: {name}" for name in arg_names)
    return (
        f"_NODE = {node!r}\n"
        + _EXTRACTOR_CODE
        + f"\n\ndef main({arguments}):\n    return _run({{{files}}})\n"
    )


_EXTRACTOR_CODE = r"""
import contextlib
import csv
import io
import json
import sys
import traceback


class _FileFailure(Exception):
    pass


def _file_name(file_path):
    return file_path.rsplit("/", 1)[-1]


def _read_bytes(file_path):
    from epicstaff_storage import StoragePermissionError, storage

    file_name = _file_name(file_path)
    try:
        return storage.read_bytes(file_path)
    except StoragePermissionError:
        raise _FileFailure(
            f"{_NODE} can't open \"{file_name}\": this flow has no access to it."
        )
    except FileNotFoundError:
        raise _FileFailure(f"{_NODE} can't find \"{file_name}\" in storage.")
    except Exception:
        raise _FileFailure(f"{_NODE} couldn't reach file storage.")


def _text(file_bytes):
    return file_bytes.decode("utf-8")


def _pdf(file_bytes):
    import pdfplumber

    text = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            text.append(page_text.strip())
    return "\n".join(text)


def _csv(file_bytes):
    delimiter = ","
    reader = csv.reader(io.TextIOWrapper(io.BytesIO(file_bytes), encoding="utf-8"), delimiter=delimiter)
    extracted_rows = []
    for row in reader:
        if not row:
            continue
        if len(row[0].replace(delimiter, "")) != 0:
            extracted_rows.append(",".join(row))
    return "\n".join(extracted_rows)


def _json(file_bytes):
    return json.dumps(json.loads(file_bytes), indent=4, ensure_ascii=False)


def _docx(file_bytes):
    from docx import Document

    document = Document(io.BytesIO(file_bytes))
    return "\n".join(paragraph.text for paragraph in document.paragraphs)


_EXTRACTORS = {
    "txt": _text,
    "text": _text,
    "log": _text,
    "pdf": _pdf,
    "csv": _csv,
    "json": _json,
    "docx": _docx,
    "doc": _docx,
}


def _extract(file_path):
    file_name = _file_name(file_path)
    extension = file_name.lower().rsplit(".", 1)[-1] if "." in file_name else ""
    file_bytes = _read_bytes(file_path)
    extractor = _EXTRACTORS.get(extension)
    if extractor is None:
        # Any other file is read as text, so a binary one is a type this node can't read.
        try:
            return _text(file_bytes)
        except UnicodeDecodeError:
            raise _FileFailure(
                f"{_NODE} can't read \"{file_name}\": this file type isn't supported."
            )
    try:
        return extractor(file_bytes)
    except ImportError:
        raise
    except Exception:
        # A .doc file is read as .docx, which works when it is one under an old name.
        if extension == "doc":
            raise _FileFailure(f"{_NODE} can't read \"{file_name}\": .doc files aren't supported.")
        raise _FileFailure(f"{_NODE} can't read \"{file_name}\".")


def _run(files):
    library_output = io.StringIO()
    with contextlib.redirect_stderr(library_output):
        try:
            result = {key: _extract(file_path) for key, file_path in files.items()}
        except Exception as error:
            fact = str(error) if isinstance(error, _FileFailure) else f"{_NODE} failed."
            return {"node.failure": fact, "node.debug": traceback.format_exc() + library_output.getvalue()}
    sys.stderr.write(library_output.getvalue())
    return result
"""
