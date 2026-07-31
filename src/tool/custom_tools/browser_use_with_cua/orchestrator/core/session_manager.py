from dataclasses import dataclass, field
from typing import Dict, Optional, Any
import asyncio


@dataclass
class SessionState:
    session_id: str
    current_tool: str = "browser"
    browser_ready: bool = False
    browser_started: bool = False
    window_id: Optional[str] = None
    x_class: Optional[str] = None
    fail_streak: int = 0
    desktop_success_streak: int = 0
    attempts_by_step: Dict[int, int] = field(default_factory=dict)
    results: list = field(default_factory=list)

    current_page: Optional[Any] = None

    browser: Optional[Any] = None
    llm: Optional[Any] = None
    agent: Optional[Any] = None
    lock: Optional[asyncio.Lock] = None

    last_url: Optional[str] = None
    last_screenshot_path: Optional[str] = None

    def reset_step_attempts(self, step_idx: int):
        if step_idx in self.attempts_by_step:
            self.attempts_by_step[step_idx] = 0

    def increment_attempts(self, step_idx: int) -> int:
        self.attempts_by_step[step_idx] = self.attempts_by_step.get(step_idx, 0) + 1
        return self.attempts_by_step[step_idx]

    def get_attempts(self, step_idx: int) -> int:
        return self.attempts_by_step.get(step_idx, 0)

    def reset_streaks(self):
        self.fail_streak = 0
        self.desktop_success_streak = 0

    def add_result(self, step_idx: int, tool: str, status: str, note: str = ""):
        self.results.append(
            {
                "step_idx": step_idx,
                "tool": tool,
                "status": status,
                "note": note[:1000],
                "attempts": self.get_attempts(step_idx),
            }
        )

    def remember_page_context(
        self, url: str | None = None, screenshot_path: str | None = None
    ):
        if url is not None:
            setattr(self, "last_url", url)
        if screenshot_path is not None:
            setattr(self, "last_screenshot_path", screenshot_path)


class SessionManager:
    def __init__(self):
        self._sessions: Dict[str, SessionState] = {}

    def get_or_create_session(
        self, session_id: str, start_tool: str = "browser"
    ) -> SessionState:
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionState(
                session_id=session_id, current_tool=start_tool
            )
        return self._sessions[session_id]

    def reset_session(self, session_id: str, start_tool: str = "browser"):
        if session_id in self._sessions:
            old_page = self._sessions[session_id].current_page
            del self._sessions[session_id]
        else:
            old_page = None

        new_session = SessionState(session_id=session_id, current_tool=start_tool)

        if old_page:
            new_session.current_page = old_page

        self._sessions[session_id] = new_session

    def cleanup_session(self, session_id: str):
        if session_id in self._sessions:
            del self._sessions[session_id]

    def has_session(self, session_id: str) -> bool:
        return session_id in self._sessions

    def get_all_sessions(self) -> Dict[str, SessionState]:
        return self._sessions.copy()

    def cleanup_old_sessions(self, max_sessions: int = 100):
        if len(self._sessions) > max_sessions:
            session_ids = list(self._sessions.keys())
            for session_id in session_ids[:-max_sessions]:
                del self._sessions[session_id]


session_manager = SessionManager()
