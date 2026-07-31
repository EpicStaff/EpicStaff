from fastmcp import Client
import uuid


class Hub:
    def __init__(self, url: str, timeout: float = 600.0, session_id: str | None = None):
        self.url = url
        self.timeout = timeout
        self.client = None
        self.session_id = session_id or str(uuid.uuid4())

    async def ainit(self):
        self.client = await Client(self.url, timeout=self.timeout).__aenter__()

    async def aclose(self):
        if self.client:
            await self.client.__aexit__(None, None, None)

    async def run_step(
        self,
        step_idx: int,
        step: dict,
        plan_ctx: dict,
        tool: str = "auto",
        reset: bool = False,
        model: str | None = None,
        temperature: float | None = None,
        start_tool: str | None = None,
    ):
        payload = {
            "session_id": self.session_id,
            "step_idx": step_idx,
            "tool": tool,
            "step": step,
            "plan": plan_ctx,
            "reset": reset,
        }
        if model:
            payload["model"] = model
        if temperature is not None:
            payload["temperature"] = temperature
        if start_tool and step_idx == 1:
            payload["start_tool"] = start_tool

        return await self.client.call_tool("run_step", payload)
