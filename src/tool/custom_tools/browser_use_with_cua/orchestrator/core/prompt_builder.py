from typing import Dict, Any

SYSTEM_PROMPTS = {
    "browser": """You are a browser automation agent.

RULES:
- Always refer to elements by their zero-based index.
- If an index is provided, you MUST use it. Do not guess selectors.
- Prefer index-based actions (click_by_index, type_by_index, focus_by_index).
- Use extract_structured_data whenever you need a reliable, up-to-date list of elements on the page (roles, labels, hrefs, and their indices). Typically call it:
  • right after a major navigation or redirect (e.g., to a login page),
  • before choosing elements by index on a new/changed screen,
  • when the DOM looks empty/changed or previous indices no longer match.
- If the page redirects (e.g., to login), treat navigation as successful and proceed with next steps.
- Finish EVERY step with exactly one of: PASSED / FAILED / REWIND.""",
    "computer": """You are automation agent that uses screenshots to get best result.

RULES:
- If BROWSER_WINDOW_ID is provided (via env/params), activate that window first and keep focus there.
- Finish EVERY step with exactly one of: PASSED / FAILED / REWIND.""",
}


class PromptBuilder:
    @staticmethod
    def build_plan_prompt(plan: Dict[str, Any], tool: str) -> str:
        system_prompt = SYSTEM_PROMPTS.get(tool, SYSTEM_PROMPTS["browser"])
        steps = plan.get("steps", [])
        total = len(steps)

        lines = []
        for i, step in enumerate(steps, 1):
            action = step.get("action", "")
            target = step.get("target", "")
            idx = step.get("index")
            text = step.get("text", "")

            instr = f"{i}/{total}. {action} {target}"
            hints = []
            if idx is not None:
                hints.append(f"index: {idx}")
            if text:
                hints.append(f"text: {text}")
            if hints:
                instr += f" ({', '.join(hints)})"

            lines.append(instr)

        steps_block = "\n".join(lines)
        return f"""{system_prompt}

Your task is to execute the following plan step by step:
{steps_block}

- Always use index-based actions.
- Use extract_structured_data on new pages or when indices might have changed.
- Do not guess selectors.
- Continue until ALL steps are complete."""

    @staticmethod
    def build_step_prompt(
        step: Dict[str, Any], plan: Dict[str, Any], step_idx: int, tool: str
    ) -> str:
        system_prompt = SYSTEM_PROMPTS.get(tool, SYSTEM_PROMPTS["browser"])
        action = step.get("action", "")
        target = step.get("target", "")
        text = step.get("text", "")
        instr = f"{step_idx}. {action} {target}"
        if text:
            instr += f" (text: {text})"
        return f"""{system_prompt}

STEP {step_idx}: {instr}"""
