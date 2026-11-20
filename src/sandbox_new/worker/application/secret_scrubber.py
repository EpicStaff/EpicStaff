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

Masking of the job's user secrets is gated by the SANDBOX_MASK_SECRET environment
variable (default on), parsed into settings.MASK_SECRET and handed to
ExecutionOrchestrator. Only an explicit false value turns it off; a malformed one
fails startup. When it is false the orchestrator skips the user secrets, so
debugging can see real values -- and those plaintext credentials then reach every
consumer listed above, including persisted rows and container logs. It is a
development affordance, not something to carry into an environment holding real
credentials. The flag does not cover values a pipeline step registers through
ExecutionContext.mask_always() -- the per-run storage credentials -- which the
author never chose to see and which are masked whatever the flag says. scrub()
itself always masks unconditionally.

The orchestrator runs scrub() on the way out rather than a pipeline step, so a
step that fails after the child's output is captured cannot bypass it.
"""

import json
import re
from collections.abc import Collection

# One fixed marker rather than one naming each secret: the name would then travel
# into stdout, the SSE stream, and the tool observation handed to the LLM, and none
# of those need it to understand that something was withheld.
MASK = "[REDACTED]"


def _pattern(*, values: Collection[str]) -> re.Pattern | None:
    """One compiled pattern matching every form every secret value can appear in.

    Only an EMPTY value is skipped here -- there is no minimum length. A
    one-character secret masks every occurrence of that character in the
    output, including incidental, unrelated matches. This is intentional:
    garbling output is a loud, self-correcting symptom, while leaking a value
    is silent and permanent, so the trade is accepted rather than bounded. The
    fix for a short-value collision is not to store something like "1" as a
    credential, not to add a length threshold here.
    """
    literals: set[str] = set()
    for value in values:
        if not value:
            continue
        literals.add(value)
        literals.add(json.dumps(value)[1:-1])

    if not literals:
        return None

    ordered = sorted(literals, key=len, reverse=True)
    return re.compile("|".join(re.escape(literal) for literal in ordered))


def scrub(*, text: str | None, values: Collection[str]) -> str | None:
    """`text` with every given secret value replaced by MASK, in one pass.

    Takes values, not a name -> value mapping: the names play no part in masking,
    and merging two mappings by name drops whichever value loses the key collision.
    """
    if not text:
        return text

    pattern = _pattern(values=values)
    if pattern is None:
        return text
    return pattern.sub(MASK, text)
