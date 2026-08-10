"""Removes injected secret values from a completed execution's output.

The inbound half of secret delivery keeps plaintext out of generated source, out of
graph_schema, and out of logs. This is the outbound half: the sandbox is the last
point that holds both the plaintext values and the process's output, so scrubbing
here covers every downstream consumer -- PythonCodeResult, GraphSessionMessage, the
SSE stream, the tool observation handed to the LLM, and both container logs -- with
no change in Django or crew.

Scope: accidental disclosure by an author who is already permitted to read the
secret. A determined author can still exfiltrate by encoding or chunking the value,
or by sending it out over the network. This is a safety net, not a boundary.
"""

import json

# One fixed marker rather than one naming each secret: the name would then travel
# into stdout, the SSE stream, and the tool observation handed to the LLM, and none
# of those need it to understand that something was withheld.
MASK = "[REDACTED]"


def _literals(*, secrets: dict[str, str]) -> list[str]:
    """Every form a secret value can appear in, longest first.

    Longest first is load-bearing, not tidiness: when one value is a substring of
    another, replacing the shorter one first would leave the rest of the longer value
    sitting in the output next to the mask.
    """
    literals: set[str] = set()
    for value in secrets.values():
        if not value:
            continue
        literals.add(value)
        literals.add(json.dumps(value)[1:-1])
    return sorted(literals, key=len, reverse=True)


def scrub(*, text: str | None, secrets: dict[str, str]) -> str | None:
    """`text` with every injected secret value replaced by MASK."""
    if not text or not secrets:
        return text

    for literal in _literals(secrets=secrets):
        text = text.replace(literal, MASK)
    return text
