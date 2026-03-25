# CLI Command Reference

All commands below use the base invocation:
```
python3 epicstaff_tools.py [-r] [-g <GRAPH_ID>] <command> [args]
```

`-r` = read-only (auto-run without user approval). `-g` = graph/flow ID.

## Inspection (all read-only, use `-r`)
```
-r    list                             # All flows
-r -g <ID> get                         # Flow overview
-r -g <ID> nodes                       # Node list with types
-r -g <ID> edges                       # DB edges (non-DT routing)
-r -g <ID> connections                 # Metadata connections (DT/CDT + non-DT)
-r -g <ID> route-map                   # DT/CDT routing verification
-r -g <ID> cdt                         # CDT node details
-r -g <ID> cdt-code                    # CDT pre/post computation code
-r -g <ID> cdt-prompts                 # CDT prompts by ID
```

## Session Debugging (all read-only, use `-r`)
```
-r -g <ID> sessions                    # Last 2 sessions
-r -g <ID> sessions -n 5 -c           # Last 5, compact
-r    session <SID> <SID>              # Compare specific sessions
-r    session-inspect <SID>            # Per-node input/output (truncated)
-r    session-inspect <SID> --full     # Per-node input/output (untruncated)
-r    session-timings <SID>            # Per-node timing breakdown
-r -g <ID> vars                        # Persistent variables
-r -g <ID> history <CHAT_ID>           # Message history
-r    crew-input <SID>                 # Crew node input/output
```

## Project / Crew / Agent / Tool (read-only, use `-r`)
```
-r -g <ID> crews                       # Flow's crew with agents, tasks, tools
-r    crews                            # All crews (no -g)
-r -g <ID> agents                      # Flow's agents
-r -g <ID> tools                       # Flow's tools
-r    tool <TOOL_ID>                   # Tool details + code
-r    agents                           # All agents (find llm_config IDs here)
```

## OpenCode (Code Container)
```
-r    oc-status                        # Instance health
-r    oc-sessions                      # All sessions + stale detection
-r    oc-messages -n 20                # Last N messages
      oc-abort                         # Abort stuck request (write — no -r)
```

## Data Sync — Flows
```
   -g <ID> pull                                       # Pull DB state → local files
   -g <ID> push .my_epicstaff/flows/<ID>/             # Push local → DB + metadata
-r -g <ID> verify .my_epicstaff/flows/<ID>/           # Three-way verify (read-only)
-r -g <ID> export-compare <FILE>                      # Compare export with current
```

## Data Sync — Tools
```
   -g <ID> pull-tools                                 # Pull tool code for flow's agents
      pull-tools                                      # Pull ALL tools
      push-tools .my_epicstaff/tools/<ID>/            # Push tool code back
```

## Data Sync — Projects
```
   -g <ID> pull-project                               # Pull crew/agent/task configs
      push-project .my_epicstaff/projects/<ID>/       # Push configs back
```

## Patching (all write — no `-r`)
```
-g <ID> patch-python "Node Name" --value-file code.py
-g <ID> patch-webhook "Webhook Name" --value-file code.py
-g <ID> patch-code-agent "Node Name" --field system_prompt --value "new prompt"
-g <ID> patch-cdt "Name" post_computation_code --value-file code.py
-g <ID> patch-dt "DT Name" --groups-file groups.json  # Patch Decision Table condition groups
-g <ID> patch-libraries "Node Name" "requests,pandas"  # Set libraries on a Python node
-g <ID> patch-node-meta "Node Name" --field key --value val  # Patch metadata field
-g <ID> patch-start-vars --value-file vars.json       # Patch __start__ node variables
-g <ID> rename-node "Old Name" "New Name"              # Updates DB + metadata (edges use IDs, no update needed)
-g <ID> sync-metadata                                  # Sync CDT code into metadata
```

## Structure Editing (write — no `-r`)
```
-g <ID> create-edge "Source" "Target"                  # Add edge
-g <ID> delete-edge "Source" "Target"                  # Remove edge
-g <ID> create-start-node                              # Create __start__ node if missing
-g <ID> create-note "Text" --near "Node Name"          # Canvas annotation
```

## Testing
```
-r -g <ID> test-flow                                   # Structural verification
-r -g <ID> test-flow -v                                # Verbose
-r -g <ID> test-flow --verify                          # + file/DB/metadata sync check
   -g <ID> run-session                                 # Trigger actual flow execution
   -g <ID> run-session --variables '{"key": "val"}' --timeout 120
```

## Session Trace (read-only)
```
-r    trace <SID>                                      # Full execution trace for a session
```
