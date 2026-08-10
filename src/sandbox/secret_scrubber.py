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
import re

# One fixed marker rather than one naming each secret: the name would then travel
# into stdout, the SSE stream, and the tool observation handed to the LLM, and none
# of those need it to understand that something was withheld.
MASK = "[REDACTED]"


def _pattern(*, secrets: dict[str, str]) -> re.Pattern | None:
    """One compiled pattern matching every form every secret value can appear in."""
    literals: set[str] = set()
    for value in secrets.values():
        if not value:
            continue
        literals.add(value)
        literals.add(json.dumps(value)[1:-1])

    if not literals:
        return None

    ordered = sorted(literals, key=len, reverse=True)
    return re.compile("|".join(re.escape(literal) for literal in ordered))


def scrub(*, text: str | None, secrets: dict[str, str]) -> str | None:
    """`text` with every injected secret value replaced by MASK, in one pass."""
    if not text or not secrets:
        return text

    pattern = _pattern(secrets=secrets)
    if pattern is None:
        return text
    return pattern.sub(MASK, text)
