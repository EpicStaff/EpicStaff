"""File Extractor and Audio to text nodes tell the user, in words, why a file couldn't be used.

The nodes' generated code runs through the sandbox's own wrapper with the real
`epicstaff_storage` library. Only what lies outside it is stood in for: the S3 client
(`boto3`), and the extraction and audio libraries, which crew's venv doesn't have.
"""

import base64
import json
import re
import textwrap
from pathlib import Path

import pytest
from dotdict import DotDict
from foundation.utils.error_reference import REFERENCE_PATTERN
from loguru import logger

from models.graph_models import GraphMessage, PythonMessageData
from services.graph.events import StopEvent
from services.graph.exceptions import NodeExecutionError
from services.graph.graph_session_manager_service import GraphSessionManagerService
from services.graph.nodes.audio_transcription_node import AudioTranscriptionNode
from services.graph.nodes.file_extractor_node import FileContentExtractorNode
from tests.graph.subgraphs.sandbox_wrapper_runner import SandboxWrapperRunCodeService

pytestmark = pytest.mark.asyncio

RAW_STORAGE_TEXT = "minio-internal.epicstaff.local:9000"
RAW_AUDIO_TEXT = "/tmp/tmpk3j2x9ab"
RAW_LIBRARY_TEXT = "/opt/sandbox/venvs/default/site-packages"
CITED_REFERENCE = rf"\(reference: ({REFERENCE_PATTERN})\)\.$"

STUB_MODULES = {
    "boto3/__init__.py": f"""
        import base64
        import json
        import os

        from botocore.exceptions import ClientError


        class _Body:
            def __init__(self, content):
                self._content = content

            def read(self):
                return self._content


        class _Client:
            def get_object(self, Bucket, Key):
                if os.environ.get("FAKE_STORAGE_DOWN"):
                    raise ConnectionError("Could not connect to http://{RAW_STORAGE_TEXT}/bucket")
                files = json.loads(os.environ.get("FAKE_STORAGE_FILES", "{{}}"))
                if Key not in files:
                    raise ClientError({{"Error": {{"Code": "NoSuchKey"}}}}, "GetObject")
                return {{"Body": _Body(base64.b64decode(files[Key]))}}


        def client(*args, **kwargs):
            return _Client()
    """,
    "pdfplumber/__init__.py": f"""
        def open(stream):
            raise ValueError("No /Root object! at {RAW_LIBRARY_TEXT}")
    """,
    "docx/__init__.py": f"""
        def Document(stream):
            raise KeyError("There is no item named 'word/document.xml' in {RAW_LIBRARY_TEXT}")
    """,
    "pydub/__init__.py": f"""
        class AudioSegment:
            @staticmethod
            def from_file(path):
                raise RuntimeError("ffmpeg: {RAW_AUDIO_TEXT}: Invalid data found when processing input")
    """,
    "faster_whisper/__init__.py": "WhisperModel = None\n",
}


@pytest.fixture
def stub_library_dir(tmp_path) -> Path:
    for relative_path, source in STUB_MODULES.items():
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(source), encoding="utf-8")
    return tmp_path


@pytest.fixture
def captured_logs():
    records: list[str] = []
    sink_id = logger.add(records.append, level="WARNING")
    yield records
    logger.remove(sink_id)


def storage_environment(files: dict[str, bytes] | None = None, **extra: str) -> dict[str, str]:
    return {
        "STORAGE_ENDPOINT": "http://storage.test",
        "STORAGE_ACCESS_KEY": "test-access",
        "STORAGE_SECRET_KEY": "test-secret",
        "STORAGE_BUCKET_NAME": "test-bucket",
        "FAKE_STORAGE_FILES": json.dumps(
            {path: base64.b64encode(content).decode() for path, content in (files or {}).items()}
        ),
        **extra,
    }


def file_extractor(service) -> FileContentExtractorNode:
    return FileContentExtractorNode(
        session_id=5,
        node_name="Extract PDF #2 #77",
        stop_event=StopEvent(),
        input_map={"document": "variables.document"},
        output_variable_path="variables.content",
        python_code_executor_service=service,
    )


def audio_to_text(service) -> AudioTranscriptionNode:
    return AudioTranscriptionNode(
        session_id=5,
        node_name="Transcribe call #3 #78",
        input_map={"recording": "variables.recording"},
        stop_event=StopEvent(),
        output_variable_path="variables.transcript",
        python_code_executor_service=service,
    )


def build_state(**variables) -> dict:
    return {"variables": DotDict(variables), "state_history": [], "system_variables": {}}


async def run_failing(node, state) -> tuple[NodeExecutionError, list[str], list[dict]]:
    """Run `node`, expecting it to fail; return the error, error cards and shown code results."""
    messages: list[GraphMessage] = []
    with pytest.raises(NodeExecutionError) as raised:
        await node.run(state, writer=messages.append)
    cards = [
        message.message_data.details
        for message in messages
        if getattr(message.message_data, "message_type", None) == "error"
    ]
    shown_results = [
        message.message_data.python_code_execution_data
        for message in messages
        if isinstance(message.message_data, PythonMessageData)
    ]
    return raised.value, cards, shown_results


def session_error(error: NodeExecutionError) -> str:
    return GraphSessionManagerService._public_session_error(5, error)


@pytest.mark.parametrize(
    ("environment", "path", "expected"),
    [
        pytest.param(
            storage_environment({"reports/2026/report.xlsx": b"PK\x03\x04\xff\xfe binary"}),
            "reports/2026/report.xlsx",
            'File Extractor node "Extract PDF #2" can\'t read "report.xlsx": '
            "this file type isn't supported.",
            id="unsupported",
        ),
        pytest.param(
            storage_environment(
                {"reports/report.pdf": b"%PDF"}, STORAGE_ALLOWED_PATHS='["other/"]'
            ),
            "reports/report.pdf",
            'File Extractor node "Extract PDF #2" can\'t open "report.pdf": '
            "this flow has no access to it.",
            id="no-access",
        ),
        pytest.param(
            storage_environment(),
            "reports/report.pdf",
            'File Extractor node "Extract PDF #2" can\'t find "report.pdf" in storage.',
            id="not-found",
        ),
    ],
)
async def test_file_extractor_names_the_file_it_couldnt_use(
    stub_library_dir, environment, path, expected
):
    service = SandboxWrapperRunCodeService((str(stub_library_dir),), environment)

    error, cards, shown_results = await run_failing(
        file_extractor(service), build_state(document=path)
    )

    assert cards == [expected]
    assert session_error(error) == expected
    # The run's Python message shows the node's error, not the generated code's report.
    assert [result["stderr"] for result in shown_results] == [expected]


@pytest.mark.parametrize(
    "environment",
    [
        pytest.param(storage_environment(FAKE_STORAGE_DOWN="1"), id="unreachable"),
        pytest.param({}, id="not-configured"),
    ],
)
async def test_file_extractor_storage_failure_cites_a_reference_and_logs_the_raw_error(
    stub_library_dir, captured_logs, environment
):
    service = SandboxWrapperRunCodeService((str(stub_library_dir),), environment)

    error, cards, shown_results = await run_failing(
        file_extractor(service), build_state(document="reports/report.pdf")
    )

    (card,) = cards
    reference = re.search(CITED_REFERENCE, card).group(1)
    assert card == (
        'File Extractor node "Extract PDF #2" couldn\'t reach file storage. '
        f"Try again or contact your administrator (reference: {reference})."
    )
    assert session_error(error) == f"The flow failed. Try again or contact your administrator (reference: {reference})."
    assert [result["stderr"] for result in shown_results] == [card]
    # The session's WARNING repeats the user text, which cites the reference too.
    (logged,) = [
        record
        for record in captured_logs
        if record.record["level"].name == "ERROR" and f"(reference: {reference})" in record
    ]
    assert ("Storage error" in logged) or ("Missing required environment variables" in logged)


async def test_file_extractor_raw_storage_text_reaches_only_the_log(
    stub_library_dir, captured_logs
):
    service = SandboxWrapperRunCodeService(
        (str(stub_library_dir),), storage_environment(FAKE_STORAGE_DOWN="1")
    )

    error, cards, shown_results = await run_failing(
        file_extractor(service), build_state(document="reports/report.pdf")
    )

    assert RAW_STORAGE_TEXT not in cards[0]
    assert RAW_STORAGE_TEXT not in json.dumps(shown_results)
    assert RAW_STORAGE_TEXT not in session_error(error)
    assert any(RAW_STORAGE_TEXT in record for record in captured_logs)


async def test_file_extractor_still_reads_a_text_file(stub_library_dir):
    service = SandboxWrapperRunCodeService(
        (str(stub_library_dir),), storage_environment({"notes/today.txt": b"hello"})
    )

    state = await file_extractor(service).run(
        build_state(document="notes/today.txt"), writer=lambda message: None
    )

    assert state["variables"].content == {"document": "hello"}


async def test_audio_to_text_file_it_cant_process_keeps_the_raw_error_in_the_log(
    stub_library_dir, captured_logs
):
    service = SandboxWrapperRunCodeService(
        (str(stub_library_dir),), storage_environment({"calls/call.mp3": b"not audio"})
    )

    error, cards, shown_results = await run_failing(
        audio_to_text(service), build_state(recording="calls/call.mp3")
    )

    expected = (
        'Audio to text node "Transcribe call #3" can\'t process "call.mp3". '
        "Check that it's a valid audio or video file."
    )
    assert cards == [expected]
    assert session_error(error) == expected
    assert RAW_AUDIO_TEXT not in json.dumps(shown_results)
    assert any(RAW_AUDIO_TEXT in record for record in captured_logs)


async def test_audio_to_text_names_its_kind_in_storage_messages(stub_library_dir):
    service = SandboxWrapperRunCodeService((str(stub_library_dir),), storage_environment())

    _, cards, _ = await run_failing(
        audio_to_text(service), build_state(recording="calls/call.mp3")
    )

    assert cards == ['Audio to text node "Transcribe call #3" can\'t find "call.mp3" in storage.']


@pytest.mark.parametrize(
    ("path", "content", "expected_name"),
    [
        pytest.param("reports/report.pdf", b"%PDF-1.7 broken", "report.pdf", id="pdf"),
        pytest.param("reports/report.docx", b"PK broken", "report.docx", id="docx"),
        pytest.param("reports/data.json", b"{not json", "data.json", id="json"),
    ],
)
async def test_file_extractor_damaged_file_of_a_listed_type_is_named(
    stub_library_dir, captured_logs, path, content, expected_name
):
    service = SandboxWrapperRunCodeService(
        (str(stub_library_dir),), storage_environment({path: content})
    )

    error, cards, shown_results = await run_failing(file_extractor(service), build_state(document=path))

    expected = (
        f'File Extractor node "Extract PDF #2" can\'t read "{expected_name}". '
        "Check that the file isn't damaged."
    )
    assert cards == [expected]
    assert session_error(error) == expected
    assert [result["stderr"] for result in shown_results] == [expected]
    assert any(path in record and "kind=damaged" in record for record in captured_logs)


async def test_file_extractor_legacy_word_file_asks_for_docx(stub_library_dir):
    service = SandboxWrapperRunCodeService(
        (str(stub_library_dir),), storage_environment({"reports/report.doc": b"\xd0\xcf\x11\xe0"})
    )

    error, cards, _ = await run_failing(file_extractor(service), build_state(document="reports/report.doc"))

    expected = 'File Extractor node "Extract PDF #2" can\'t read "report.doc". Save it as .docx and try again.'
    assert cards == [expected]
    assert session_error(error) == expected


async def test_file_extractor_library_text_reaches_only_the_log(stub_library_dir, captured_logs):
    service = SandboxWrapperRunCodeService(
        (str(stub_library_dir),), storage_environment({"reports/report.pdf": b"%PDF"})
    )

    error, cards, shown_results = await run_failing(
        file_extractor(service), build_state(document="reports/report.pdf")
    )

    assert RAW_LIBRARY_TEXT not in cards[0]
    assert RAW_LIBRARY_TEXT not in json.dumps(shown_results)
    assert RAW_LIBRARY_TEXT not in session_error(error)
    assert any(RAW_LIBRARY_TEXT in record for record in captured_logs)


async def test_file_extractor_csv_that_isnt_utf8_keeps_the_sandbox_text(stub_library_dir):
    # A listed type that isn't UTF-8 text fails as it always has.
    service = SandboxWrapperRunCodeService(
        (str(stub_library_dir),),
        storage_environment({"exports/clients.csv": "name;city\nZo\u00eb;K\u00f6ln\n".encode("latin-1")}),
    )

    _, cards, shown_results = await run_failing(
        file_extractor(service), build_state(document="exports/clients.csv")
    )

    (card,) = cards
    assert re.fullmatch(
        r"UnicodeDecodeError on line \d+: 'utf-8' codec can't decode byte 0x\w+ in position \d+: "
        r"invalid continuation byte",
        card.strip(),
    )
    assert [result["stderr"] for result in shown_results] == [card]


class SandboxFailedRunCodeService:
    """Stands in for RunPythonCodeService when the sandbox itself couldn't run the code."""

    async def run_code(self, python_code_data, inputs, **kwargs):
        return {
            "execution_id": "test",
            "returncode": 1,
            "stdout": "",
            "stderr": "Node execution failed (reference: 0a1b2c3d4e5f)",
            "result_data": None,
            "correlation_id": "0a1b2c3d4e5f",
        }


@pytest.mark.parametrize(
    ("node", "expected"),
    [
        pytest.param(
            file_extractor,
            'File Extractor node "Extract PDF #2" couldn\'t run its code. '
            "Try again or contact your administrator (reference: 0a1b2c3d4e5f).",
            id="file-extractor",
        ),
        pytest.param(
            audio_to_text,
            'Audio to text node "Transcribe call #3" couldn\'t run its code. '
            "Try again or contact your administrator (reference: 0a1b2c3d4e5f).",
            id="audio-to-text",
        ),
    ],
)
async def test_sandbox_failure_names_the_nodes_own_kind(node, expected):
    error, cards, _ = await run_failing(
        node(SandboxFailedRunCodeService()), build_state(document="a.pdf", recording="a.mp3")
    )

    assert cards == [expected]
    assert session_error(error) == "The flow failed. Try again or contact your administrator (reference: 0a1b2c3d4e5f)."
