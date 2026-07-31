import asyncio
import os
import json
import uuid

from orchestrator.hub import Hub
from orchestrator.planner import plan_steps
from orchestrator.core.config import AgentConfig

from orchestrator.supervisor import Supervisor as IfSupervisor
from orchestrator.crew_supervisor import CrewSupervisor

from dotenv import load_dotenv

load_dotenv()


def to_jsonable(obj):
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, list):
        return [to_jsonable(item) for item in obj]
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    return obj


async def amain(full_prompt: str) -> dict:
    config = AgentConfig.from_env()
    errors = config.validate()
    if errors:
        print("Configuration errors:")
        for error in errors:
            print(f"  - {error}")
        return {"error": "Configuration validation failed", "details": errors}

    print("[main] Starting task with config:")
    print(f"  - Model: {config.deepseek_model}")
    print(f"  - Start tool: {config.start_tool}")
    print(f"  - MCP URL: {config.mcp_url}")

    try:
        steps = plan_steps(full_prompt)
        print(f"[planner] Generated {len(steps)} steps")

        session_id = str(uuid.uuid4())
        print(f"[main] Session ID: {session_id[:8]}...")

        hub = Hub(config.mcp_url, timeout=config.mcp_timeout, session_id=session_id)
        await hub.ainit()

        try:
            supervisor_engine = os.getenv("SUPERVISOR_ENGINE", "if").lower()
            if supervisor_engine == "crew":
                supervisor = CrewSupervisor(
                    hub, steps, config, user_context=full_prompt
                )
            else:
                supervisor = IfSupervisor(hub, steps, config, user_context=full_prompt)

            result = await supervisor.run()

            print(
                f"[main] Execution completed: {result['done']}/{result['total']} steps"
            )
            return result

        finally:
            await hub.aclose()

    except Exception as e:
        print(f"[main] Fatal error: {e}")
        return {"error": str(e), "total": 0, "done": 0, "results": []}


def run_from_env():
    prompt = os.getenv("AGENT_PROMPT")
    if not prompt:
        print("Error: AGENT_PROMPT environment variable is required")
        return {"error": "No prompt provided"}

    print(f"[main] Task: {prompt[:100]}...")
    return asyncio.run(amain(prompt))


def run_interactive():
    print("=== Agent Interactive Mode ===")
    print("Enter your task (or 'quit' to exit):")

    while True:
        try:
            prompt = input("\n> ").strip()
            if prompt.lower() in ("quit", "exit", "q"):
                break
            if not prompt:
                continue

            print(f"\n[main] Executing: {prompt}")
            result = asyncio.run(amain(prompt))
            print(
                f"\n[result] {json.dumps(to_jsonable(result), ensure_ascii=False, indent=2)}"
            )

        except KeyboardInterrupt:
            print("\n[main] Interrupted by user")
            break
        except Exception as e:
            print(f"\n[main] Error: {e}")


if __name__ == "__main__":
    mode = os.getenv("RUN_MODE", "auto")

    if mode == "interactive":
        run_interactive()
    elif mode == "env":
        result = run_from_env()
        print(json.dumps(to_jsonable(result), ensure_ascii=False, indent=2))
    else:
        if os.getenv("AGENT_PROMPT"):
            result = run_from_env()
            print(json.dumps(to_jsonable(result), ensure_ascii=False, indent=2))
        else:
            try:
                from orchestrator.prompt import PROMPT

                print("Found orchestrator/prompt.py - executing default prompt")
                result = asyncio.run(amain(PROMPT))
                print(json.dumps(to_jsonable(result), ensure_ascii=False, indent=2))
            except ImportError:
                print("No AGENT_PROMPT env var and no orchestrator/prompt.py found")
                print("Starting interactive mode...")
                run_interactive()
            except AttributeError:
                print("orchestrator/prompt.py exists but missing PROMPT variable")
                print("Starting interactive mode...")
                run_interactive()
