import asyncio
import os
import uuid
import json
from browser_use import Agent, Tools, BrowserProfile, Browser
from browser_use.llm import ChatOpenAI


SESSION_DIR = "sessions"
os.makedirs(SESSION_DIR, exist_ok=True)


tools = Tools()


SPEED_OPTIMIZATION_PROMPT = """
You are a browser task executor. All outputs must follow the strict JSON format for AgentOutput:
- Always include "action": one of ["go_to_url", "click", "type", "wait", "done"]
- Use "target": {...} object for any action parameters
- Do NOT include keys like "url" or "new_tab" directly at the root level
- Example for go_to_url: {"action": "go_to_url", "target": {"url": "https://example.com"}}
- Final step must be: {"action": "done", "text": "..."}
"""


deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
if deepseek_api_key is None:
    print("Error: missing DEEPSEEK_API_KEY")
    exit(1)


browser = Browser(keep_alive=True)


llm = ChatOpenAI(
    model="o3",
)

# llm = ChatDeepSeek(
# base_url='https://api.deepseek.com/v1',
# model='deepseek-chat',
# api_key=deepseek_api_key,
# )


browser_profile = BrowserProfile(
    minimum_wait_page_load_time=0.1,
    wait_between_actions=0.1,
    headless=False,
    keep_alive=True,
)


sessions = {}


def clear_sessions():
    print("Clearing sessions before restart")
    sessions.clear()


def reset_browser_session():
    global browser
    print("Resetting browser session")
    browser = Browser(keep_alive=True)


def load_or_create_session(session_id: str, prompt: str) -> Agent:
    if session_id in sessions:
        return sessions[session_id]

    agent = Agent(
        task=prompt,
        llm=llm,
        use_vision=True,
        tools=tools,
        flash_mode=True,
        extend_system_message=SPEED_OPTIMIZATION_PROMPT,
        browser_profile=browser_profile,
        browser_session=browser,
    )

    sessions[session_id] = agent
    return agent


async def run_browser_task(
    prompt: str, next_prompt: str | None = None, session_id: str | None = None
) -> dict:
    session_id = session_id or str(uuid.uuid4())
    session_path = os.path.join(SESSION_DIR, f"{session_id}.json")

    history = []
    if os.path.exists(session_path):
        with open(session_path, "r", encoding="utf-8") as f:
            history = json.load(f).get("history", [])

    current_prompt = next_prompt or prompt

    agent = Agent(
        task=current_prompt,
        llm=llm,
        use_vision=False,
        tools=tools,
        flash_mode=True,
        extend_system_message=SPEED_OPTIMIZATION_PROMPT,
        browser_profile=browser_profile,
        browser_session=browser,
    )

    await agent.run()

    history.append({"prompt": current_prompt})

    with open(session_path, "w", encoding="utf-8") as f:
        json.dump(
            {"session_id": session_id, "history": history},
            f,
            ensure_ascii=False,
            indent=2,
        )

    return {
        "status": "done",
        "session_id": session_id,
        "last_prompt": current_prompt,
        "history": history,
    }


if __name__ == "__main__":
    asyncio.run(
        run_browser_task("What are the latest changes in AI regulations in the EU?")
    )


# from browser_use import Browser, Agent
# from browser_use.llm import ChatDeepSeek
# from orchestrator.core.config import AgentConfig
# import asyncio, os, subprocess
# from orchestrator.core.session_manager import session_manager
# from typing import Optional

# CONFIG = AgentConfig.from_env()


# async def _detect_window_id(x_class: Optional[str] = None) -> Optional[str]:
#     try:
#         if x_class:
#             out = (
#                 subprocess.check_output(
#                     ["xdotool", "search", "--onlyvisible", "--class", x_class]
#                 )
#                 .decode()
#                 .strip()
#             )
#         else:
#             for klass in ("chromium", "chrome", "firefox"):
#                 try:
#                     out = (
#                         subprocess.check_output(
#                             ["xdotool", "search", "--onlyvisible", "--class", klass]
#                         )
#                         .decode()
#                         .strip()
#                     )
#                     if out:
#                         return out.splitlines()[-1].strip()
#                 except Exception:
#                     continue
#             return None
#         if not out:
#             return None
#         return out.splitlines()[-1].strip()
#     except Exception:
#         return None


# async def run_browser_task(
#     prompt: str,
#     model: str | None = None,
#     temperature: float | None = None,
#     session_id: str = "default",
#     reset: bool = False,
#     step_number: int | None = None,
# ):
#     if reset:
#         session_manager.reset_session(session_id, start_tool="browser")
#     state = session_manager.get_or_create_session(session_id, start_tool="browser")

#     if state.browser is None:
#         os.environ["PLAYWRIGHT_HEADLESS"] = os.getenv("PLAYWRIGHT_HEADLESS", "0")
#         os.environ["DISPLAY"] = os.getenv("DISPLAY", CONFIG.display or ":99")
#         state.browser = Browser(headless=False)
#         state.browser_started = True
#         state.browser_ready = True

#         if not state.window_id:
#             state.window_id = await _detect_window_id(state.x_class)

#     if state.llm is None:
#         state.llm = ChatDeepSeek(
#             api_key=CONFIG.deepseek_api_key,
#             model=model or CONFIG.deepseek_model,
#             base_url=CONFIG.deepseek_base_url,
#             temperature=(
#                 CONFIG.deepseek_temperature if temperature is None else temperature
#             ),
#         )
#     else:
#         if model:
#             state.llm.model = model
#         if temperature is not None:
#             state.llm.temperature = temperature

#     if state.agent is None:
#         state.agent = Agent(
#             task=prompt or "Ready", browser=state.browser, llm=state.llm
#         )

#     if state.lock is None:
#         state.lock = asyncio.Lock()

#     if step_number == 1 and prompt:
#         state.agent.task = prompt

#     async with state.lock:
#         try:
#             result = await state.agent.run()
#         except Exception as e:
#             if "QueueShutDown" in str(e):
#                 state.agent = Agent(
#                     task=state.agent.task, browser=state.browser, llm=state.llm
#                 )
#                 result = await state.agent.run()
#             else:
#                 raise

#     try:
#         page = getattr(state.browser, "page", None) or state.current_page
#         url = None
#         if page and hasattr(page, "url"):
#             url = page.url
#         state.remember_page_context(url=url)

#         if page and hasattr(page, "screenshot"):
#             path = "/mnt/data/last_browser_page.png"
#             try:
#                 img = page.screenshot(path=path)
#                 state.remember_page_context(screenshot_path=path)
#             except TypeError:
#                 img = await page.screenshot(path=path)
#                 state.remember_page_context(screenshot_path=path)
#     except Exception:
#         pass

#     if not state.window_id:
#         state.window_id = await _detect_window_id(state.x_class)

#     state.add_result(step_number or 0, "browser", "DONE", note=str(result)[:500])
#     return {"output": result, "step_number": step_number}


# def get_browser_state_for_computer(session_id: str):
#     state = session_manager.get_or_create_session(session_id)
#     return {
#         "browser_ready": bool(state and state.browser),
#         "agent_ready": bool(state and state.agent),
#     }


# async def cleanup_browser_session(session_id: str):
#     state = session_manager.get_or_create_session(session_id)
#     try:
#         if state and state.browser:
#             try:
#                 state.browser.close()
#             except Exception:
#                 pass
#     finally:
#         session_manager.cleanup_session(session_id)
