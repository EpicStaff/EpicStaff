from services.graph.events import StopEvent
from services.graph.nodes.node_file_failure import (
    NODE_FILE_FAILURE_SOURCE,
    FileReadingNode,
    NodeFileFailureKind,
    node_file_main_source,
)
from services.run_python_code_service import RunPythonCodeService
from src.shared.models import PythonCodeData
from src.shared.models.storage_scope import StorageCredentials


class FileContentExtractorNode(FileReadingNode):
    TYPE = "FILE_EXTRACTOR"
    KIND_NAME = "File Extractor"

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
        if not input_map:
            raise ValueError("FileContentExtractor input cannot be empty.")

        arg_names = input_map.keys()
        # TODO: this code imports pdfplumber and python-docx. Libraries now come
        # only from the venv, and this node declares none, so it runs in the
        # sandbox's default venv and fails there until it is given its own.
        code_data = PythonCodeData(
            code=self._get_extractor_code(arg_names),
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

    def _get_extractor_code(self, arg_names: list[str]):
        return f"""
import pdfplumber
import csv
import json
from epicstaff_storage import storage
from io import BytesIO, TextIOWrapper
from docx import Document


def extract_text_from_txt(file_data_path: str) -> str:
    file_bytes = read_storage_file(file_data_path)
    return file_bytes.decode("utf-8")


def extract_text_from_pdf(file_data_path: str) -> str:
    file_bytes = read_storage_file(file_data_path)
    text = []

    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            text.append(page_text.strip())

    return "\\n".join(text)


def extract_text_from_csv(file_data_path: str) -> str:
    file_bytes = read_storage_file(file_data_path)

    file_stream = BytesIO(file_bytes)
    wrapper = TextIOWrapper(file_stream, encoding="utf-8")
    delimiter = ","
    reader = csv.reader(wrapper, delimiter=delimiter)

    extracted_rows = []
    for row in reader:
        if not row:
            continue
        if len(row[0].replace(delimiter, "")) != 0:
            extracted_rows.append(",".join(row))

    extracted_text = "\\n".join(extracted_rows)

    wrapper.close()
    file_stream.close()

    return extracted_text


def extract_text_from_json(file_data_path: str) -> str:
    file_bytes = read_storage_file(file_data_path)
    file_stream = BytesIO(file_bytes)

    data = json.load(file_stream)
    result = json.dumps(data, indent=4, ensure_ascii=False)

    file_stream.close()
    return result


def extract_text_from_docx(file_data_path: str) -> str:
    file_bytes = read_storage_file(file_data_path)
    file_stream = BytesIO(file_bytes)

    document = Document(file_stream)
    paragraphs = [p.text for p in document.paragraphs]

    file_stream.close()
    return "\\n".join(paragraphs)


def extract_content(file_data_path: str) -> str:
    file_ext = (
        file_data_path.lower().rsplit(".", 1)[-1] if "." in file_data_path else ""
    )

    if file_ext in ["txt", "text", "log"]:
        return extract_listed_type(extract_text_from_txt, file_data_path)

    elif file_ext == "pdf":
        return extract_listed_type(extract_text_from_pdf, file_data_path)

    elif file_ext == "csv":
        return extract_listed_type(extract_text_from_csv, file_data_path)

    elif file_ext == "json":
        return extract_listed_type(extract_text_from_json, file_data_path)

    elif file_ext in ["docx", "doc"]:
        # python-docx can't read the legacy .doc format at all.
        failure_kind = (
            "{NodeFileFailureKind.LEGACY_WORD}"
            if file_ext == "doc"
            else "{NodeFileFailureKind.DAMAGED}"
        )
        return extract_listed_type(extract_text_from_docx, file_data_path, failure_kind)

    return extract_unlisted_type(file_data_path)


def get_files_content(**files):
    content = dict()
    for key, file_data_path in files.items():
        content[key] = extract_content(file_data_path)
    return content


{node_file_main_source(arg_names, "get_files_content")}
{NODE_FILE_FAILURE_SOURCE}

def extract_listed_type(extract, file_data_path, failure_kind="{NodeFileFailureKind.DAMAGED}"):
    # A file that isn't UTF-8 text keeps the error it has always shown.
    try:
        return extract(file_data_path)
    except (NodeFileFailure, UnicodeDecodeError):
        raise
    except Exception as error:
        fail_on_file(failure_kind, file_data_path, error)


def extract_unlisted_type(file_data_path):
    try:
        return extract_text_from_txt(file_data_path)
    except UnicodeDecodeError as error:
        fail_on_file("{NodeFileFailureKind.UNSUPPORTED}", file_data_path, error)
"""
