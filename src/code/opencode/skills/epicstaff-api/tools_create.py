"""Tool create operations — create new Python code tools."""

import json

from common import api_post, api_get


def cmd_create_tool(args):
    """Create a new Python code tool."""
    name = args.name
    description = getattr(args, "description", "")
    code = ""
    if getattr(args, "code_file", None):
        with open(args.code_file) as f:
            code = f.read()

    payload = {
        "name": name,
        "description": description,
        "python_code": {"code": code, "libraries": []},
        "args_schema": {"type": "object", "properties": {}},
    }
    result = api_post("/python-code-tool/", payload)
    tid = result.get("id")
    print(f"Created tool: [{tid}] {result.get('name')}")
    if description:
        print(f"  description: {description}")
    if code:
        print(f"  code: {len(code)} chars")
    return result
