from orchestrator.core.config import AgentConfig
from orchestrator.core.session_manager import session_manager
from orchestrator.core.error_handler import ErrorHandler
import time
from typing import Dict, Any, List


def choose_tool_for_step(
    step: Dict[str, Any], current_tool: str, fail_streak: int, config: AgentConfig
) -> str:
    action = step.get("action", "")
    target_kind = step.get("target_kind", "unknown")
    risk = step.get("risk", "med")
    target = step.get("target", "").lower()

    if action == "type" and "password" in target:
        return "computer"

    if "login" in target and action == "assert":
        return "computer"

    if fail_streak >= config.escalate_threshold:
        return "computer"

    if action == "click" and (
        target_kind in ("icon", "menu") or risk in ("med", "high")
    ):
        return "computer"

    return current_tool


class Supervisor:
    def __init__(
        self,
        hub,
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
        print(
            f"[supervisor] Initialized with {len(steps)} steps, session {hub.session_id[:8]}"
        )

    async def run(self) -> Dict[str, Any]:
        total = len(self.steps)
        current_step = 1

        while 1 <= current_step <= total:
            step = self.steps[current_step - 1]
            attempts = self.session.increment_attempts(current_step)

            tool_choice = choose_tool_for_step(
                step, self.session.current_tool, self.session.fail_streak, self.config
            )

            start_tool = None
            reset = False
            if current_step == 1 and attempts == 1:
                start_tool = self.config.start_tool or tool_choice
                reset = True

            print(
                f"[supervisor] step={current_step}/{total} attempt={attempts} tool={tool_choice} "
                f"fail_streak={self.session.fail_streak} desktop_ok_streak={self.session.desktop_success_streak}"
            )

            try:
                result = await self.hub.run_step(
                    step_idx=current_step,
                    step=step,
                    plan_ctx={
                        "total_steps": total,
                        "user_prompt": self.user_context,
                        "steps": self.steps,
                    },
                    tool=tool_choice,
                    reset=reset,
                    model=self.config.deepseek_model,
                    temperature=self.config.deepseek_temperature,
                    start_tool=start_tool,
                )

                data = (
                    getattr(result, "structured_content", None)
                    or getattr(result, "data", {})
                    or {}
                )
                status = (data.get("status") or "").upper()
                note = data.get("note") or data.get("error") or ""
                tool_used = data.get("tool_used", tool_choice)

                print(
                    f"[supervisor] -> status={status} tool_used={tool_used} note_length={len(note)}"
                )

                if status == "PASSED":
                    self._handle_success(current_step, tool_used, note)
                    current_step += 1
                    continue

                if status == "REWIND":
                    self._handle_rewind(current_step, tool_used, note)
                    current_step = max(1, current_step - 1)
                    self.session.reset_step_attempts(current_step)
                    time.sleep(0.2)
                    continue

                self._handle_failure(current_step, tool_used, note)
                if attempts < self.config.max_attempts_per_step:
                    time.sleep(0.2)
                    continue

                print(
                    f"[supervisor] Max attempts ({self.config.max_attempts_per_step}) reached for step {current_step}"
                )
                break

            except Exception as e:
                print(f"[supervisor] Exception in step {current_step}: {e}")
                error_info = ErrorHandler.handle_step_error(
                    e, current_step, tool_choice
                )
                self._handle_failure(current_step, tool_choice, error_info["note"])
                if (
                    attempts < self.config.max_attempts_per_step
                    and error_info["recoverable"]
                ):
                    time.sleep(0.2)
                    continue
                print(f"[supervisor] Critical error in step {current_step}, stopping")
                break

        done = min(total, max(0, current_step - 1))
        print(f"[supervisor] Execution finished: {done}/{total} steps completed")
        return {
            "total": total,
            "done": done,
            "results": self.session.results,
            "session_id": self.session.session_id,
            "final_tool": self.session.current_tool,
        }

    def _handle_success(self, step_idx: int, tool_used: str, note: str):
        self.session.add_result(step_idx, tool_used, "PASSED", note)
        self.session.fail_streak = 0

        switch_step = self.config.switch_to_computer_after_step
        if switch_step is not None and step_idx == switch_step:
            print(
                f"[supervisor] Switching tool to 'computer' after step {step_idx} as configured"
            )
            self.session.current_tool = "computer"
            self.session.desktop_success_streak = 0
            return

        if tool_used == "computer":
            self.session.desktop_success_streak += 1
            if self.session.desktop_success_streak >= self.config.deescalate_after:
                print(
                    f"[supervisor] Deescalating to browser after {self.session.desktop_success_streak} desktop successes"
                )
                self.session.current_tool = "browser"
                self.session.desktop_success_streak = 0
        else:
            self.session.desktop_success_streak = 0
            self.session.current_tool = "browser"

    def _handle_failure(self, step_idx: int, tool_used: str, note: str):
        self.session.add_result(step_idx, tool_used, "FAILED", note)
        self.session.fail_streak += 1
        if self.session.fail_streak >= self.config.escalate_threshold:
            if self.session.current_tool != "computer":
                print(
                    f"[supervisor] Escalating to computer after {self.session.fail_streak} failures"
                )
            self.session.current_tool = "computer"

    def _handle_rewind(self, step_idx: int, tool_used: str, note: str):
        self.session.add_result(step_idx, tool_used, "REWIND", note)
        self.session.fail_streak += 1
        if self.session.fail_streak >= self.config.escalate_threshold:
            if self.session.current_tool != "computer":
                print(
                    f"[supervisor] Escalating to computer after rewind (fail_streak={self.session.fail_streak})"
                )
            self.session.current_tool = "computer"
