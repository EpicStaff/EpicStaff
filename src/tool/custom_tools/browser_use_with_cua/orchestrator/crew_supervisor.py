from __future__ import annotations
from typing import Any, Dict, List, Optional
import json
import time

from crewai import Agent, Crew, Task
from pydantic import BaseModel, Field

from orchestrator.hub import Hub
from orchestrator.core.config import AgentConfig
from orchestrator.core.session_manager import session_manager
from orchestrator.core.error_handler import ErrorHandler


def default_choose_tool(
    step: Dict[str, Any], current_tool: str, fail_streak: int, cfg: AgentConfig
) -> str:
    action = step.get("action", "")
    target_kind = step.get("target_kind", "unknown")
    target = (step.get("target") or "").lower()

    if action == "type" and "password" in target:
        return "computer"
    if "login" in target and action in ("assert", "click"):
        return "computer"
    if fail_streak >= cfg.escalate_threshold:
        return "computer"
    if action == "click" and target_kind in ("icon", "menu"):
        return "computer"
    return current_tool or "browser"


class StepToolResult(BaseModel):
    ok: bool = Field(default=False)
    status: str = Field(default="FAILED")
    note: str = Field(default="")
    tool_used: str = Field(default="browser")


class BaseStepTool:
    """Base tool: delegates step execution to MCP via Hub."""

    def __init__(self, hub: Hub, cfg: AgentConfig, tool_name: str):
        self.hub = hub
        self.cfg = cfg
        self.tool_name = tool_name

    async def __call__(
        self, *, step_idx: int, step: dict, plan_ctx: dict, start_tool: Optional[str]
    ) -> StepToolResult:
        res = await self.hub.run_step(
            step_idx=step_idx,
            step=step,
            plan_ctx=plan_ctx,
            tool=self.tool_name,
            reset=False,
            model=self.cfg.deepseek_model,
            temperature=self.cfg.deepseek_temperature,
            start_tool=start_tool,
        )
        data = (
            getattr(res, "structured_content", None) or getattr(res, "data", {}) or {}
        )
        return StepToolResult(
            ok=(data.get("status") == "PASSED"),
            status=data.get("status", "FAILED"),
            note=data.get("note", ""),
            tool_used=data.get("tool_used", self.tool_name),
        )


class BrowserStepTool(BaseStepTool):
    def __init__(self, hub: Hub, cfg: AgentConfig):
        super().__init__(hub, cfg, "browser")


class ComputerStepTool(BaseStepTool):
    def __init__(self, hub: Hub, cfg: AgentConfig):
        super().__init__(hub, cfg, "computer")


class CrewSupervisor:
    def __init__(
        self,
        hub: Hub,
        steps: List[Dict[str, Any]],
        config: AgentConfig,
        user_context: str = "",
    ):
        self.hub = hub
        self.steps = steps
        self.config = config
        self.user_context = user_context
        self.session = session_manager.get_or_create_session(
            hub.session_id, config.start_tool
        )

        self.browser_tool = BrowserStepTool(hub, config)
        self.computer_tool = ComputerStepTool(hub, config)

        self.supervisor_agent = Agent(
            role="Supervisor",
            goal="Select the right tool (browser or computer) for each step and ensure PASSED/REWIND/FAILED discipline.",
            backstory=(
                "You orchestrate a web task. Each step must end with PASSED/FAILED/REWIND. "
                "Prefer browser for safe/low-risk DOM actions, choose computer when UI elements are icons/menus, "
                "password fields, tricky clicks, or after multiple failures."
            ),
            allow_delegation=False,
            verbose=True,
        )

        print(
            f"[supervisor] Initialized (Crew) with {len(steps)} steps, session {hub.session_id[:8]}"
        )

    async def run(self) -> Dict[str, Any]:
        total = len(self.steps)
        current_step = 1

        first_attempt = True

        while 1 <= current_step <= total:
            step = self.steps[current_step - 1]
            attempts = self.session.increment_attempts(current_step)

            start_tool = None
            reset = False
            if first_attempt:
                chosen_start = self.config.start_tool or "browser"
                start_tool = chosen_start
                reset = True
                first_attempt = False

            plan_ctx = {
                "total_steps": total,
                "user_prompt": self.user_context,
                "steps": self.steps,
            }

            decision_prompt = (
                f"STEP {current_step}/{total}\n"
                f"JSON step:\n{json.dumps(step, ensure_ascii=False)}\n\n"
                f"Current tool: {self.session.current_tool}\n"
                f"Fail streak: {self.session.fail_streak}\n"
                f"Rules:\n"
                f"- If password typing or login assert/click → prefer computer.\n"
                f"- If fail_streak >= {self.config.escalate_threshold} → computer.\n"
                f"- If click on icon/menu → computer.\n"
                f"- Else keep current tool.\n"
                f"Return one word exactly: 'browser' or 'computer'."
            )

            crew = Crew(
                agents=[self.supervisor_agent],
                tasks=[
                    Task(
                        description=decision_prompt,
                        expected_output="One token: browser or computer",
                        agent=self.supervisor_agent,
                    )
                ],
                verbose=False,
            )

            decision_obj = crew.kickoff()

            tool_choice_raw = ""
            try:
                if hasattr(decision_obj, "raw") and decision_obj.raw:
                    tool_choice_raw = str(decision_obj.raw)
                elif (
                    hasattr(decision_obj, "final_output") and decision_obj.final_output
                ):
                    tool_choice_raw = str(decision_obj.final_output)
                else:
                    tool_choice_raw = str(decision_obj)
            except Exception:
                tool_choice_raw = str(decision_obj)

            tool_choice_raw = (tool_choice_raw or "").strip().lower()
            tool_choice = "browser" if "browser" in tool_choice_raw else "computer"

            tool_choice = default_choose_tool(
                step,
                tool_choice or self.session.current_tool,
                self.session.fail_streak,
                self.config,
            )
            self.session.current_tool = tool_choice

            print(
                f"[supervisor] (Crew) step={current_step}/{total} attempt={attempts} tool={tool_choice} "
                f"fail_streak={self.session.fail_streak} desktop_ok_streak={self.session.desktop_success_streak}"
            )

            try:
                if tool_choice == "computer":
                    tool_res = await self.computer_tool(
                        step_idx=current_step,
                        step=step,
                        plan_ctx=plan_ctx,
                        start_tool=start_tool if reset else None,
                    )
                else:
                    tool_res = await self.browser_tool(
                        step_idx=current_step,
                        step=step,
                        plan_ctx=plan_ctx,
                        start_tool=start_tool if reset else None,
                    )

                status = (tool_res.status or "").upper()
                note = tool_res.note or ""
                tool_used = tool_res.tool_used or tool_choice

                print(
                    f"[supervisor] -> status={status} tool_used={tool_used} note_length={len(note)}"
                )

                self.session.add_result(current_step, tool_used, status, note)

                if status == "PASSED":
                    self.session.fail_streak = 0
                    if tool_used == "computer":
                        self.session.desktop_success_streak += 1
                        if (
                            self.session.desktop_success_streak
                            >= self.config.deescalate_after
                        ):
                            print(
                                f"[supervisor] (Crew) Deescalating to browser after {self.session.desktop_success_streak} desktop successes"
                            )
                            self.session.current_tool = "browser"
                            self.session.desktop_success_streak = 0
                    else:
                        self.session.desktop_success_streak = 0
                        self.session.current_tool = "browser"

                    current_step += 1
                    continue

                if status == "REWIND":
                    self.session.fail_streak += 1
                    if self.session.fail_streak >= self.config.escalate_threshold:
                        if self.session.current_tool != "computer":
                            print(
                                f"[supervisor] (Crew) Escalating to computer after rewind (fail_streak={self.session.fail_streak})"
                            )
                        self.session.current_tool = "computer"
                    current_step = max(1, current_step - 1)
                    self.session.reset_step_attempts(current_step)
                    time.sleep(0.2)
                    continue
                self.session.fail_streak += 1
                if attempts < self.config.max_attempts_per_step:
                    if self.session.fail_streak >= self.config.escalate_threshold:
                        if self.session.current_tool != "computer":
                            print(
                                f"[supervisor] (Crew) Escalating to computer after {self.session.fail_streak} failures"
                            )
                        self.session.current_tool = "computer"
                    time.sleep(0.2)
                    continue

                print(
                    f"[supervisor] (Crew) Max attempts ({self.config.max_attempts_per_step}) reached for step {current_step}"
                )
                break

            except Exception as e:
                print(f"[supervisor] (Crew) Exception in step {current_step}: {e}")
                error_info = ErrorHandler.handle_step_error(
                    e, current_step, self.session.current_tool or "browser"
                )
                self.session.add_result(
                    current_step,
                    self.session.current_tool or "browser",
                    error_info["status"],
                    error_info["note"],
                )
                if (
                    attempts < self.config.max_attempts_per_step
                    and error_info["recoverable"]
                ):
                    time.sleep(0.2)
                    continue
                print(
                    f"[supervisor] (Crew) Critical error in step {current_step}, stopping"
                )
                break

        done = min(total, max(0, current_step - 1))
        print(f"[supervisor] (Crew) Execution finished: {done}/{total} steps completed")
        return {
            "total": total,
            "done": done,
            "results": self.session.results,
            "session_id": self.session.session_id,
            "final_tool": self.session.current_tool,
        }
