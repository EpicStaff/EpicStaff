# Secrets in Sandboxed Python

How a credential reaches user code inside the `sandbox` container, and how it is kept out of
that code's output on the way back. Covers `get_secret()`, environment-based delivery, the
runtime allow-list, and the output scrubber gated by `SANDBOX_MASK_SECRET`.

For storage, encryption and the resolver see
[DEV_secrets_backend_guide.md](DEV_secrets_backend_guide.md).

---

## 1. The trip through Redis

Three channels, one per hop. Nothing polls for the wrong thing; each service listens only on
the channel that is its job.

| Channel | Direction | Carries |
|---|---|---|
| `sessions:schema` | django_app → crew | the whole resolved graph, once per session |
| `code_exec_tasks` | crew (or django_app, for a Test-mode run) → sandbox | one execution task, including its secrets |
| `code_results` | sandbox → whoever asked | stdout / stderr / result, already scrubbed |

**Step 1 — the allow-list gate, before anything is published.**
`session_manager_service.run_session` calls
`secret_declaration_validator.violations(graph_id=...)` and raises `UndeclaredSecretError`
inside its `try` block if any node reads a secret it did not declare. The session is marked
`ERROR` and **nothing is published** — no partial run, no secret delivered.

**Step 2 — django_app resolves and publishes.** `redis_service.publish_session_data`
deep-copies, fills plaintext into the copy, and publishes that. The original — the one saved
to `Session.graph_schema` — keeps only carrier ids, which are `Field(exclude=True)` and so
never serialize.

**Step 3 — crew is a courier, not a decryptor.** `crew` has no `SECRET_KEY`. The
`PythonCodeData` it builds a `PythonNode` from already contains `{name: plaintext}` because
it arrived that way. `run_python_code_service.run_code` forwards it verbatim:

```python
code_task_data = CodeTaskData(
    ...,
    # Already resolved by Django: crew holds no SECRET_KEY and cannot
    # decrypt anything itself.
    secrets=python_code_data.secrets,
)
```

It subscribes to `code_results` *before* publishing, then waits for a matching
`execution_id`.

**Step 4 — the sandbox receives the task.** `sandbox/main.py` parses it into `CodeTaskData`
and **never logs the raw message** — only `code_task_data.log_summary()`, which reports a
secret *count*, not values.

---

## 2. The subprocess boundary

This is the core of the design. `ExecuteCodeHandler` feeds the child process through **two
channels that never cross**:

```
        ┌─────────────────────────────────────┐
        │ wrap_code()  →  temp_code_path.py   │  ON DISK
        │ user code + preamble, NO secrets    │
        └─────────────────────────────────────┘
                          +
        ┌─────────────────────────────────────┐
        │ build_env()  →  env=                │  MEMORY ONLY
        │ EPICSTAFF_SECRETS={"NAME":"value"}  │
        └─────────────────────────────────────┘
                          ↓
        create_subprocess_shell(f"{python} {path}", env=env)
```

Code goes to a file; secrets go to the environment. A credential therefore cannot end up in
a file by accident, which is the whole point.

**`build_env()`** copies `os.environ` and adds one variable:

```python
if secrets:
    # One JSON variable rather than one per secret: Secret.name is a
    # free-form CharField and may contain spaces, so per-name variables
    # would need mangling.
    env["EPICSTAFF_SECRETS"] = json.dumps(secrets)
```

It returns `None` when there is nothing to configure, which means "inherit the parent
environment" — the pre-existing default.

**`wrap_code()`** puts `from epicstaff_secrets import get_secret` in the preamble, so node
code calls `get_secret("NAME")` with no import line, the same way it already uses `DotDict`.
The import sits **inside the `try` block** so a missing library reports through the same
stderr path as any other failure rather than killing the process before the handler can
report it.

---

## 3. `get_secret()`

`src/shared/epicstaff_secrets/secrets.py` — a tiny library installed into every sandbox venv
(registered as a predefined library in `CreateVenvHandler`, so it is always present).

```python
def get_secret(name: str) -> str:
    """Return the plaintext of a secret this node declared."""
    available = _load()
    if name not in available:
        declared = ", ".join(sorted(available)) or "none"
        raise SecretNotAvailableError(
            f"Secret '{name}' was not declared for this node. "
            f"Declared secrets: {declared}. "
            f"Add it to this node's secrets to make it readable."
        )
    return available[name]
```

Four deliberate choices:

- **No `default=` parameter.** A silently-`None` credential fails later and far more
  confusingly than an immediate exception.
- **`SecretNotAvailableError(RuntimeError)`, not `KeyError`.** The sandbox wrapper prints
  `str(e)` to stderr, and `KeyError.__str__` wraps its message in quotes.
- **The error lists what *was* declared**, so the fix is obvious from the message alone.
- **The payload is parsed once and cached** in a module dict. `clear_cache()` exists for
  tests; a real execution is a fresh process, so the cache never goes stale in production.

Because delivery is by name and the injected dict contains **only declared secrets**, an
undeclared name cannot be read even if the allow-list gate were somehow bypassed. Defence in
depth: the gate stops the session, and the injection stops the read.

---

## 4. Output masking

Even with everything above, one gap remained: nothing stopped code from leaking a secret it
was *legitimately given*. `print(get_secret("K"))` is the obvious case; an uncaught
exception whose message echoes a bad auth header is the one people actually hit.

That output reaches six consumers — `PythonCodeResult`, `GraphSessionMessage`, the SSE
stream, the tool observation handed to the LLM, and both containers' logs — all fed by three
things: `stdout`, `stderr`, and the return value. So the filter sits at the one point that
holds both the plaintext and the raw output, and all six get clean data with no change
anywhere else.

`ExecuteCodeHandler.handle` builds the set of values to mask once, before the process starts,
and scrubs every stream with it right after `communicate()`:

```python
# User secrets join the masking set only when masking is on; the
# per-execution storage credentials are masked unconditionally.
masking_values = build_masking_values(
    (context.get("secrets") or {}) if masking_enabled() else {},
    {
        "STORAGE_ACCESS_KEY": context.get("temp_storage_access_key"),
        "STORAGE_SECRET_KEY": context.get("temp_storage_secret_key"),
    },
)
...
stderr = scrub(text=stderr, secrets=masking_values)
stdout = scrub(text=stdout, secrets=masking_values)

# Logged after scrubbing, so the container log never holds a value the
# response withheld.
if stderr:
    logger.info("Error: {}", stderr)
```

Because the set is resolved once for the whole result, stdout, stderr and `result_data`
cannot disagree about whether this run was masked. The timeout path reuses the same set.

The result file gets the same treatment, assigned *into* `result_data` rather than over it,
so if scrubbing ever raised, the swallowing `except` leaves `result_data` as `None` instead
of returning the raw value.

### 4.1 `secret_scrubber.py`

| Behavior | Why |
|---|---|
| One fixed marker `MASK = "[REDACTED]"` | A per-secret mask would carry the secret's **name** into stdout, the SSE stream and the LLM's observation. None of them need it to understand something was withheld. |
| **No minimum length** — a 1-character secret is masked | Garbling nearby output is loud and self-correcting; leaking is silent and permanent. `test_a_short_value_masks_incidental_matches` pins the accepted cost. |
| Empty values are the one exclusion | `str.replace("")` matches between every character, so an empty literal would replace the entire output with masks. Not a length policy. |
| Both the raw value **and** its JSON-escaped form are matched | `result_data` is the return value under `json.dumps`, so a value containing a quote, backslash or non-ASCII character appears there only escaped. |
| Literals sorted **longest first** | If one value is a substring of another and the shorter is replaced first, the longer value's tail is left sitting beside the mask. |
| One compiled regex, one pass | The first version called `str.replace` per literal, which rescans and re-copies the whole text for every secret. Every literal goes through `re.escape` — a value like `sk-live.*x` must match as plain text. |
| `scrub()` is unconditional | The `SANDBOX_MASK_SECRET` check lives at the call site (`masking_enabled()` deciding whether user secrets join the masking set), so the flag is read in exactly one visible place. A caller that forgets it over-masks, which is the harmless direction. |

### 4.2 `SANDBOX_MASK_SECRET`

A required variable on the `sandbox` service. Compose passes it through with no default, and
`:?` aborts on an unset **or empty** value, so an `.env` that lacks it or leaves it blank fails
at `docker compose up`:

```yaml
# src/docker-compose.yaml
sandbox:
  environment:
    SANDBOX_MASK_SECRET: ${SANDBOX_MASK_SECRET:?}
```

Declared in `src/env.yaml` (default `true` for production, `false` for development) and
generated into `src/.env` / `src/.env.example` — **edit `env.yaml` and run
`python scripts/envtool.py`** (`--dev` for development defaults), never the generated files.

`src/sandbox/settings.py` reads it once at import time:

```python
MASK_SECRET = env.bool("SANDBOX_MASK_SECRET")
```

`secret_scrubber.masking_enabled()` returns `settings.MASK_SECRET`.

`Env.bool` (`src/shared/envtools.py`) is **strict**, for this flag and every other one. The
value is compared case-insensitively after stripping whitespace, and anything outside the two
accepted lists stops the sandbox at startup with a `ValueError` naming the variable:

| Value | Masking | At startup |
|---|---|---|
| `false`, `0`, `no`, `off`, `n`, `f` | **off** | `warning`: masking is OFF |
| `true`, `1`, `yes`, `on`, `y`, `t` | on | `info`: masking is ON |
| anything else — a typo (`flase`, `ture`), `enabled`, `none` | — | the sandbox does not start: `ValueError` |
| empty — reachable only outside compose (a local run reading `src/.env`), since `:?` rejects an empty value | — | the sandbox does not start: `ValueError` |
| unset | — | the sandbox does not start: `EnvironmentNotFoundError` (under compose, `docker compose up` fails first) |

So a misspelled value can never switch masking off: `SANDBOX_MASK_SECRET=flase` fails startup
instead of reading as False. `none` is no exception — other `Env` readers turn it into `None`,
but `Env.bool` rejects it, because a `None` flag is falsy. Only an explicit false disables
masking.

`SANDBOX_REQUIRE_ISOLATION` is read the same way, into `settings.REQUIRE_ISOLATION`, with no
in-code default: unset or malformed fails startup like every other sandbox flag.

The sandbox announces the setting once at startup (`main.log_secret_masking_state`, called
from `main.init`), at `warning` level when masking is off, so disabling it leaves a trace in
the logs rather than being inferred from output that quietly stopped being redacted.

> **Setting it false is a development affordance only.** Plaintext user secrets then reach
> execution results, the SSE stream, the LLM's tool observation, persisted
> `PythonCodeResult` rows and both containers' logs. The per-execution storage credentials
> stay masked either way.

### 4.3 What masking does not do

Scope is **accidental disclosure by an author who is already permitted to read the secret**.
A determined author can still exfiltrate by encoding the value, chunking it, or sending it
over the network. Blocking that needs network egress controls, which is separate work.

This is documented in the module docstring too, so nobody mistakes the scrubber for a
boundary. It is a safety net.

---

## 5. Running the tests

The sandbox suites are not under `src/django_app` and need their own invocation:

```bash
make sandbox-tests ARGS="-q"   # from the repo root
```

Two tests in `tests/chain_tests/test_dynamic_venv_executor_chain.py` are Docker-only and
always fail on the host — that is the expected baseline, not a regression.

| File | Covers |
|---|---|
| `tests/chain_tests/test_execute_code_handler_env.py` | `build_env`, the disk-leak guard, `get_secret` end to end, output masking through the real handler, and the `SANDBOX_MASK_SECRET` switch |
| `tests/chain_tests/test_secret_scrubber.py` | mask behavior, JSON-escaped forms, overlapping values, regex metacharacters |
| `tests/chain_tests/test_security_flag_settings.py` | `SANDBOX_MASK_SECRET` and `SANDBOX_REQUIRE_ISOLATION` parsed through the real settings module: explicit true and false values, and a typo, empty, `none` or unset value failing startup |

The full value table of `Env.bool` is in
`src/django_app/tests/settings_tests/test_env_bool.py`, next to the other `Env` tests.

The switch is tested at the handler level rather than through `scrub()`, because `scrub()` no
longer consults the flag — testing it there would prove nothing.
