import json
from typing import Any

from langgraph.types import StreamWriter
from loguru import logger
from services.graph.exceptions import ReturnCodeError
from services.graph.nodes.python_node import PythonNode

# The keys of the result the generated code returns when it fails. A success returns one key
# per node input, which is a Python identifier, so a dotted key can never be one of them.
FAILURE_KEYS = frozenset({"node.failure", "node.debug"})


class GeneratedCodeNode(PythonNode):
    """A node that runs code crew generates for it, not code the user wrote.

    The generated code reports its own failure by exiting 0 and returning
    `{"node.failure": <fact for the user>, "node.debug": <traceback and library stderr>}`.
    The node logs `node.debug` at ERROR with the session and node, streams only the fact, and
    raises it.
    A non-zero exit (the code never reached its own handler) is read like a Python node's.
    """

    def read_execution_data(
        self, python_code_execution_data: dict, writer: StreamWriter, execution_order: int
    ) -> Any:
        if python_code_execution_data["returncode"] == 0:
            output = json.loads(python_code_execution_data["result_data"])
            if isinstance(output, dict) and output.keys() == FAILURE_KEYS:
                self._report_failure(output, python_code_execution_data, writer, execution_order)
        return super().read_execution_data(python_code_execution_data, writer, execution_order)

    def _report_failure(
        self,
        failure: dict,
        python_code_execution_data: dict,
        writer: StreamWriter,
        execution_order: int,
    ):
        logger.error(
            "{fact}\n{debug} (session_id={session_id}, node_name={node_name})",
            fact=failure["node.failure"],
            debug=failure["node.debug"],
            session_id=self.session_id,
            node_name=self.node_name,
        )
        # Streamed the way a failed run looks, with the fact in place of the raw output.
        self.write_python_message(
            {
                **python_code_execution_data,
                "returncode": 1,
                "stderr": failure["node.failure"],
                "result_data": "null",
            },
            writer,
            execution_order,
        )
        raise ReturnCodeError(failure["node.failure"])
