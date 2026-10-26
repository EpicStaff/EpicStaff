# Chat flow contract

What a flow bound to a chat desk gets when a visitor's message starts it, and what it must
answer. The chat service checks the declared names when a desk is saved
(`check_contract`); the values are built by `run_variables()` in
`src/chat/application/orchestrators/conversation.py`.

## Start variables

Sent on every run, whether the start node declares them or not. A flow must declare
`chat_history` and `user_message`.

| Variable | Value |
|---|---|
| `chat_history` | The desk's last `history_window` visitor, bot and operator messages before this one, oldest first: `[{role, content}]`. A visitor message that answered an action adds `action`, cut to its `type`, `action` and `text` (see below). |
| `user_message` | The visitor's text; `""` for a message that is only an action. |
| `action` | The visitor's answer to an offered action, whole (up to `CHAT_ACTION_MAX_BYTES`, e.g. an edited table); `null` for a plain message. |
| `chat_extra_data` | The widget's context object, untrusted; `null` when none was sent. |
| `chat_user_id` | The verified customer id on a signed desk; `null` otherwise. |
| `chat_conversation_id` | The conversation's id, as a string: the same on every run of the conversation. |

### Past actions in `chat_history`

An action can be large (an edited table) and the history goes into every later run, up to
`history_window` times. So in `chat_history` a past action keeps only `type`, `action` and
`text`; its `params`, `tables` and any other key went to the run it started, as that run's
`action` variable, and nowhere else. A flow that needs an earlier table must keep it itself
(for example in a persistent variable).

## End node outputs

Read from the end node's result. The `output_map` must contain `reply`.

| Output | Meaning |
|---|---|
| `reply` | The bot's answer, a non-empty string. Missing or blank: the visitor sees "The flow finished without a reply." |
| `actions` | Optional list of actions the widget offers with the reply. |
| `request_human` | Optional; `true` hands the conversation to a person, if the desk allows hand-offs. |
