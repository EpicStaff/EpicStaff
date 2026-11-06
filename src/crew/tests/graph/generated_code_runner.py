"""Run the code crew generates in a subprocess, and answer with the result of a successful run.

Nodes that generate code read its result back: a file node's envelope, a decision table's
condition results and changed variables. Running that code for real keeps these tests
from passing against a hand-written result that drifted from it. The runner covers only
successful runs of crew's generated code, and copies only what that code relies on: the
module globals include `json`, and the entrypoint gets its inputs as a `DotDict`, as in
the sandbox. It doesn't report failures the way the sandbox does, so code that raises
fails the test instead; a test that needs a failed run answers it with a fake from
`tests.graph.code_results`.
"""

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.shared.models import CodeResultData, PythonCodeData

# dotdict and epicstaff_storage, which the code imports, are top-level packages of src/shared.
_SHARED_DIR = Path(__file__).resolve().parents[3] / "shared"
_DRIVER = """
import json
import sys

from dotdict import DotDict

code_path, entrypoint, inputs_path, value_path = sys.argv[1:5]
with open(code_path, encoding="utf-8") as code_file:
    source = code_file.read()
with open(inputs_path, encoding="utf-8") as inputs_file:
    inputs = json.load(inputs_file)
namespace = {"__name__": "__main__", "json": json}
exec(compile(source, "<code>", "exec"), namespace)
value = namespace[entrypoint](**DotDict(inputs))
with open(value_path, "w", encoding="utf-8") as value_file:
    json.dump(value, value_file)
"""

# Answers a run instead of running its code, or returns None to let the code run.
Answer = Callable[[PythonCodeData, dict[str, Any]], CodeResultData | None]


def run_generated_code(
    code: str,
    entrypoint: str,
    inputs: dict[str, Any],
    extra_python_path: tuple[str, ...] = (),
    extra_environment: dict[str, str] | None = None,
) -> CodeResultData:
    """Return the result crew gets when ``code`` runs and returns.

    ``extra_python_path`` comes first on the path, so a test can stand in for a library
    the code imports; ``extra_environment`` is added to the code's environment.

    Raises:
        subprocess.CalledProcessError: The code raised; its traceback is on stderr.
    """
    with tempfile.TemporaryDirectory() as directory:
        code_path = Path(directory) / "code.py"
        inputs_path = Path(directory) / "inputs.json"
        value_path = Path(directory) / "value.json"
        code_path.write_text(code, encoding="utf-8")
        inputs_path.write_text(json.dumps(inputs), encoding="utf-8")
        python_path = os.pathsep.join(
            path
            for path in (*extra_python_path, str(_SHARED_DIR), os.environ.get("PYTHONPATH"))
            if path
        )
        environment = {**os.environ, **(extra_environment or {}), "PYTHONPATH": python_path}
        subprocess.run(
            [
                sys.executable,
                "-c",
                _DRIVER,
                str(code_path),
                entrypoint,
                str(inputs_path),
                str(value_path),
            ],
            env=environment,
            timeout=60,
            check=True,
        )
        result_data = value_path.read_text(encoding="utf-8")
    return CodeResultData(
        execution_id="test", returncode=0, stdout="", stderr="", result_data=result_data
    )


class GeneratedCodeRunCodeService:
    """Stands in for RunPythonCodeService, running every code with `run_generated_code`.

    Args:
        answer: Answers the runs it returns a result for, instead of running their code.
    """

    def __init__(
        self,
        extra_python_path: tuple[str, ...] = (),
        extra_environment: dict[str, str] | None = None,
        answer: Answer | None = None,
    ) -> None:
        self.extra_python_path = extra_python_path
        self.extra_environment = extra_environment
        self.answer = answer

    async def run_code(self, python_code_data, inputs, **kwargs) -> CodeResultData:
        if self.answer is not None:
            answered = self.answer(python_code_data, inputs)
            if answered is not None:
                return answered
        return run_generated_code(
            python_code_data.code,
            python_code_data.entrypoint,
            inputs,
            extra_python_path=self.extra_python_path,
            extra_environment=self.extra_environment,
        )
