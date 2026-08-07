# Schema Validate Tool
#
# A COOPERATIVE structured-output validator, not an engine-enforced guarantee.
# The agent supplies its own draft output plus a JSON Schema; this tool
# validates and reports PASS/FAIL with per-violation detail. Nothing here
# re-invokes the LLM or loops automatically -- the calling agent's own
# prompt/plan is what drives the "validate -> fix -> validate again" retry
# loop. See tool_data.yaml for the full description shown to the agent.
#
# Never raises: malformed draft JSON, malformed/invalid schema, and any
# unexpected exception are all converted to readable "Error: ..." strings.

import json

import jsonschema
from jsonschema.exceptions import SchemaError

MAX_ERRORS = 25
MAX_MESSAGE_LEN = 300

# Sentinel so we can tell "argument not supplied at all" apart from a literal
# JSON null being passed as the draft output or schema.
_MISSING = object()


def _format_path(path) -> str:
    """Render a jsonschema error path (deque of str/int keys) as e.g. $.items[0].name."""
    if not path:
        return "$"
    parts = ["$"]
    for part in path:
        if isinstance(part, int):
            parts.append(f"[{part}]")
        else:
            parts.append(f".{part}")
    return "".join(parts)


def _format_failure(errors: list, max_attempts) -> str:
    total = len(errors)
    capped = errors[:MAX_ERRORS]

    lines = [
        f"FAIL: output does not match the schema "
        f"({total} violation{'s' if total != 1 else ''})."
    ]
    if max_attempts is not None:
        lines.append(
            f"(max_attempts hint: {max_attempts} -- this tool does not track "
            "attempts itself, track your own retry count)"
        )

    for error in capped:
        path = _format_path(list(error.path))
        message = error.message
        if len(message) > MAX_MESSAGE_LEN:
            message = message[:MAX_MESSAGE_LEN] + "... (truncated)"
        lines.append(f"- {path}: {message}")

    if total > MAX_ERRORS:
        lines.append(f"(showing first {MAX_ERRORS} of {total} violations, truncated)")

    lines.append("Fix the listed field(s) and call this tool again with the corrected output.")
    return "\n".join(lines)


def main(output=_MISSING, schema=_MISSING, max_attempts: int | None = None) -> str:
    """
    Validate a draft structured output against a JSON Schema.

    'output' may be a JSON string (parsed with json.loads) or an
    already-structured JSON value. 'schema' must be a JSON Schema object.
    Returns a PASS confirmation string or a FAIL string listing every
    violation (path + message). Cooperative only: the agent must act on a
    FAIL result and call this tool again -- nothing here enforces a retry.
    """
    try:
        if output is _MISSING:
            return "Error: missing required argument 'output' (the draft output to validate)."

        if schema is _MISSING or schema is None:
            return "Error: missing required argument 'schema' (the JSON Schema to validate against)."

        if isinstance(output, str):
            try:
                parsed_output = json.loads(output)
            except (json.JSONDecodeError, ValueError) as e:
                return f"Error: 'output' is not valid JSON. {e}"
        else:
            parsed_output = output

        if not isinstance(schema, dict):
            return (
                "Error: 'schema' must be a JSON Schema object, got "
                f"{type(schema).__name__}."
            )

        try:
            validator_cls = jsonschema.validators.validator_for(schema)
            validator_cls.check_schema(schema)
        except SchemaError as e:
            return f"Error: 'schema' is not a valid JSON Schema. {_format_path(list(e.path))}: {e.message}"
        except Exception as e:
            return f"Error: 'schema' is not a valid JSON Schema. {e}"

        validator = validator_cls(schema)
        errors = list(validator.iter_errors(parsed_output))

        if not errors:
            confirmation = "PASS: output is valid against the provided schema."
            try:
                confirmation += f" Normalized value: {json.dumps(parsed_output)}"
            except (TypeError, ValueError):
                pass
            return confirmation

        return _format_failure(errors, max_attempts)
    except Exception as e:
        return f"Error: schema validation failed due to an unexpected exception: {e}"
