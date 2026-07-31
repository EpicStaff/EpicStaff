import re
import json
from typing import Tuple, Dict, Any


class AgentError(Exception):
    def __init__(
        self, message: str, step_idx: int, tool: str, recoverable: bool = True
    ):
        self.message = message
        self.step_idx = step_idx
        self.tool = tool
        self.recoverable = recoverable
        super().__init__(message)


class ErrorHandler:
    @staticmethod
    def parse_status(text: str) -> Tuple[bool, str]:

        if not text:
            return False, "FAILED"

        matches = re.findall(r"(?mi)^\s*(PASSED|FAILED|REWIND)\s*$", text)
        if matches:
            status = matches[-1].upper()
            return (status == "PASSED"), status

        matches2 = re.findall(r"(?i)\b(PASSED|FAILED|REWIND)\b", text)
        if matches2:
            status = matches2[-1].upper()
            return (status == "PASSED"), status

        return False, "FAILED"

    @staticmethod
    def handle_step_error(error: Exception, step_idx: int, tool: str) -> Dict[str, Any]:

        error_msg = str(error)

        if "Expected at least one handler to return a non-None result" in error_msg:
            return {
                "status": "REWIND",
                "recoverable": True,
                "note": f"{error_msg}\n[hint] State handlers missing — rewinding to re-establish context.",
            }

        if any(
            word in error_msg.lower() for word in ["timeout", "time out", "timed out"]
        ):
            return {
                "status": "FAILED",
                "recoverable": True,
                "note": f"Timeout error in {tool}: {error_msg}",
            }

        if any(word in error_msg.lower() for word in ["connection", "network", "dns"]):
            return {
                "status": "FAILED",
                "recoverable": True,
                "note": f"Network error in {tool}: {error_msg}",
            }

        if any(word in error_msg.lower() for word in ["playwright", "browser", "page"]):
            return {
                "status": "FAILED",
                "recoverable": True,
                "note": f"Browser error in {tool}: {error_msg}",
            }

        return {
            "status": "FAILED",
            "recoverable": False,
            "note": f"{tool} exception: {error_msg}",
        }

    @staticmethod
    def extract_output_strings(obj) -> str:
        def _collect_strings(obj):
            if obj is None:
                return []
            if isinstance(obj, str):
                return [obj]
            if isinstance(obj, dict):
                out = []
                for key in (
                    "final",
                    "status_text",
                    "output",
                    "text",
                    "message",
                    "content",
                    "result",
                ):
                    if key in obj and isinstance(obj[key], str):
                        out.append(obj[key])
                for value in obj.values():
                    out.extend(_collect_strings(value))
                return out
            if isinstance(obj, (list, tuple)):
                out = []
                for item in obj:
                    out.extend(_collect_strings(item))
                return out
            return [str(obj)]

        parts = _collect_strings(obj)
        raw = "\n".join(p for p in parts if p is not None)

        if not raw:
            try:
                raw = json.dumps(obj, ensure_ascii=False)
            except Exception:
                raw = str(obj)

        unescaped = (
            raw.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", "\t")
        )
        return unescaped.strip()

    @staticmethod
    def is_critical_error(error_msg: str) -> bool:
        critical_patterns = [
            "out of memory",
            "disk full",
            "permission denied",
            "authentication failed",
            "api key",
            "quota exceeded",
            "rate limit exceeded",
        ]

        error_lower = error_msg.lower()
        return any(pattern in error_lower for pattern in critical_patterns)

    @staticmethod
    def should_escalate_tool(error_msg: str, current_tool: str) -> bool:
        if current_tool == "browser":
            browser_escalation_patterns = [
                "element not found",
                "selector not found",
                "timeout waiting for",
                "element is not visible",
                "element is not clickable",
            ]
            error_lower = error_msg.lower()
            return any(
                pattern in error_lower for pattern in browser_escalation_patterns
            )

        return False
