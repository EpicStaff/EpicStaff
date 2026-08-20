import json
from collections.abc import Sequence

from app.prompt.base import PromptBuilder
from shared.models.agent_service import AgentSpec, ContextAttachment


class SingleTaskPromptBuilder(PromptBuilder):
    def build(
        self,
        agent: AgentSpec,
        *,
        instructions: str,
        output_schema: dict | None = None,
        attachments: Sequence[ContextAttachment] = (),
    ) -> list[dict]:
        return [
            {"role": "system", "content": self._system_prompt(agent)},
            *self._attachment_messages(attachments),
            {"role": "user", "content": self._task_prompt(instructions, output_schema)},
        ]

    def _task_prompt(self, instructions: str, output_schema: dict | None) -> str:
        if output_schema:
            return (
                f"{instructions}\n\nRespond with a JSON object matching this schema:\n"
                f"{json.dumps(output_schema)}"
            )

        return instructions
