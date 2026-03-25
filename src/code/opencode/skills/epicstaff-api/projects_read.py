"""Project inspection commands — crews, agents."""

import json

from common import api_get


def cmd_crews(args):
    """List all crews, or show only the crew(s) used by the current flow."""
    if args.graph_id:
        graph = api_get(f"/graphs/{args.graph_id}/")
        crew_nodes = graph.get("crew_node_list", [])
        if not crew_nodes:
            print(f"Flow {args.graph_id} has no crew nodes.")
            return
        crew_ids = set()
        for cn in crew_nodes:
            c = cn.get("crew")
            if isinstance(c, dict):
                crew_ids.add(c["id"])
            elif isinstance(c, int):
                crew_ids.add(c)
        print(f"Flow {args.graph_id}: {len(crew_nodes)} crew node(s)\n")
        for cn in crew_nodes:
            c = cn.get("crew", {})
            cid = c["id"] if isinstance(c, dict) else c
            cname = c.get("name", "?") if isinstance(c, dict) else "?"
            print(f"  Crew node '{cn.get('node_name')}' (node_id={cn['id']}) → crew {cid}: {cname}")
            imap = cn.get("input_map", {})
            if imap:
                print(f"    input_map: {json.dumps(imap, indent=6)[:300]}")
            print(f"    output_variable_path: {cn.get('output_variable_path')}")
        print()
        for cid in crew_ids:
            _print_crew_detail(cid)
    else:
        crews = api_get("/crews/")
        print(f"All crews ({len(crews)}):")
        for c in crews:
            agents = c.get("agents", [])
            print(f"  [{c['id']:3d}] {c.get('name','?'):40s}  process={c.get('process')}  agents={agents}")


def _print_crew_detail(crew_id):
    """Print detailed crew info including agents, tasks, tools."""
    crew = api_get(f"/crews/{crew_id}/")
    print(f"{'='*70}")
    print(f"CREW {crew_id}: {crew.get('name')}")
    print(f"{'='*70}")
    print(f"  process: {crew.get('process')}")
    print(f"  memory: {crew.get('memory')}")
    print(f"  cache: {crew.get('cache')}")
    mgr = crew.get("manager_llm_config")
    if mgr:
        print(f"  manager_llm_config: {mgr}")
    emb = crew.get("embedding_config")
    if emb:
        print(f"  embedding_config: {emb}")

    tasks = crew.get("tasks", [])
    if tasks:
        print(f"\n  Tasks ({len(tasks)}):")
        for tid in tasks:
            try:
                task = api_get(f"/tasks/{tid}/")
                print(f"    Task {tid}: {task.get('name', '?')}")
                inst = str(task.get("instructions", ""))
                if inst:
                    print(f"      instructions: {inst[:200]}{'...' if len(inst)>200 else ''}")
                eo = str(task.get("expected_output", ""))
                if eo:
                    print(f"      expected_output: {eo[:150]}{'...' if len(eo)>150 else ''}")
                kq = task.get("knowledge_query")
                if kq:
                    print(f"      knowledge_query: {str(kq)[:150]}")
                print(f"      agent: {task.get('agent')}")
            except Exception as e:
                print(f"    Task {tid}: ERROR {e}")

    agent_ids = crew.get("agents", [])
    if agent_ids:
        print(f"\n  Agents ({len(agent_ids)}):")
        for aid in agent_ids:
            _print_agent_summary(aid, indent=4)


def _print_agent_summary(agent_id, indent=2):
    """Print agent summary with tools."""
    pfx = " " * indent
    try:
        agent = api_get(f"/agents/{agent_id}/")
    except Exception as e:
        print(f"{pfx}Agent {agent_id}: ERROR {e}")
        return
    print(f"{pfx}Agent {agent_id}: {agent.get('role')}")
    print(f"{pfx}  goal: {str(agent.get('goal',''))[:150]}")
    backstory = str(agent.get("backstory", ""))
    if backstory:
        print(f"{pfx}  backstory: {backstory[:150]}{'...' if len(backstory)>150 else ''}")
    llm = agent.get("llm_config")
    if llm:
        print(f"{pfx}  llm_config: {llm}")
    tools = agent.get("tools", [])
    if tools:
        print(f"{pfx}  tools ({len(tools)}):")
        for t in tools:
            if isinstance(t, dict):
                d = t.get("data", t)
                print(f"{pfx}    [{d.get('id')}] {d.get('name')} — {str(d.get('description',''))[:70]}")
            else:
                print(f"{pfx}    {t}")


def cmd_agents(args):
    """List all agents, or show agents for the flow's crew."""
    if args.graph_id:
        graph = api_get(f"/graphs/{args.graph_id}/")
        crew_nodes = graph.get("crew_node_list", [])
        agent_ids = set()
        for cn in crew_nodes:
            c = cn.get("crew", {})
            if isinstance(c, dict):
                for aid in c.get("agents", []):
                    agent_ids.add(aid)
        if not agent_ids:
            print(f"No agents found in flow {args.graph_id}")
            return
        print(f"Agents in flow {args.graph_id}:")
        for aid in sorted(agent_ids):
            _print_agent_summary(aid, indent=2)
    else:
        agents = api_get("/agents/")
        print(f"All agents ({len(agents)}):")
        for a in agents:
            tools = a.get("tools", [])
            tool_count = len(tools)
            print(f"  [{a['id']:3d}] {str(a.get('role','?')):40s}  tools={tool_count}  llm_config={a.get('llm_config')}")
