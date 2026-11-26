"""The built-in file and audio nodes run in the venvs the sandbox builds for them.

Their code imports libraries the default venv does not carry, so a node that names no
system venv fails on its first import.
"""

import asyncio

import pytest
from dotdict import DotDict

from services.graph.events import StopEvent
from services.graph.nodes.audio_transcription_node import AudioTranscriptionNode
from services.graph.nodes.file_extractor_node import FileContentExtractorNode

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize(
    ("node_class", "system_venv"),
    [
        (FileContentExtractorNode, "file_extractor"),
        (AudioTranscriptionNode, "audio_transcription"),
    ],
)
async def test_builtin_node_submits_its_system_venv(
    run_python_code_service, sandbox, node_class, system_venv
):
    node = node_class(
        session_id=1,
        node_name="node",
        stop_event=StopEvent(),
        input_map={"file": "variables.file"},
        output_variable_path="variables.out",
        python_code_executor_service=run_python_code_service,
    )
    state = {
        "variables": DotDict({"file": "sessions/1/sample.pdf"}),
        "state_history": [],
        "system_variables": {},
        "execution_counts": {},
    }

    running = asyncio.ensure_future(
        node.execute(state, lambda message: None, 0, {"file": "sessions/1/sample.pdf"})
    )
    [task] = await sandbox.wait_for_tasks(1)
    await sandbox.reply(task["execution_id"], result_data='{"file": "text"}')
    await asyncio.wait_for(running, timeout=5)

    assert (task["system_venv"], task["venv_id"]) == (system_venv, None)
