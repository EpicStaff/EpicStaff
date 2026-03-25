export const DEFAULT_OUTPUT_SCHEMA: Record<string, any> = {
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "EpicChatResponse",
  "description": "Load skill 'epicchat-response' for full formatting guide (tables, buttons, navigation, build mode).",
  "type": "object",
  "required": ["message"],
  "additionalProperties": true,
  "properties": {
    "message": {
      "type": "string",
      "description": "Main chat reply (Markdown supported). This is the ONLY required field."
    },
    "tools": {
      "type": "array",
      "items": { "type": "string", "enum": ["Build mode"] }
    },
    "ef_tables": {
      "type": "array",
      "description": "Interactive data tables below the message. Each object needs at minimum a 'rows' array of objects.",
      "items": { "type": "object" }
    },
    "action_message": {
      "type": "array",
      "description": "Buttons, links, prompt suggestions displayed with the message.",
      "items": { "$ref": "#/$defs/action" }
    }
  },
  "$defs": {
    "action": {
      "type": "object",
      "required": ["type"],
      "description": "An interactive element: button, link, or prompt suggestion.\n\n## Build Mode\nYou might be in plan mode (read-only). The user already knows — do not explain it.\nTo let the user launch you in build mode, offer a button: {'type': 'button', 'text': 'Allow build mode (N turns)', 'action': 'sendAction'}\nOnce the user clicks it, you will be relaunched in build mode and can make changes.\nIf you need more turns while already in build mode, offer the button again.\nAt each build turn, show how many build turns remain.\nErr on the side of offering the button — always better to offer than to omit.\n\n### Button text patterns\n- 'Allow build mode' — 1 turn\n- 'Allow build mode (N turns)' — N turns\n- 'Allow build mode (N turns) - <option>' — N turns, forwards the chosen option label. Use when proposing multiple approaches.\n\nChoose the turn count based on how many steps your plan requires. Each turn is one agent response. Examples:\n- Simple one-step fix → 'Allow build mode' (1 turn)\n- Multi-step plan (create node, add edge, patch config) → 'Allow build mode (3 turns)'\n\n### Build Mode Rules\n- ALWAYS offer the build mode button when your plan involves creating, editing, or deleting anything — no exceptions.\n- After presenting a plan, include the button so the user can approve with one click.\n- Multi-turn build persists automatically — the flow tracks remaining turns. You do NOT need to re-request.\n- When you receive build permission, proceed immediately with the plan you proposed.\n- If the user asks you to build, create, or modify something, first outline your plan, estimate the turns needed, then offer the button.\n- Err on the side of asking — it is better to offer the button too often than to forget.\n- When multi-turn build is active, you will see a message like 'Build mode continues (N turn(s) remaining)'. Keep executing your plan.\n\n## Navigation Actions\nThe widget supports navigating the user to flows and nodes in the EpicStaff UI:\n- **openFlow**: Opens a flow by ID in the visual programming editor AND automatically refreshes the page cache. Offer this after creating or modifying a flow.\n- **openNode**: Opens a specific node within a flow (expands the node panel) AND automatically refreshes.\n- **refreshCache**: Reloads the page. Use ONLY standalone when the user is already viewing the correct flow.\n\n### Navigation Rules\n- After modifications, ALWAYS include a refreshCache button alongside your navigation button (openFlow or openNode) to ensure the user sees the latest state.\n- Example: offer both 'Open flow 56' (openFlow) and 'Refresh cache' (refreshCache) as two buttons.\n\n## Prompt Suggestions\nUse 'prompt' type elements to suggest follow-up questions or actions. These appear as chips in the input footer. Always offer 2-3 relevant suggestions after completing a task.",
      "properties": {
        "type": { "type": "string", "enum": ["button", "link", "prompt"], "description": "'button' = clickable button. 'link' = hyperlink. 'prompt' = suggestion chip." },
        "text": { "type": "string", "description": "Display label. For 'prompt', also the text sent as next user message. To request build mode, use text 'Allow build mode' (1 turn) or 'Allow build mode (N turns)' for multi-turn." },
        "action": { "type": "string", "description": "Action identifier: 'sendAction', 'link', 'processTables', 'switchAgent', 'openFlow', 'openNode', 'refreshCache'." },
        "params": { "type": "object", "additionalProperties": true, "description": "Extra params. For 'link': {url: '...'}. For 'switchAgent': {flow_id: N}. For 'openFlow': {flowId: N}. For 'openNode': {flowId: N, nodeId: '<uuid>'}." }
      }
    }
  }
};
