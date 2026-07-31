import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from fastmcp import Client


@dataclass
class MCPService:
    name: str
    url: str


@dataclass
class MCPNodeConfig:
    services: Dict[str, MCPService] = field(default_factory=dict)
    default_service: str = "browser-use"

    allowed_tools: Dict[str, list[str]] = field(
        default_factory=lambda: {
            "browser-use": ["run_browser"],
        }
    )

    timeout_s: float = 300.0
    retries: int = 1


class MCPToolNode:
    def __init__(self, cfg: MCPNodeConfig):
        if not cfg.services:
            raise ValueError(
                "MCPNodeConfig.services is empty. Add at least one MCPService."
            )
        if cfg.default_service not in cfg.services:
            raise ValueError(
                f"default_service '{cfg.default_service}' not found in services."
            )
        self.cfg = cfg

    def _validate(self, service: str, tool_name: str) -> None:
        if service not in self.cfg.services:
            raise ValueError(
                f"Unknown service '{service}'. Known: {list(self.cfg.services.keys())}"
            )
        allowed = self.cfg.allowed_tools.get(service, [])
        if allowed and tool_name not in allowed:
            raise ValueError(
                f"Tool '{tool_name}' is not allowed for service '{service}'. Allowed: {allowed}"
            )

    async def _acall(
        self, service: str, tool_name: str, payload: Dict[str, Any]
    ) -> Any:
        self._validate(service, tool_name)
        service_url = self.cfg.services[service].url
        async with Client(service_url, timeout=self.cfg.timeout_s) as client:
            return await client.call_tool(tool_name, payload or {})

    def call(
        self,
        tool_name: str,
        payload: Optional[Dict[str, Any]] = None,
        service: Optional[str] = None,
    ) -> Any:
        payload = payload or {}
        service = service or self.cfg.default_service

        last_err: Optional[Exception] = None
        for _ in range(self.cfg.retries + 1):
            try:
                return asyncio.run(self._acall(service, tool_name, payload))
            except Exception as e:
                last_err = e
        raise last_err


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MCPToolNode CLI")
    parser.add_argument("--service", default="browser-use", help="Service name")
    parser.add_argument(
        "--url", default="http://127.0.0.1:8080/mcp", help="MCP server URL"
    )
    parser.add_argument(
        "--tool", required=True, help="Tool name to call (e.g. run_browser)"
    )
    parser.add_argument("--payload", default="{}", help="JSON payload string")
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=300.0)
    args = parser.parse_args()

    cfg = MCPNodeConfig(
        services={args.service: MCPService(name=args.service, url=args.url)},
        default_service=args.service,
        allowed_tools={args.service: []},
        retries=args.retries,
        timeout_s=args.timeout,
    )

    node = MCPToolNode(cfg)
    payload = json.loads(args.payload)
    result = node.call(tool_name=args.tool, payload=payload, service=args.service)
    print(json.dumps(result, ensure_ascii=False, indent=2))
