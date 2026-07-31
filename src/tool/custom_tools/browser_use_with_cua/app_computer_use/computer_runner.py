import os
import asyncio
from typing import Any, Dict, Optional

from app_computer_use.test_computer_use import main as run_steps


def _apply_context_env(params: Dict[str, Any]) -> Dict[str, Any]:
    ctx_in: Dict[str, Any] = params.get("context", {}) if params else {}
    window_id: Optional[str] = (
        str(params.get("window_id"))
        if params.get("window_id") is not None
        else (
            str(ctx_in.get("window_id"))
            if ctx_in.get("window_id") is not None
            else None
        )
    )
    last_url: Optional[str] = params.get("last_url") or ctx_in.get("last_url")
    screenshot: Optional[str] = params.get("screenshot") or ctx_in.get("screenshot")
    step_idx: Optional[int] = params.get("step_idx") or ctx_in.get("step_idx")
    display: Optional[str] = params.get("display") or ctx_in.get("display")

    if window_id:
        os.environ["BROWSER_WINDOW_ID"] = str(window_id)
    if last_url:
        os.environ["ORCH_LAST_URL"] = str(last_url)
    if screenshot:
        os.environ["ORCH_LAST_SCREENSHOT"] = str(screenshot)
    if display:
        os.environ["DISPLAY"] = str(display)

    os.environ["ORCHESTRATOR_COMPUTER_PROMPT"] = "1"

    return {
        "window_id": window_id,
        "last_url": last_url,
        "screenshot": screenshot,
        "step_idx": step_idx,
        "display": display,
    }


async def run_computer_task(
    prompt: str,
    env: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    params = params or {}

    if env:
        os.environ["COMPUTER_ENV"] = env

    norm_ctx = _apply_context_env(params)

    loop = asyncio.get_running_loop()
    state = await loop.run_in_executor(None, run_steps, prompt)

    return {
        "output": state,
        "status": "ok",
        "env": os.getenv("COMPUTER_ENV", env or "local"),
        "context_used": norm_ctx,
    }
