# Secrets in Sandboxed Python

How a credential reaches user code inside the `sandbox` container, and how it is kept out of
that code's output on the way back. Covers `get_secret()`, environment-based delivery, the
runtime allow-list, and the output scrubber. `SANDBOX_MASK_SECRET` decides only whether user
secrets are masked; the per-execution storage credentials are masked whatever it says.

For storage, encryption and the resolver see
[DEV_secrets_backend_guide.md](DEV_secrets_backend_guide.md).

> **Which service.** Compose now runs `sandbox_new`; the old `sandbox` service (`src/sandbox`)
> is commented out. §4.1 and §4.3 describe `sandbox_new`. The other sections, and the
> `tests/chain_tests` rows of §5, were written for `src/sandbox` and have not yet been
> re-checked against `sandbox_new`, whose file and function names differ.

---

## 1. The trip through Redis

Four channels, one per hop. Nothing polls for the wrong thing; each service listens only on
the channel that is its job.

| Channel | Direction | Carries |
|---|---|---|
| `sessions:schema` | django_app → crew | the whole resolved graph, once per session |
| `code_exec_tasks` | crew (or django_app, for a Test-mode run) → sandbox | one execution task, including its secrets |
| `code_results` | sandbox → whoever asked | stdout / stderr / result, already scrubbed |
| `code_results:crew` | sandbox → crew (tasks sent with `reply_to_crew_channel`) | the same result, read only by crew |

**Step 1 — the allow-list gate, before anything is published.**
`session_manager_service.run_session` calls
`secret_declaration_validator.violations(graph_id=...)` and raises `UndeclaredSecretError`
inside its `try` block if any node reads a secret it did not declare. The session is marked
`ERROR` and **nothing is published** — no partial run, no secret delivered.

**Step 2 — django_app resolves and publishes.** `redis_service.publish_session_data`
deep-copies, fills plaintext into the copy, and publishes that. The caller's original stays
unresolved and keeps only carrier ids, which are `Field(exclude=True)` and so never
serialize.

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

It sets `reply_to_crew_channel`, registers the `execution_id` with its one process-wide
subscription to `code_results:crew` *before* publishing, then waits for that result.

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

### 4.1 `sandbox_new`: `ExecutionOrchestrator` and `secret_scrubber.py`

The code above is `src/sandbox`. In `sandbox_new` the scrub runs once, in
`ExecutionOrchestrator._build_result` (`worker/application/orchestrator.py`), not in a
pipeline step, so a step that fails after the child's output is captured cannot skip it.
The masked set is the union of two sources:

```python
# User secrets are masked only when MASK_SECRET is on; values the steps
# registered as always-masked (worker-issued credentials) are masked regardless.
user_secret_values = list((context.job.secrets or {}).values()) if self._mask_secrets else []
masked_values = [*user_secret_values, *context.always_masked]
```

- **User secrets** (`job.secrets`) join only when `MASK_SECRET` is on (§4.3).
- **Values registered through `ExecutionContext.mask_always()`** are always masked.
  `ConfigureStorageStep` registers the per-run `STORAGE_ACCESS_KEY` and `STORAGE_SECRET_KEY`
  in the same place it puts them into the child's env, so a step that hands the child a
  worker-issued value is the step that marks it for masking. The author never chose to see
  these, so the flag does not cover them.

`scrub()` takes `values`, not a name → value dict (`src/sandbox`'s `scrub()` and
`build_masking_values()` still take dicts). The names play no part in masking, and merging two
dicts by name drops whichever value loses the key collision: a user secret named
`STORAGE_SECRET_KEY` would have overwritten the storage credential and left it unmasked.
`values` is a `Collection`, not an `Iterable`, because the orchestrator passes the same
argument to three `scrub()` calls and a generator would be empty from the second one on.

### 4.2 `secret_scrubber.py`

| Behavior | Why |
|---|---|
| One fixed marker `MASK = "[REDACTED]"` | A per-secret mask would carry the secret's **name** into stdout, the SSE stream and the LLM's observation. None of them need it to understand something was withheld. |
| **No minimum length** — a 1-character secret is masked | Garbling nearby output is loud and self-correcting; leaking is silent and permanent. `test_a_short_value_masks_incidental_matches` pins the accepted cost. |
| Empty values are the one exclusion | `str.replace("")` matches between every character, so an empty literal would replace the entire output with masks. Not a length policy. |
| Both the raw value **and** its JSON-escaped form are matched | `result_data` is the return value under `json.dumps`, so a value containing a quote, backslash or non-ASCII character appears there only escaped. |
| Literals sorted **longest first** | If one value is a substring of another and the shorter is replaced first, the longer value's tail is left sitting beside the mask. |
| One compiled regex, one pass | The first version called `str.replace` per literal, which rescans and re-copies the whole text for every secret. Every literal goes through `re.escape` — a value like `sk-live.*x` must match as plain text. |
| `scrub()` is unconditional | The `SANDBOX_MASK_SECRET` check lives at the call site, so the flag is read in exactly one visible place: `masking_enabled()` in `src/sandbox`, and in `sandbox_new` the `self._mask_secrets` check that decides whether user secrets join the masked set in `ExecutionOrchestrator._build_result` (§4.1). A caller that forgets it over-masks, which is the harmless direction. |

### 4.3 `SANDBOX_MASK_SECRET`

A required variable on the `sandbox_new` service (the `sandbox` service is commented out in
compose). Compose passes it through with no default, and `:?` aborts on an unset **or empty**
value, so an `.env` that lacks it or leaves it blank fails at `docker compose up`:

```yaml
# src/docker-compose.yaml
sandbox_new:
  environment:
    SANDBOX_MASK_SECRET: ${SANDBOX_MASK_SECRET:?}
```

Declared in `src/env.yaml` (default `true` for production, `false` for development) and
generated into `src/.env` / `src/.env.example` — **edit `env.yaml` and run
`python scripts/envtool.py`** (`--dev` for development defaults), never the generated files.

`src/sandbox_new/settings.py` reads it once at import time and hands it to
`ExecutionOrchestrator` as `mask_secrets`:

```python
MASK_SECRET = env.bool("SANDBOX_MASK_SECRET", True)
```

`Env.bool` (`foundation.utils.env`, the same rules as `src/shared/envtools.py`) is **strict**,
for this flag and every other one. The value is compared case-insensitively after stripping
whitespace, and anything outside the two accepted lists stops the sandbox at startup with a
`ValueError` naming the variable:

| Value | Masking |
|---|---|
| `false`, `0`, `no`, `off`, `n`, `f` | **off** |
| `true`, `1`, `yes`, `on`, `y`, `t` | on |
| anything else — a typo (`flase`, `ture`), `enabled`, `none` | the sandbox does not start: `ValueError` |
| empty — reachable only outside compose (a local run reading `src/.env`), since `:?` rejects an empty value | the sandbox does not start: `ValueError` |
| unset — reachable only outside compose | on (the in-code default) |

So a misspelled value can never switch masking off: `SANDBOX_MASK_SECRET=flase` fails startup
instead of reading as False. `none` is no exception — other `Env` readers turn it into `None`,
but `Env.bool` rejects it, because a `None` flag is falsy. Only an explicit false disables
masking.

`SANDBOX_BLOCK_NETWORK`, `SANDBOX_REQUIRE_ISOLATION` and `SANDBOX_REQUIRE_SIGNAL_ISOLATION` are
read the same way, each defaulting to the confining value `true`.

`sandbox_new` does not log the masking state at startup, so a disabled scrubber shows only as
output that is no longer redacted.

> **Setting it false is a development affordance only.** Plaintext user secrets then reach
> execution results, the SSE stream, the LLM's tool observation, persisted
> `PythonCodeResult` rows and both containers' logs. The per-execution storage credentials
> stay masked either way.

### 4.4 What masking does not do

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
| `src/sandbox_new/tests/test_settings.py` (`make sandbox_new-tests`) | the four `sandbox_new` security flags parsed through its real settings module: explicit true and false values, a typo, empty or `none` value failing startup, and an unset value reading as true |

The full value table of the shared `Env.bool` (`src/shared/envtools.py`) is in
`src/django_app/tests/settings_tests/test_env_bool.py`, next to the other `Env` tests.
foundation's copy in `foundation.utils.env` follows the same rules; it is pinned only through
`src/sandbox_new/tests/test_settings.py`, so change both together.

The switch is tested at the handler level rather than through `scrub()`, because `scrub()` no
longer consults the flag — testing it there would prove nothing.
