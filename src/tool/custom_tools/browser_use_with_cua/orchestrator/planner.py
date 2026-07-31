from typing import List, Dict, Any
from openai import OpenAI
from dotenv import load_dotenv
import json
from orchestrator.core.config import AgentConfig

load_dotenv()

CONFIG = AgentConfig.from_env()

client = OpenAI(api_key=CONFIG.openai_api_key)

ORCHESTRATOR_SYSTEM_PROMPT = """
You are a Web & Desktop Task Orchestrator. Your task will be completed when you will complete all steps. Break the user's goal into small, safe, deterministic steps.
Return pure JSON with an array named "steps". Each step object MUST include:
- action: one of ["navigate","type","click","submit","wait"]
- target: concise description
- hints: array of nearby labels/sections
- text: string (for type/navigate), else omit or empty
- target_kind: one of {"icon","button","link","input","menu","unknown"}
- risk: one of {"low","med","high"}

RULES:
-If the site redirects (e.g., to a login route), it's still a success. 
-Always include a line "CURRENT_URL: <final_url>" before PASSED/FAILED.
- No commentary; return only valid JSON.
""".strip()


def plan_steps(user_prompt: str) -> List[Dict[str, Any]]:
    if not CONFIG.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required for planning")

    print(f"[planner] Using model: {CONFIG.planner_model}")
    print(f"[planner] Planning task: {user_prompt[:200]}...")

    try:
        resp = client.chat.completions.create(
            model=CONFIG.planner_model,
            temperature=0.0,
            messages=[
                {"role": "system", "content": ORCHESTRATOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
        )

        data = resp.choices[0].message.content
        plan = json.loads(data)

        steps = plan.get("steps")
        if not isinstance(steps, list) or len(steps) == 0:
            raise RuntimeError(f"Planner returned no steps: {plan}")

        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                raise RuntimeError(f"Step {i+1} is not a dictionary: {step}")

            required_fields = ["action", "target"]
            for field in required_fields:
                if field not in step:
                    raise RuntimeError(
                        f"Step {i+1} missing required field '{field}': {step}"
                    )

        print(f"[planner] Generated {len(steps)} steps successfully")

        for i, step in enumerate(steps[:3], 1):
            action = step.get("action", "?")
            target = step.get("target", "?")
            print(f"  {i}. {action}: {target}")

        if len(steps) > 3:
            print(f"  ... and {len(steps) - 3} more steps")

        return steps

    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse planner response as JSON: {e}")
    except Exception as e:
        raise RuntimeError(f"Planning failed: {e}")
