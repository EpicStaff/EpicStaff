"""Project write operations — pull and push crew/agent/task configs."""

import json
import sys
from pathlib import Path

from common import api_get, api_patch, _normalize_slug, PROJECTS_DIR


def cmd_pull_project(args):
    """Pull crew/agent/task configs into .my_epicstaff/projects/."""
    graph = api_get(f"/graphs/{args.graph_id}/")
    crew_nodes = graph.get("crew_node_list", [])
    if not crew_nodes:
        print(f"Flow {args.graph_id} has no crew nodes.")
        return
    outdir = PROJECTS_DIR / str(args.graph_id)
    outdir.mkdir(parents=True, exist_ok=True)
    count = 0
    print(f"Pulling project from flow {args.graph_id} into {outdir}/\n")
    for cn in crew_nodes:
        c = cn.get("crew", {})
        if not isinstance(c, dict):
            continue
        cid = c["id"]
        crew = api_get(f"/crews/{cid}/")
        cslug = _normalize_slug(crew.get("name", str(cid)))
        crew_meta = {
            "id": cid,
            "name": crew.get("name"),
            "process": crew.get("process"),
            "memory": crew.get("memory"),
            "cache": crew.get("cache"),
            "manager_llm_config": crew.get("manager_llm_config"),
            "embedding_config": crew.get("embedding_config"),
            "memory_llm_config": crew.get("memory_llm_config"),
            "agents": crew.get("agents", []),
            "tasks": crew.get("tasks", []),
            "crew_node": {
                "node_name": cn.get("node_name"),
                "input_map": cn.get("input_map"),
                "output_variable_path": cn.get("output_variable_path"),
            },
        }
        p = outdir / f"crew_{cid}_{cslug}.json"
        p.write_text(json.dumps(crew_meta, indent=2))
        print(f"  {p.name}")
        count += 1
        for aid in crew.get("agents", []):
            try:
                agent = api_get(f"/agents/{aid}/")
                aslug = _normalize_slug(agent.get("role", str(aid)))
                agent_meta = {
                    "id": aid,
                    "role": agent.get("role"),
                    "goal": agent.get("goal"),
                    "backstory": agent.get("backstory"),
                    "llm_config": agent.get("llm_config"),
                    "max_iter": agent.get("max_iter"),
                    "memory": agent.get("memory"),
                    "allow_delegation": agent.get("allow_delegation"),
                    "tools": [
                        {"id": (t.get("data", t) if isinstance(t, dict) else t).get("id", t) if isinstance(t, dict) else t,
                         "name": (t.get("data", t) if isinstance(t, dict) else {}).get("name", "?")}
                        for t in agent.get("tools", [])
                    ],
                }
                p = outdir / f"agent_{aid}_{aslug}.json"
                p.write_text(json.dumps(agent_meta, indent=2))
                print(f"  {p.name}")
                count += 1
            except Exception as e:
                print(f"  ❌ agent {aid}: {e}")
        for tid in crew.get("tasks", []):
            try:
                task = api_get(f"/tasks/{tid}/")
                tslug = _normalize_slug(task.get("name", str(tid)))
                task_meta = {
                    "id": tid,
                    "name": task.get("name"),
                    "instructions": task.get("instructions"),
                    "expected_output": task.get("expected_output"),
                    "knowledge_query": task.get("knowledge_query"),
                    "agent": task.get("agent"),
                    "order": task.get("order"),
                }
                p = outdir / f"task_{tid}_{tslug}.json"
                p.write_text(json.dumps(task_meta, indent=2))
                print(f"  {p.name}")
                count += 1
            except Exception as e:
                print(f"  ❌ task {tid}: {e}")
    print(f"\nPulled {count} files.")


def cmd_push_project(args):
    """Push agent/task configs from local files back to the API."""
    if not args.path:
        args.path = str(PROJECTS_DIR)
    p = Path(args.path)
    files = sorted(p.iterdir()) if p.is_dir() else [p]
    ok, fail = 0, 0
    print(f"Pushing project from {p}/\n")
    for f in files:
        if not f.name.endswith(".json"):
            continue
        try:
            data = json.loads(f.read_text())
            obj_id = data.get("id")
            if not obj_id:
                continue
            if f.name.startswith("agent_"):
                patch = {}
                for k in ("role", "goal", "backstory", "llm_config", "max_iter", "memory"):
                    if k in data:
                        patch[k] = data[k]
                if patch:
                    api_patch(f"/agents/{obj_id}/", patch)
                    print(f"  ✅ {f.name} → agent {obj_id}")
                    ok += 1
            elif f.name.startswith("task_"):
                patch = {}
                for k in ("name", "instructions", "expected_output", "knowledge_query"):
                    if k in data:
                        patch[k] = data[k]
                if patch:
                    api_patch(f"/tasks/{obj_id}/", patch)
                    print(f"  ✅ {f.name} → task {obj_id}")
                    ok += 1
            elif f.name.startswith("crew_"):
                patch = {}
                for k in ("name", "process", "memory", "cache"):
                    if k in data:
                        patch[k] = data[k]
                if patch:
                    api_patch(f"/crews/{obj_id}/", patch)
                    print(f"  ✅ {f.name} → crew {obj_id}")
                    ok += 1
        except Exception as e:
            print(f"  ❌ {f.name}: {e}")
            fail += 1
    print(f"\nDone: {ok} pushed, {fail} failed.")
    if fail:
        sys.exit(1)
