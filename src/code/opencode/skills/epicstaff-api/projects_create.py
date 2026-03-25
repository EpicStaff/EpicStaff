"""Project create operations — create new crews, agents, and tasks."""

import json

from common import api_get, api_post, api_patch


def cmd_create_crew(args):
    """Create a new crew."""
    payload = {
        "name": args.name,
        "process": getattr(args, "process", "sequential"),
        "memory": False,
        "cache": True,
    }
    result = api_post("/crews/", payload)
    cid = result.get("id")
    print(f"Created crew: [{cid}] {result.get('name')} (process={result.get('process')})")
    print(f"  ⚠️  REMINDER: When adding this crew to a flow, the crew node needs:")
    print(f"     - input_map: map node parameters to flow variables (e.g. {{\"topic\": \"variables.request.topic\"}})")
    print(f"     - output_variable_path: set to 'variables' or 'variables.<domain>' to store crew output")
    return result


def cmd_create_agent(args):
    """Create a new agent and optionally add to a crew."""
    payload = {
        "role": args.role,
        "goal": getattr(args, "goal", ""),
        "backstory": getattr(args, "backstory", ""),
    }
    llm_config_id = getattr(args, "llm_config", None)
    if llm_config_id:
        payload["llm_config"] = int(llm_config_id)

    result = api_post("/agents/", payload)
    aid = result.get("id")
    print(f"Created agent: [{aid}] role={result.get('role')}")

    if not llm_config_id:
        print(f"  ⚠️  WARNING: No LLM config set. Agent will not work until an LLM config is assigned.")
        print(f"     Fix: PATCH /agents/{aid}/ with {{\"llm_config\": <config_id>}}")
        print(f"     Available configs: run 'epicstaff_tools.py -r llm-configs'")

    crew_id = getattr(args, "crew_id", None)
    if crew_id:
        crew = api_get(f"/crews/{crew_id}/")
        agents = crew.get("agents", [])
        if aid not in agents:
            agents.append(aid)
            api_patch(f"/crews/{crew_id}/", {"agents": agents})
            print(f"  Added to crew {crew_id}")
    return result


def cmd_create_task(args):
    """Create a new task and optionally add to a crew."""
    payload = {
        "name": args.name,
        "instructions": getattr(args, "instructions", ""),
        "expected_output": getattr(args, "expected_output", None) or "Task output",
    }
    agent_id = getattr(args, "agent_id", None)
    if agent_id:
        payload["agent"] = agent_id

    result = api_post("/tasks/", payload)
    tid = result.get("id")
    print(f"Created task: [{tid}] {result.get('name')}")
    if agent_id:
        print(f"  Assigned to agent {agent_id}")

    crew_id = getattr(args, "crew_id", None)
    if crew_id:
        crew = api_get(f"/crews/{crew_id}/")
        tasks = crew.get("tasks", [])
        if tid not in tasks:
            tasks.append(tid)
            api_patch(f"/crews/{crew_id}/", {"tasks": tasks})
            print(f"  Added to crew {crew_id}")
    return result
