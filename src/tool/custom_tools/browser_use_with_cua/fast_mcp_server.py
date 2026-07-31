import os
import json
import time
import subprocess
from fastmcp import FastMCP
from app_browser_use.browser_runner import (
    run_browser_task,
    clear_sessions,
    reset_browser_session,
)

mcp = FastMCP("Browser Use Agent")

SESSIONS_DIR = "sessions"
os.makedirs(SESSIONS_DIR, exist_ok=True)


@mcp.tool
async def restart_browser_use() -> dict:
    script_path = "/app/restart.sh"

    try:
        clear_sessions()
        reset_browser_session()

        result = subprocess.run(
            ["bash", script_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            text=True,
        )

        time.sleep(10)

        return {
            "status": "success" if result.returncode == 0 else "error",
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }

    except Exception as ex:
        return {"status": "failed", "error": str(ex)}


@mcp.tool
async def run_browser_use(
    prompt: str, next_prompt: str | None = None, session_id: str | None = None
) -> dict:
    if not session_id:
        session_id = os.urandom(4).hex()

    session_file = os.path.join(SESSIONS_DIR, f"{session_id}.json")

    session_data = {}
    if os.path.exists(session_file):
        with open(session_file, "r", encoding="utf-8") as f:
            session_data = json.load(f)

    session_data.setdefault("history", []).append(prompt)
    if next_prompt:
        session_data["history"].append(next_prompt)

    with open(session_file, "w", encoding="utf-8") as f:
        json.dump(session_data, f, ensure_ascii=False, indent=2)

    result = await run_browser_task(prompt, next_prompt)

    result["session_id"] = session_id
    return result


if __name__ == "__main__":
    print("[server] Starting simple MCP server")
    mcp.run("streamable-http", host="0.0.0.0", port=8080)


# import os
# from typing import Optional
# from fastmcp import FastMCP
# from app_browser_use.browser_runner import run_browser_task
# from app_computer_use.computer_runner import run_computer_task
# from orchestrator.core.session_manager import session_manager
# from orchestrator.core.prompt_builder import PromptBuilder
# from orchestrator.core.error_handler import ErrorHandler
# from orchestrator.core.config import AgentConfig

# CONFIG = AgentConfig.from_env()
# mcp = FastMCP("custom_tools MCP Server")


# @mcp.tool(description="Browser tool")
# async def run_browser(
#     prompt: str,
#     model: str = "deepseek-chat",
#     session_id: str = "default",
#     reset: bool = False,
# ):
#     if not CONFIG.deepseek_api_key:
#         return {"ok": False, "error": "DEEPSEEK_API_KEY not set"}
#     try:
#         result = await run_browser_task(prompt, model, None, session_id, reset, None)
#         return {"ok": True, "output": result.get("output")}
#     except Exception as e:
#         return {"ok": False, "error": str(e)}


# if __name__ == "__main__":
#     print(f"[server] Starting simple MCP server")
#     mcp.run("streamable-http", host="0.0.0.0", port=8080)

# async def _execute_browser_step(
#     session_id: str,
#     prompt: str,
#     model: str,
#     temperature: float,
#     reset: bool,
#     session,
#     step_idx: int,
# ):
#     if not CONFIG.deepseek_api_key:
#         return {
#             "ok": False,
#             "status": "FAILED",
#             "note": "DEEPSEEK_API_KEY not set",
#             "tool_used": "browser",
#         }
#     try:
#         result = await run_browser_task(
#             prompt, model, temperature, session_id, reset, step_idx
#         )
#         out_text = ErrorHandler.extract_output_strings(result.get("output", "")).strip()
#         ok, status = ErrorHandler.parse_status(out_text)
#         if ok:
#             session.browser_ready = True
#         return {
#             "ok": status == "PASSED",
#             "status": status,
#             "note": out_text,
#             "tool_used": "browser",
#         }
#     except Exception as e:
#         error_info = ErrorHandler.handle_step_error(e, step_idx, "browser")
#         return {
#             "ok": False,
#             "status": error_info["status"],
#             "note": error_info["note"],
#             "tool_used": "browser",
#         }


# async def _execute_computer_step(session_id: str, prompt: str, session, step_idx: int):
#     try:
#         window_id = getattr(session, "window_id", None)
#         last_url = getattr(session, "last_url", None)
#         screenshot_path = getattr(session, "last_screenshot_path", None)

#         if window_id:
#             os.environ["BROWSER_WINDOW_ID"] = str(window_id)
#         if CONFIG.display and not os.environ.get("DISPLAY"):
#             os.environ["DISPLAY"] = CONFIG.display

#         params = {
#             "window_id": window_id,
#             "context": {
#                 "handoff_from": "browser",
#                 "session_id": session_id,
#                 "step_idx": step_idx,
#                 "last_url": last_url,
#                 "screenshot": screenshot_path,
#             },
#         }

#         cresult = await run_computer_task(prompt, env="local", params=params)

#         out_text = ErrorHandler.extract_output_strings(
#             (cresult or {}).get("output", "")
#         ).strip()
#         ok, status = ErrorHandler.parse_status(out_text)

#         return {
#             "ok": (status == "PASSED"),
#             "status": status,
#             "note": out_text,
#             "tool_used": "computer",
#         }

#     except Exception as e:
#         error_info = ErrorHandler.handle_step_error(e, step_idx, "computer")
#         return {
#             "ok": False,
#             "status": error_info["status"],
#             "note": error_info["note"],
#             "tool_used": "computer",
#         }


# @mcp.tool(description="Execute one plan step")
# async def run_step(
#     session_id: str,
#     step_idx: int,
#     tool: str,
#     step: dict,
#     plan: dict,
#     reset: bool = False,
#     model: str = "deepseek-chat",
#     temperature: float = 0.0,
#     start_tool: Optional[str] = None,
# ):

#     print(f"[server] Step {step_idx}: {tool}")
#     if reset:
#         session_manager.reset_session(session_id, start_tool or "browser")

#     session = session_manager.get_or_create_session(session_id, start_tool or "browser")
#     chosen = "computer" if tool.lower() == "computer" else "browser"
#     session.current_tool = chosen

#     if chosen == "browser":
#         prompt = PromptBuilder.build_step_prompt(
#             step=step, plan=plan, step_idx=step_idx, tool=chosen
#         )
#         return await _execute_browser_step(
#             session_id, prompt, model, temperature, reset, session, step_idx
#         )
#     else:
#         prompt = PromptBuilder.build_step_prompt(
#             step=step, plan=plan, step_idx=step_idx, tool=chosen
#         )
#         return await _execute_computer_step(session_id, prompt, session, step_idx)


# @mcp.tool(description="Computer tool")
# async def run_computer(prompt: str, env: str = "docker", params: dict = None):
#     try:
#         result = await run_computer_task(prompt, env, params or {})
#         return {"ok": True, "output": result}
#     except Exception as e:
#         return {"ok": False, "error": str(e)}


# if __name__ == "__main__":
#     print(f"[server] Starting simple MCP server")
#     mcp.run("streamable-http", host="0.0.0.0", port=8080)
