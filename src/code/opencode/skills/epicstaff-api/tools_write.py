"""Tool write operations — pull and push tool code."""

import re
import json
import sys
from pathlib import Path

from common import api_get, api_patch, _tool_slug, _get_flow_tool_ids, TOOLS_DIR


def cmd_pull_tools(args):
    """Pull tool code and metadata into .my_epicstaff/tools/."""
    if args.graph_id:
        tool_ids = _get_flow_tool_ids(args.graph_id)
        outdir = TOOLS_DIR / str(args.graph_id)
    else:
        tool_ids = None
        outdir = TOOLS_DIR / "all"
    outdir.mkdir(parents=True, exist_ok=True)
    all_tools = api_get("/python-code-tool/")
    count = 0
    print(f"Pulling tools into {outdir}/\n")
    for t in all_tools:
        tid = t["id"]
        if tool_ids is not None and tid not in tool_ids:
            continue
        slug = _tool_slug(t.get("name", str(tid)))
        prefix = f"tool_{tid}_{slug}"
        pc = t.get("python_code", {})
        code = pc.get("code", "") if isinstance(pc, dict) else ""
        if code.strip():
            p = outdir / f"{prefix}.py"
            p.write_text(code)
            print(f"  {p.name} ({len(code)} chars)")
            count += 1
        meta = {
            "id": tid,
            "name": t.get("name"),
            "description": t.get("description"),
            "args_schema": t.get("args_schema", {}),
            "libraries": (pc.get("libraries", []) if isinstance(pc, dict) else []),
        }
        p = outdir / f"{prefix}.json"
        p.write_text(json.dumps(meta, indent=2))
        print(f"  {p.name}")
        count += 1
    print(f"\nPulled {count} files.")


def cmd_push_tools(args):
    """Push tool code from local files back to the API."""
    if not args.path:
        args.path = str(TOOLS_DIR)
    p = Path(args.path)
    if p.is_dir():
        files = sorted(p.iterdir())
        print(f"Pushing tools from {p}/\n")
    else:
        files = [p]
        print(f"Pushing tool {p.name}\n")
    ok, fail = 0, 0
    for f in files:
        if not f.name.endswith(".py") or not f.name.startswith("tool_"):
            continue
        m = re.match(r"^tool_(\d+)_(.+)\.py$", f.name)
        if not m:
            continue
        tid = int(m.group(1))
        code = f.read_text()
        meta_path = f.with_suffix(".json")
        libs = []
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            libs = meta.get("libraries", [])
        try:
            api_patch(f"/python-code-tool/{tid}/", {
                "python_code": {"code": code, "libraries": libs}
            })
            print(f"  ✅ {f.name} → tool {tid}")
            ok += 1
        except Exception as e:
            print(f"  ❌ {f.name}: {e}")
            fail += 1
    print(f"\nDone: {ok} pushed, {fail} failed.")
    if fail:
        sys.exit(1)
