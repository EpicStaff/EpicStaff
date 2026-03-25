"""Tool inspection commands — list and show tool details."""

import json

from common import api_get


def cmd_tools(args):
    """List all python code tools, or show tools for the flow's agents."""
    if args.graph_id:
        graph = api_get(f"/graphs/{args.graph_id}/")
        crew_nodes = graph.get("crew_node_list", [])
        tool_map = {}
        for cn in crew_nodes:
            c = cn.get("crew", {})
            if isinstance(c, dict):
                for aid in c.get("agents", []):
                    try:
                        agent = api_get(f"/agents/{aid}/")
                        for t in agent.get("tools", []):
                            if isinstance(t, dict):
                                d = t.get("data", t)
                                tool_map[d.get("id")] = d
                    except Exception:
                        pass
        if not tool_map:
            print(f"No tools found in flow {args.graph_id}")
            return
        print(f"Tools in flow {args.graph_id} ({len(tool_map)}):")
        for tid, d in sorted(tool_map.items()):
            print(f"  [{tid:3d}] {d.get('name','?'):40s} — {str(d.get('description',''))[:60]}")
    else:
        tools = api_get("/python-code-tool/")
        print(f"All tools ({len(tools)}):")
        for t in tools:
            print(f"  [{t['id']:3d}] {t.get('name','?'):40s} — {str(t.get('description',''))[:60]}")


def cmd_tool(args):
    """Show detailed tool info including code."""
    tool = api_get(f"/python-code-tool/{args.tool_id}/")
    print(f"Tool {tool['id']}: {tool.get('name')}")
    print(f"  description: {tool.get('description')}")
    schema = tool.get("args_schema", {})
    props = schema.get("properties", {})
    if props:
        print(f"  args:")
        for k, v in props.items():
            print(f"    {k}: {v.get('type','?')} — {v.get('description','')}")
    code_obj = tool.get("python_code", {})
    if isinstance(code_obj, dict):
        libs = code_obj.get("libraries", [])
        if libs:
            print(f"  libraries: {libs}")
        code = code_obj.get("code", "")
        if code:
            print(f"\n  Code ({len(code)} chars):")
            for i, line in enumerate(code.split("\n")[:50], 1):
                print(f"    {i:3d} | {line}")
            if code.count("\n") > 50:
                print(f"    ... ({code.count(chr(10)) - 50} more lines)")
