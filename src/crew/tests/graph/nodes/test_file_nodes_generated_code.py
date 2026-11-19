"""The code File Extractor and Audio to text nodes send to the sandbox, and what the nodes
do with its result.

That code is ours, so on a failure it exits 0 and returns `{"node.failure": <fact>, "node.debug": <raw>}`;
the node logs `debug` and streams only the fact. These tests run the generated source the
way the sandbox does (exec, then call `main`) against a fake storage module and fake
extraction libraries, which only exist in the sandbox.
"""

import contextlib
import sys
import types
from pathlib import Path

import pytest
from dotdict import DotDict
from loguru import logger

from services.graph.events import StopEvent
from services.graph.exceptions import ReturnCodeError
from services.graph.nodes.audio_transcription_node import AudioTranscriptionNode
from services.graph.nodes.file_extractor_node import FileContentExtractorNode
from tests.graph.test_graph_builder import FakePythonCodeExecutorService

EXTRACTOR = 'File Extractor node "Extract PDF #2"'
AUDIO = 'Audio to text node "Transcribe call #3"'


class FakeStoragePermissionError(PermissionError):
    pass


def _storage_module(files: dict[str, bytes | Exception]) -> types.ModuleType:
    """`epicstaff_storage` serving `files`; an exception value is raised on read."""

    def read_bytes(path: str) -> bytes:
        content = files[path]
        if isinstance(content, Exception):
            raise content
        return content

    module = types.ModuleType("epicstaff_storage")
    module.StoragePermissionError = FakeStoragePermissionError
    module.storage = types.SimpleNamespace(read_bytes=read_bytes)
    return module


def _run(code: str, monkeypatch, capsys, modules: dict, **inputs):
    """Run the generated code like the sandbox; return (main's result, stderr, exit code)."""
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    namespace: dict = {}
    exec(compile(code, "<code>", "exec"), namespace)
    try:
        result, exit_code = namespace["main"](**inputs), 0
    except SystemExit as exit_info:
        result, exit_code = None, exit_info.code
    return result, capsys.readouterr().err, exit_code


def _extractor(node_name: str = "Extract PDF #2 #18") -> FileContentExtractorNode:
    return FileContentExtractorNode(
        session_id=1,
        node_name=node_name,
        stop_event=StopEvent(),
        input_map={"document": "variables.document"},
        output_variable_path="variables.text",
        python_code_executor_service=FakePythonCodeExecutorService(),
    )


def _audio() -> AudioTranscriptionNode:
    return AudioTranscriptionNode(
        session_id=1,
        node_name="Transcribe call #3 #19",
        input_map={"call": "variables.call"},
        stop_event=StopEvent(),
        output_variable_path="variables.transcript",
        python_code_executor_service=FakePythonCodeExecutorService(),
    )


def _unreadable_document(stream):
    raise ValueError("file is not a zip file")


def _damaged_pdf_library() -> types.ModuleType:
    def open_pdf(stream):
        # Library noise on stderr must not reach the user either.
        print("CropBox missing from /Page, defaulting to MediaBox", file=sys.stderr)
        raise ValueError("PDFSyntaxError: No /Root object! in /tmp/sandbox/job-1/report.pdf")

    return types.SimpleNamespace(open=open_pdf)


@pytest.mark.parametrize(
    ("path", "content", "libraries", "expected"),
    [
        pytest.param(
            "uploads/report.xlsx",
            b"PK\x03\x04\xff\xfe",
            {},
            f'{EXTRACTOR} can\'t read "report.xlsx": this file type isn\'t supported.',
            id="file-type-not-supported",
        ),
        pytest.param(
            "uploads/report.doc",
            b"\xd0\xcf\x11\xe0",
            # An old binary Word file: the .docx reader can't open it.
            {"docx": types.SimpleNamespace(Document=_unreadable_document)},
            f'{EXTRACTOR} can\'t read "report.doc": .doc files aren\'t supported.',
            id="old-word-file",
        ),
        pytest.param(
            "uploads/report.pdf",
            b"%PDF-broken",
            {"pdfplumber": _damaged_pdf_library()},
            f'{EXTRACTOR} can\'t read "report.pdf".',
            id="damaged-file",
        ),
        pytest.param(
            "uploads/report.pdf",
            FakeStoragePermissionError(
                "Access denied: read_bytes on 'uploads/report.pdf' is not within this flow's "
                "allowed files. Allowed paths: [org/secret/]."
            ),
            {},
            f'{EXTRACTOR} can\'t open "report.pdf": this flow has no access to it.',
            id="no-access",
        ),
        pytest.param(
            "uploads/report.pdf",
            FileNotFoundError("Not found in storage: uploads/report.pdf"),
            {},
            f'{EXTRACTOR} can\'t find "report.pdf" in storage.',
            id="file-not-found",
        ),
        pytest.param(
            "uploads/report.pdf",
            RuntimeError("Storage error for 'uploads/report.pdf': http://minio-internal:9000 refused"),
            {},
            f"{EXTRACTOR} couldn't reach file storage.",
            id="storage-error",
        ),
        pytest.param(
            "uploads/report.docx",
            b"PK\x03\x04",
            # The library is missing from the venv: not a fact about the file.
            {"docx": None},
            f"{EXTRACTOR} failed.",
            id="unexpected",
        ),
    ],
)
def test_file_extractor_failure_returns_the_fact(monkeypatch, capsys, path, content, libraries, expected):
    modules = {"epicstaff_storage": _storage_module({path: content}), **libraries}

    result, stderr, exit_code = _run(_extractor().python_code_data.code, monkeypatch, capsys, modules, document=path)

    assert (exit_code, stderr) == (0, "")
    assert result["node.failure"] == expected


def test_file_extractor_failure_debug_holds_the_cause_and_library_output(monkeypatch, capsys):
    path = "uploads/report.pdf"
    modules = {
        "epicstaff_storage": _storage_module({path: b"%PDF-broken"}),
        "pdfplumber": _damaged_pdf_library(),
    }

    result, _, _ = _run(_extractor().python_code_data.code, monkeypatch, capsys, modules, document=path)

    assert "PDFSyntaxError: No /Root object! in /tmp/sandbox/job-1/report.pdf" in result["node.debug"]
    assert "CropBox missing from /Page, defaulting to MediaBox" in result["node.debug"]


def test_file_extractor_reads_a_docx_file_named_doc(monkeypatch, capsys):
    path = "uploads/report.doc"
    paragraphs = [types.SimpleNamespace(text="first"), types.SimpleNamespace(text="second")]
    modules = {
        "epicstaff_storage": _storage_module({path: b"PK\x03\x04"}),
        "docx": types.SimpleNamespace(Document=lambda stream: types.SimpleNamespace(paragraphs=paragraphs)),
    }

    result, stderr, exit_code = _run(_extractor().python_code_data.code, monkeypatch, capsys, modules, document=path)

    assert (result, stderr, exit_code) == ({"document": "first\nsecond"}, "", 0)


def test_file_extractor_reads_a_text_file(monkeypatch, capsys):
    modules = {"epicstaff_storage": _storage_module({"uploads/notes.md": b"hello"})}

    result, stderr, exit_code = _run(
        _extractor().python_code_data.code, monkeypatch, capsys, modules, document="uploads/notes.md"
    )

    assert (result, stderr, exit_code) == ({"document": "hello"}, "", 0)


def test_file_extractor_passes_library_warnings_on_when_it_succeeds(monkeypatch, capsys):
    def open_pdf(stream):
        print("CropBox missing from /Page, defaulting to MediaBox", file=sys.stderr)
        page = types.SimpleNamespace(extract_text=lambda: "page one")
        return contextlib.nullcontext(types.SimpleNamespace(pages=[page]))

    path = "uploads/report.pdf"
    modules = {
        "epicstaff_storage": _storage_module({path: b"%PDF-1.7"}),
        "pdfplumber": types.SimpleNamespace(open=open_pdf),
    }

    result, stderr, exit_code = _run(_extractor().python_code_data.code, monkeypatch, capsys, modules, document=path)

    assert (result, exit_code) == ({"document": "page one"}, 0)
    assert stderr == "CropBox missing from /Page, defaulting to MediaBox\n"


def test_file_extractor_names_a_node_whose_name_has_quotes(monkeypatch, capsys):
    path = "uploads/report.pdf"
    modules = {"epicstaff_storage": _storage_module({path: FileNotFoundError(path)})}
    node = _extractor(node_name="Bob's \"{files}\"")

    result, _, _ = _run(node.python_code_data.code, monkeypatch, capsys, modules, document=path)

    assert result["node.failure"] == 'File Extractor node "Bob\'s "{files}"" can\'t find "report.pdf" in storage.'


def _audio_library(*, decodable: bool) -> types.SimpleNamespace:
    class AudioSegment:
        @staticmethod
        def from_file(path):
            if not decodable:
                raise RuntimeError(f"ffmpeg: {path}: Invalid data found when processing input")
            return AudioSegment()

        def export(self, path, format):
            Path(path).write_bytes(b"RIFF")

    return types.SimpleNamespace(AudioSegment=AudioSegment)


@pytest.mark.parametrize(
    ("content", "decodable", "expected"),
    [
        pytest.param(
            b"not audio",
            False,
            f'{AUDIO} can\'t process "call.mp3".',
            id="audio-cant-be-processed",
        ),
        pytest.param(
            FakeStoragePermissionError("Access denied: read_bytes on 'calls/call.mp3'"),
            None,
            f'{AUDIO} can\'t open "call.mp3": this flow has no access to it.',
            id="no-access",
        ),
        pytest.param(
            FileNotFoundError("Not found in storage: calls/call.mp3"),
            None,
            f'{AUDIO} can\'t find "call.mp3" in storage.',
            id="file-not-found",
        ),
        pytest.param(
            RuntimeError("Storage error for 'calls/call.mp3': http://minio-internal:9000 refused"),
            None,
            f"{AUDIO} couldn't reach file storage.",
            id="storage-error",
        ),
        # Decoding works, but the transcription library is missing from the venv.
        pytest.param(b"ID3", True, f"{AUDIO} failed.", id="unexpected"),
    ],
)
def test_audio_failure_returns_the_fact(monkeypatch, capsys, content, decodable, expected):
    path = "calls/call.mp3"
    modules = {"epicstaff_storage": _storage_module({path: content}), "faster_whisper": None}
    if decodable is not None:
        modules["pydub"] = _audio_library(decodable=decodable)

    result, stderr, exit_code = _run(_audio().python_code_data.code, monkeypatch, capsys, modules, call=path)

    assert (exit_code, stderr) == (0, "")
    assert result["node.failure"] == expected


def test_audio_failure_debug_holds_the_cause(monkeypatch, capsys):
    path = "calls/call.mp3"
    modules = {
        "epicstaff_storage": _storage_module({path: b"not audio"}),
        "pydub": _audio_library(decodable=False),
    }

    result, _, _ = _run(_audio().python_code_data.code, monkeypatch, capsys, modules, call=path)

    assert "Invalid data found when processing input" in result["node.debug"]


@pytest.fixture
def error_logs():
    records: list[str] = []
    sink_id = logger.add(records.append, level="ERROR")
    yield records
    logger.remove(sink_id)


def _state(**variables) -> dict:
    return {
        "variables": DotDict(variables),
        "state_history": [],
        "system_variables": {},
        "execution_counts": {},
    }


def _streamed(messages) -> str:
    return repr([message.to_payload() for message in messages])


@pytest.mark.asyncio
async def test_file_extractor_node_streams_the_fact_and_logs_the_cause(monkeypatch, error_logs):
    path = "uploads/report.pdf"
    monkeypatch.setitem(sys.modules, "epicstaff_storage", _storage_module({path: b"%PDF-broken"}))
    monkeypatch.setitem(sys.modules, "pdfplumber", _damaged_pdf_library())
    messages = []

    with pytest.raises(ReturnCodeError) as raised:
        await _extractor().run(_state(document=path), writer=messages.append)

    fact = f'{EXTRACTOR} can\'t read "report.pdf".'
    assert str(raised.value) == fact
    error_cards = [
        message.message_data.details
        for message in messages
        if getattr(message.message_data, "message_type", None) == "error"
    ]
    assert error_cards == [fact]
    assert "PDFSyntaxError" not in _streamed(messages)
    assert "CropBox" not in _streamed(messages)
    (record,) = [record for record in error_logs if "PDFSyntaxError" in record]
    assert "session_id=1" in record
    assert "Extract PDF #2 #18" in record


@pytest.mark.asyncio
async def test_audio_node_streams_the_fact_and_logs_the_cause(monkeypatch, error_logs):
    path = "calls/call.mp3"
    monkeypatch.setitem(sys.modules, "epicstaff_storage", _storage_module({path: b"not audio"}))
    monkeypatch.setitem(sys.modules, "pydub", _audio_library(decodable=False))
    messages = []

    with pytest.raises(ReturnCodeError) as raised:
        await _audio().run(_state(call=path), writer=messages.append)

    assert str(raised.value) == f'{AUDIO} can\'t process "call.mp3".'
    assert "Invalid data found" not in _streamed(messages)
    assert any("Invalid data found" in record and "session_id=1" in record for record in error_logs)


@pytest.mark.asyncio
async def test_file_extractor_node_stores_the_text_when_it_succeeds(monkeypatch):
    path = "uploads/notes.md"
    monkeypatch.setitem(sys.modules, "epicstaff_storage", _storage_module({path: b"hello"}))

    state = await _extractor().run(_state(document=path), writer=lambda message: None)

    assert state["variables"].text.document == "hello"
