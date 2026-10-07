# Chat Admin "Format history" node: renders the stored conversation as plain text
# for the answering task's prompt. The task would otherwise see the record as a
# Python dict, or "None" for a new conversation.

# The most recent messages only, so a long conversation does not crowd the prompt.
MAX_HISTORY_MESSAGES = 20
NO_HISTORY = "(This is the start of the conversation.)"
ROLE_LABELS = {"user": "User", "assistant": "Assistant"}


def main(conversation):
    messages = conversation.get("messages") if isinstance(conversation, dict) else None
    lines = [
        f"{ROLE_LABELS.get(message.get('role'), 'User')}: {message.get('content') or ''}"
        for message in (messages or [])[-MAX_HISTORY_MESSAGES:]
        if isinstance(message, dict)
    ]
    return "\n\n".join(lines) or NO_HISTORY
