# Stream Step Consolidation — Widget Instructions

## Problem

The Code Agent sends multiple `code_agent_stream` messages during a single thinking step (as reasoning text grows). The widget currently renders each as a separate ▸ entry in the Thinking expander, making it look like the agent took 10+ steps when it really did 3.

## Solution

Stream messages now include a `step_id` (integer) in `message_data`:

```json
{
  "message_type": "code_agent_stream",
  "text": "Thinking about the problem...\n\n[Running command] epicstaff_tools.py sessions -n 2 -r",
  "is_final": false,
  "step_id": 2,
  "sse_visible": true
}
```

### Widget behavior

When displaying `code_agent_stream` messages in the Thinking expander:

1. If the incoming `step_id` matches the last displayed entry's `step_id` → **replace** that entry's text (update in-place)
2. If `step_id` is different (or new) → **append** a new entry

This means:
- Reasoning-only updates within the same OC message → same `step_id` → single ▸ entry that updates
- New tool call / new OC message → new `step_id` → new ▸ entry

### `step_id` semantics

- Starts at 0 per agent execution
- Increments each time a new stream message is actually emitted (i.e., reasoning text changed or new tool calls appeared)
- Does **not** increment on every OpenCode message — only when there's genuinely new content to display
- If `step_id` is absent (legacy messages), fall back to current behavior (append)

### Sessions UI

Same logic applies to the Sessions page message list — consecutive `code_agent_stream` messages with the same `step_id` should be collapsed into one row, showing only the latest text.

## Example

Before (current): 8 entries in Thinking expander
```
▸ Loading EpicStaff Flow Management skill...
▸ Reading skill documentation...
▸ Planning approach...
▸ [Running command] epicstaff_tools.py sessions -n 2 -r
▸ Analyzing session data...
▸ Formatting response...
▸ Building table...
▸ Adding suggestions...
```

After (with step_id consolidation): 3 entries
```
▸ Loading EpicStaff Flow Management skill...  (step_id=1)
▸ [Running command] epicstaff_tools.py sessions -n 2 -r  (step_id=2)
▸ Formatting response with table and suggestions...  (step_id=3)
```
