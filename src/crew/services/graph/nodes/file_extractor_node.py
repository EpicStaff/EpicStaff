from services.graph.events import StopEvent
from services.graph.nodes.python_node import PythonNode
from models.request_models import PythonCodeData
from services.run_python_code_service import RunPythonCodeService


class FileContentExtractorNode(PythonNode):
    TYPE = "FILE_EXTRACTOR"

    def __init__(
        self,
        session_id: int,
        node_name: str,
        stop_event: StopEvent,
        input_map: dict,
        output_variable_path: str,
        python_code_executor_service: RunPythonCodeService,
    ):
        if not input_map:
            raise ValueError(f"FileContentExtractor input cannot be empty.")

        arg_names = input_map.keys()
        code_data = PythonCodeData(
            venv_name="default",
            code=self._get_extractor_code(arg_names),
            entrypoint="main",
            libraries=["pdfplumber", "python-docx"],
        )

        super().__init__(
            session_id=session_id,
            node_name=node_name,
            stop_event=stop_event,
            input_map=input_map,
            output_variable_path=output_variable_path,
            python_code_executor_service=python_code_executor_service,
            python_code_data=code_data,
        )

    def _get_extractor_code(self, arg_names: list[str]):
        return f"""
import base64
import pdfplumber
import csv
import json
from io import BytesIO, TextIOWrapper
from docx import Document


def extract_text_from_txt(file_data_base64: str) -> str:
    file_bytes = base64.b64decode(file_data_base64)
    return file_bytes.decode("utf-8")


def extract_text_from_pdf(file_data_base64: str) -> str:
    file_bytes = base64.b64decode(file_data_base64)
    text = []

    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            text.append(page_text.strip())

    return "\\n".join(text)


def extract_text_from_csv(file_data_base64: str) -> str:
    file_bytes = base64.b64decode(file_data_base64)

    file_stream = BytesIO(file_bytes)
    wrapper = TextIOWrapper(file_stream, encoding="utf-8")
    delimiter = ","
    reader = csv.reader(wrapper, delimiter=delimiter)

    extracted_rows = []
    for row in reader:
        if len(row[0].replace(delimiter, "")) != 0:
            extracted_rows.append(",".join(row))

    extracted_text = "\\n".join(extracted_rows)

    wrapper.close()
    file_stream.close()

    return extracted_text


def extract_text_from_json(file_data_base64: str) -> str:
    file_bytes = base64.b64decode(file_data_base64)
    file_stream = BytesIO(file_bytes)

    data = json.load(file_stream)
    result = json.dumps(data, indent=4, ensure_ascii=False)

    file_stream.close()
    return result


def extract_text_from_docx(file_data_base64: str) -> str:
    file_bytes = base64.b64decode(file_data_base64)
    file_stream = BytesIO(file_bytes)

    document = Document(file_stream)
    paragraphs = [p.text for p in document.paragraphs]

    file_stream.close()
    return "\\n".join(paragraphs)


def extract_content(file_name: str, file_data_base64: str) -> str:
    file_ext = file_name.lower().split(".")[-1] if "." in file_name else ""

    if file_ext in ["txt", "text", "log"]:
        return extract_text_from_txt(file_data_base64)

    elif file_ext == "pdf":
        return extract_text_from_pdf(file_data_base64)

    elif file_ext == "csv":
        return extract_text_from_csv(file_data_base64)

    elif file_ext == "json":
        return extract_text_from_json(file_data_base64)

    elif file_ext in ["docx", "doc"]:
        return extract_text_from_docx(file_data_base64)

    return extract_text_from_txt(file_data_base64)


def get_files_content(**files):
    content = dict()
    for key, file_ in files.items():
        content[key] = extract_content(file_.name, file_.base64_data)
    return content


def main({", ".join(arg_names)}):
    content = get_files_content({", ".join(f"{a}={a}" for a in arg_names)})
    return content
"""
