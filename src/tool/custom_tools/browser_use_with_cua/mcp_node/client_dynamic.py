import os
from mcptool_node import MCPNodeConfig, MCPService, MCPToolNode
from prompt import PROMPT
from config import DEEPSEEK_MODEL, DEEPSEEK_TEMPERATURE

MCP_BROWSER_URL = os.getenv("MCP_BROWSER_URL", "http://127.0.0.1:8080/mcp")
MCP_COMPUTER_URL = os.getenv("MCP_COMPUTER_URL", "http://127.0.0.1:8080/mcp")

cfg = MCPNodeConfig(
    services={
        "browser_use_with_cua": MCPService(
            name="browser_use_with_cua", url=MCP_BROWSER_URL
        ),
    },
    default_service="browser-use",
    allowed_tools={
        "browser-use": ["run_browser"],
        "computer-use": ["run_computer"],
    },
    retries=1,
    timeout_s=600.0,
)

node = MCPToolNode(cfg)

result = node.call(
    tool_name="run_browser",
    payload={
        "prompt": PROMPT,
        "model": DEEPSEEK_MODEL,
        "temperature": DEEPSEEK_TEMPERATURE,
    },
    service="browser_use_with_cua",
)

print("Tool result:")
print(result)
