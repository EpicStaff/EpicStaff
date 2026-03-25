# Troubleshooting

Read this when a flow fails, returns nothing, or behaves unexpectedly.

## Debug Ladder

Always check recent sessions first (`sessions -n 5`) to understand concurrent sessions, routes taken, and completion status before diving deeper.

When a flow fails, follow this order:

1. **`sessions -n 3`** — look for `[error]`, premature `[graph_end]`, missing nodes in trace
1b. **`session-inspect <SID> --full`** — when you need to understand why a decision was taken or what exactly a node received/produced (untruncated structured responses)
2. **`route-map`** — CDT shows "NOT FOUND in metadata" → DB node_name ≠ metadata name
3. **`edges`** — 0 edges = no non-CDT routing possible
4. **`cdt-prompts`** — missing prompt_id → "name 'X' is not defined" error
5. **`cdt-code`** — empty `pre_input_map` → main() receives None/NameError
6. **`export-compare <FILE>`** — spot missing prompts, changed input maps, code drift
7. **`verify .my_epicstaff/flows/<ID>/`** — ensures file ↔ DB ↔ metadata sync
8. **`oc-sessions` / `oc-status`** — stuck/stale OpenCode sessions ("Request queued")

## Common Errors

| Error | Likely Cause |
|---|---|
| `Connection refused` | Backend not running, wrong `API_BASE_URL` or `DJANGO_PORT` |
| `HTTP 404` | Wrong endpoint or resource ID |
| `HTTP 500` | Backend bug — check Django logs |
| `Timed out: no response for 60 seconds` | OpenCode down, wrong model ID, or missing API key |
| Node shows as black dot | Metadata out of sync — run `init-metadata` |
| `"Found edge starting at unknown node"` | Node was renamed but edges still reference old name — use `rename-node` |

## Additional API References

### Python Code Tools (Agent Tools)

Tools run in sandboxed containers:
- `GET/POST /api/python-code-tool/` — list/create
- `GET/PATCH /api/python-code-tool/<id>/` — read/update

Agent's `main()` docstring determines when the agent uses the tool. Include: what, when, args, returns, examples.

Tool assignment: `tool_ids` on agent PATCH (destructive replace — include all IDs).

### Knowledge & GraphRAG

- `POST /api/graph-rag/collections/{coll_id}/graph-rag/` — create
- `GET /api/graph-rag/{id}/` — details
- `PUT /api/graph-rag/{id}/index-config/` — update config
- `POST /api/process-rag-indexing/` — trigger indexing (`{"rag_id": N, "rag_type": "graph"}`)

One GraphRAG per collection. LLM field is read-only (use Django shell). Indexing runs async in knowledge container.
