import os
from typing import Callable

import asyncio

from loguru import logger

from services.redis_service import RedisService


SESSION_STATUS_CHANNEL = os.environ.get(
    "SESSION_STATUS_CHANNEL", "sessions:session_status"
)

# Typed findings channel (EST-3285 5.3): src/shared/tools/report_findings_tool/main.py
# returns a dict carrying this marker key when it successfully reports findings.
# The tool's return value goes to CrewAI as a JSON string (result_data is always
# json.dumps(...) of whatever the sandboxed main() returns), so we recognize it
# here, in the same place the "agent" message is already published, and
# republish the payload as its own GraphSessionMessage(message_type="findings")
# for the frontend to render natively (table/cards) instead of as plain text.
# Keep this key in sync with FINDINGS_MARKER_KEY in report_findings_tool/main.py.
FINDINGS_MARKER_KEY = "__epicstaff_message_type__"
FINDINGS_MESSAGE_TYPE = "findings"

# Upper bound on a plausible report_findings_tool JSON payload, used to skip
# json.loads on the hot path (_maybe_publish_findings_message runs for every
# tool result, every agent, every run). A realistic worst case is ~50 findings
# with ~2000-char "details" each: 50 * 2000 = 100_000 chars, plus per-finding
# JSON overhead (title/severity/file/line keys, quoting, commas) roughly
# doubling that to ~200_000, plus the marker key/envelope. 256_000 (250 KiB)
# is comfortably above that bound while still being cheap to reject anything
# bigger without parsing (a findings payload is bounded by the tool's own
# caps, so a bigger result definitionally isn't findings).
MAX_FINDINGS_RESULT_BYTES = 256_000


class GraphSessionCallbackFactory:
    def __init__(
        self, session_id: int, redis_service: RedisService, crewai_output_channel: str
    ):
        self.crewai_output_channel = crewai_output_channel
        self.session_id = session_id
        self.redis_service = redis_service

    def get_done_callback(self) -> Callable[[asyncio.Task], None]:
        """
        Callback to handle the completion of a session task.
        """

        def inner(task: asyncio.Task) -> None:
            try:
                if task.cancelled():
                    logger.warning(f"Session {self.session_id} was cancelled.")
                    self.redis_service.publish(
                        SESSION_STATUS_CHANNEL,
                        {"session_id": self.session_id, "status": "cancelled"},
                    )
                elif task.exception():
                    # Here we go again....
                    exc = task.exception()
                    logger.error(
                        f"Session {self.session_id} task completed with exception"
                    )

                    self.redis_service.publish(
                        SESSION_STATUS_CHANNEL,
                        {
                            "session_id": self.session_id,
                            "status": "error",
                            "error": str(exc),
                        },
                    )
                    raise exc
                else:
                    logger.info(f"Session {self.session_id} finished successfully.")
                    finish_state: dict = task.result()

                    assert isinstance(finish_state, dict)
                    state_history: list = finish_state["state_history"]

                    last_state = state_history[-1]

                    self.redis_service.publish(
                        SESSION_STATUS_CHANNEL,
                        {
                            "session_id": self.session_id,
                            "status": "end",
                            "status_data": {
                                "state_history": state_history,
                                "output": last_state["output"],
                            },
                        },
                    )
            except Exception as e:
                logger.exception(
                    f"Error in done callback for session {self.session_id}: {e}"
                )

        return inner
