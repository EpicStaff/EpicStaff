from dataclasses import dataclass
from typing import Optional
import os
from dotenv import load_dotenv

load_dotenv()


@dataclass
class AgentConfig:
    escalate_threshold: int = 4
    deescalate_after: int = 2
    max_attempts_per_step: int = 6

    switch_to_computer_after_step: Optional[int] = None

    prefer_backend: str = "browser"
    start_tool: str = "browser"

    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"
    deepseek_base_url: str = ""
    deepseek_temperature: float = 0.0
    openai_api_key: str = ""
    planner_model: str = "gpt-4o-mini"

    mcp_url: str = "http://127.0.0.1:8080/mcp"
    mcp_timeout: float = 600.0
    browser_step_timeout: float = 60.0

    display: str = ":99"
    vnc_geometry: str = "1600x900"
    playwright_headless: str = "0"
    start_url: str = "about:blank"

    runs_dir: str = "./runs"

    @classmethod
    def from_env(cls) -> "AgentConfig":

        switch_env = os.getenv("ORCH_SWITCH_TO_COMPUTER_AFTER_STEP", "").strip()
        switch_to_computer_after_step = (
            int(switch_env) if switch_env.isdigit() else None
        )

        return cls(
            escalate_threshold=int(os.getenv("ESCALATE_THRESHOLD", "4")),
            deescalate_after=int(os.getenv("DEESCALATE_AFTER", "2")),
            max_attempts_per_step=int(os.getenv("MAX_ATTEMPTS_PER_STEP", "6")),
            prefer_backend=os.getenv("PREFER_BACKEND", "browser"),
            start_tool=os.getenv("START_TOOL", "browser"),
            switch_to_computer_after_step=switch_to_computer_after_step,
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", ""),
            deepseek_temperature=float(os.getenv("DEEPSEEK_TEMPERATURE", "0.0")),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            planner_model=os.getenv("PLANNER_MODEL", "gpt-4o-mini"),
            mcp_url=os.getenv("MCP_URL", "http://127.0.0.1:8080/mcp"),
            display=os.getenv("DISPLAY", ":99"),
            vnc_geometry=os.getenv("VNC_GEOMETRY", "1600x900"),
            playwright_headless=os.getenv("PLAYWRIGHT_HEADLESS", "0"),
            start_url=os.getenv("START_URL", "about:blank"),
            runs_dir=os.getenv("RUNS_DIR", "./runs"),
        )

    def validate(self) -> list[str]:
        errors = []
        if not self.deepseek_api_key:
            errors.append("DEEPSEEK_API_KEY is required")
        if not self.openai_api_key:
            errors.append("OPENAI_API_KEY is required")
        return errors
