# Secrets Backend Developer Guide

Consolidated reference for how EpicStaff stores, resolves and protects credentials, and —
most importantly — **what you must do when you add a field, a node, or a service that
touches a secret**. Everything described here is actual runtime behavior.

Related focused docs: [secrets_endpoints.md](secrets_endpoints.md),
[sandbox_secrets.md](sandbox_secrets.md), [secret_usage.md](secret_usage.md).

---

## 1. Mental model

A credential passes through four stages. Each is a separate defence, and each is the
*only* place its job is done:

```
┌────────────────────────────────────────────────────────────────────────┐
│ 1. AT REST        Fernet encryptedtext in Secret.value                 │
│    SecretEncryption is the only encrypt/decrypt implementation         │
│    Key derived from SECRET_KEY via HKDF — django_app holds it alone    │
├────────────────────────────────────────────────────────────────────────┤
│ 2. REFERENCED     Everything points at a Secret by FK or by name       │
│    No model, payload or API body carries plaintext                     │
├────────────────────────────────────────────────────────────────────────┤
│ 3. RESOLVED       SecretResolver turns a reference into plaintext as   │
│    LATE as possible — on a deep copy, never on the persisted object    │
├────────────────────────────────────────────────────────────────────────┤
│ 4. USED           Delivered to the consumer, then scrubbed on the way  │
│    back out (sandbox stdout/stderr/result → [REDACTED])                │
└────────────────────────────────────────────────────────────────────────┘
```

Four invariants shape everything. If a change breaks one of these, it is wrong even if the
tests pass:

- **django_app is the only decryption authority.** `SECRET_KEY` is set on the `django_app`
  service only — not in `x-common-env`. `crew`, `sandbox`, `manager` and `realtime` cannot
  decrypt anything; they receive already-resolved plaintext or nothing.
- **Resolution happens on a copy.** `resolve_payload()` deep-copies before filling, because
  the caller's object is what gets persisted to `Session.graph_schema`. Resolving in place
  would write plaintext into the database.
- **A Secret is immutable.** Create and delete only. Rotating a credential means creating a
  new `Secret` and repointing references. `value` is `editable=False` and there is no update
  endpoint. Several design decisions follow from this — see §7.
- **Secrets are org-scoped, and the name is the stable key.** `UniqueConstraint(org, name)`.
  Every resolution path filters by org; a name that exists only in another org is treated as
  missing, never borrowed.

---

## 2. Data model

| Model | Table | Purpose |
|---|---|---|
| `Secret` | `tables_secret` | `OrgScopedModel` + timestamps + metadata. `name` (CharField 128), `value` (CharField 12000, `editable=False`, holds Fernet encryptedtext), `tail` (CharField 4, `editable=False`). |

Constraints (`tables/models/secret_models.py`):

```python
UniqueConstraint(fields=["org", "name"], name="unique_secret_name_per_org")
CheckConstraint(condition=~Q(value=""), name="secret_value_not_empty")
```

`tail` is the last 4 characters of the **plaintext**, stored so the UI can show
`****...ab12` without decrypting. Values shorter than 9 characters get `tail=""` and are
fully masked — a 6-character secret would otherwise be two-thirds disclosed by its own tail.

### 2.1 Who references a Secret

Two reference styles, and the distinction matters throughout the codebase:

**FK sites** — the secret is *chosen* by reference. One nullable FK, `on_delete=SET_NULL`:

| Model | Field |
|---|---|
| `LLMConfig` | `api_key_secret` |
| `EmbeddingConfig` | `api_key_secret` |
| `RealtimeConfig` | `api_key_secret` |
| `RealtimeTranscriptionConfig` | `api_key_secret` |
| `McpTool` | `auth_secret` |
| `TelegramTriggerNode` | `telegram_bot_api_key_secret` |

**Declaration sites** — `PythonCode.secrets` is an M2M to `Secret`, and it **is the
allow-list**: it says which secrets that code may read at runtime. Six places own a
`PythonCode` (`tables/services/secrets/python_code_sites.py`, `PYTHON_CODE_SITES`):

| Model | Field | Node type |
|---|---|---|
| `PythonNode` | `python_code` | `python` |
| `WebhookTriggerNode` | `python_code` | `webhook-trigger` |
| `ClassificationDecisionTableNode` | `pre_python_code` | `classification-decision-table` |
| `ClassificationDecisionTableNode` | `post_python_code` | `classification-decision-table` |
| `ConditionalEdge` | `python_code` | `edge` |
| `PythonCodeTool` | `python_code` | — (org-owned, not a flow node) |

`GRAPH_PYTHON_CODE_SITES` is the first five — the ones reachable from a graph id.
`PythonCodeTool` is org-owned, so a per-graph walk cannot find it and it is gated separately
(§6.2).

> **`PYTHON_CODE_SITES` is shared deliberately.** The declaration validator (§6.2) and the
> usage sources ([secret_usage.md](secret_usage.md) §1) both read it, so the two features
> cannot drift on which sites exist. If you add a seventh site, add it there and both pick it
> up — and the canary test
> `test_graph_python_code_sites_still_holds_exactly_the_five_known_sites`
> (`tests/graph_versioning_tests/test_secret_declarations.py`) will fail until you also teach
> versioning about it.

### 2.2 Not migrated: ngrok and Twilio

`NgrokWebhookConfig.auth_token` and `VoiceSettings.twilio_account_sid` /
`twilio_auth_token` still store **plaintext** and are deliberately outside this system.
Both are platform-wide rather than tenant data: `NgrokWebhookConfig` is a plain model with
no org FK (globally unique `name` and `auth_token`) and `VoiceSettings` is a singleton
(`pk=1`). `Secret` is org-scoped by definition, so there is no org to attach them to.
Both are superadmin-only to read or write and neither reaches sandboxed user code.

The open gap is encryption at rest: unlike everything else here, these two are readable in
a DB dump. Migrating them needs either a platform-level secret scope or an owning org.

---

## 3. Encryption layer

`tables/services/secrets/encryption.py` — `SecretEncryption`, exported as the singleton
`secret_encryption`. **The only place a secret's text is encrypted or decrypted.**

```python
derived = HKDF(algorithm=SHA256(), length=32, salt=None, info=b"epicstaff.secrets.v1")
              .derive(settings.SECRET_KEY.encode())
Fernet(base64.urlsafe_b64encode(derived))
```

- **HKDF, not `SECRET_KEY` directly.** Fernet needs exactly 32 url-safe-base64 bytes;
  `SECRET_KEY` is an arbitrary string. Deriving also means this key is domain-separated
  from every other use of `SECRET_KEY` (sessions, signing) via `info`.
- `salt=None` is required, not an oversight: the derivation must be reproducible across
  processes and restarts, so there is nowhere to store a random salt.
- `MAX_TEXT_BYTES = 8192`, checked on encrypt → `SecretTooLargeError` (400). This sizes
  `Secret.value`'s `max_length=12000`, which must hold the *encryptedtext*, not the input.
- `encrypt()` returns a `SealedValue` with a `write_to(secret)` method that assigns
  `value` and `tail` together — so no call site can set one and forget the other.
- `decrypt()` maps `InvalidToken` → `SecretDecryptionError` (500). That is an
  infrastructure fault (wrong key, tampered row), never a user error.

**Rotating `SECRET_KEY` makes every stored secret undecryptable.** There is no key-version
column and no re-encryption command. Treat `SECRET_KEY` as permanent for any deployment
holding secrets.

---

## 4. Resolution layer

`tables/services/secrets/secret_resolver.py` — `SecretResolver`, singleton
`secret_resolver`. The only consumer of `SecretEncryption.decrypt`.

Three entry points:

| Method | Input | Returns |
|---|---|---|
| `resolve(secret_id=, org_id=, context="")` | one id (or `None`) | plaintext, or `None` |
| `resolve_named(names=, org_id=, context="")` | list of names | `{name: plaintext}` |
| `resolve_payload(payload=, org_id=)` | a pydantic model | a **deep copy**, plaintext filled in |

`context` is a human label (`"LLMConfig.api_key"`) used only in error messages.
`_message()` never interpolates the value — errors carry the id and a reason, nothing more.

### 4.1 `resolve_payload` and the two carrier conventions

`resolve_payload` walks the pydantic tree (models, lists, dicts) and fills plaintext slots
from their carriers. Two conventions, both enforced structurally:

**`<field>_secret_id` → `<field>`.** A field ending in `_secret_id` is the carrier; the
same name without that suffix is the plaintext slot. A carrier with no matching slot raises
`SecretResolutionError` rather than silently doing nothing.

**`secret_names` → `secrets`.** The reserved pair for declaration sites: a list of names in,
a `{name: plaintext}` dict out. (No collision with the suffix rule —
`"secret_names".endswith("_secret_id")` is `False`.)

The carrier fields are declared `Field(exclude=True)` on the pydantic models, so
`model_dump()` omits them. That is what keeps **both** plaintext *and* secret ids out of
`Session.graph_schema`, which is built from the unresolved original:

```python
# tables/services/redis_service.py
def publish_session_data(self, *, session_data: SessionData, org_id: int) -> int:
    # Resolve here, not upstream: the caller's object is what gets persisted
    # to Session.graph_schema, so plaintext must exist only on this copy.
    resolved = secret_resolver.resolve_payload(payload=session_data, org_id=org_id)
    return self.redis_client.publish("sessions:schema", resolved.model_dump_json())
```

`publish_realtime_agent_chat` does the same, and deliberately logs the **unresolved**
object — logging `resolved` would write credentials into the log stream.

The regression guard for all of this is
`tests/services_tests/test_graph_schema_no_plaintext.py`.

### 4.2 Errors

| Condition | Exception | HTTP |
|---|---|---|
| Non-null reference, row missing or wrong org | `SecretResolutionError` | 500 |
| Row present, value will not decrypt | `SecretResolutionError` | 500 |
| Value over 8192 bytes on create | `SecretTooLargeError` | 400 |
| Code reads an undeclared secret | `UndeclaredSecretError` | 400 |

A **null** reference is not an error — it means no credential is configured, which is
legitimate for providers that need none.

`resolve_named` is the exception to fail-loud: a name with no matching row is **omitted**,
not raised. The name comes from a string literal in user code, so a typo must not stop the
whole flow from starting; the sandbox raises at the `get_secret()` call instead, where the
error can name what *was* injected. Still fail-closed — no credential is exposed either way.

---

## 5. Writing secrets

`tables/services/secrets/secret_service.py` is deliberately tiny:

```python
class SecretService:
    def create(self, *, text: str, **fields) -> Secret:
        secret = Secret(**fields)
        secret_encryption.encrypt(text=text).write_to(secret)
        secret.save()
        return secret
```

There is **no `update`**. It was removed on purpose: a secret whose value can change makes
"which credential did that run use?" unanswerable, and the tail/value pair invites drift.

`SecretSerializer` (`tables/serializers/model_serializers/secret_serializers.py`) takes
`value` as `write_only` and required, and calls this service in `create()`. Reads return
`tail`, never `value`.

---

## 6. The allow-list

`PythonCode.secrets` is not documentation — it is enforced, in two places, for two different
reasons.

### 6.1 Save-time validation (convenience)

`PythonCodeSerializer.validate` (`tables/serializers/model_serializers/python_serializers.py`)
parses the code and rejects a save whose code reads an undeclared name, with a message
listing what is selected and what is available in the org:

```
Code calls get_secret("STRIPE_KEY") but that secret is not selected for this node.
Selected: none. Available in this organization: STRIPE_KEY, SLACK_TOKEN.
Select them under Secrets, or remove the calls.
```

This is a good error at the right moment, but it is **bypassable** — import, copy services,
management commands and direct DB writes all reach `PythonCode` without it.

### 6.2 Session-start enforcement (the real boundary)

`tables/services/secrets/declaration_validator.py`. This is the gate that actually holds:

```python
# tables/services/session_manager_service.py, inside run_session's try block
violations = secret_declaration_validator.violations(graph_id=graph_id)
if violations:
    raise UndeclaredSecretError("Session aborted: " + " ".join(v.describe() for v in violations))
```

- Walks `GRAPH_PYTHON_CODE_SITES`, so every graph-owned code site is covered by
  construction.
- Reports **every** violation at once, so one run tells the user everything to fix.
- Raised *inside* the try block so the existing handler marks the session `ERROR`, records
  the reason, and **publishes nothing** — no partial run, no secret delivered.
- `PythonCodeTool` is org-owned and unreachable from a graph id, so it is gated in the
  converter instead via `assert_tool_secrets_declared(tool_name=, code=, declared=)`, which
  already receives exactly the tools the session will use.

### 6.3 Detection is AST-based

`parse_code.parse_secret_names(code=)` walks the AST and collects the string literal from
`get_secret("NAME")` calls, matching both `get_secret(...)` (`ast.Name`) and
`module.get_secret(...)` (`ast.Attribute`).

Consequences worth knowing:

- A `get_secret` in a comment or an unrelated string does **not** count.
- A non-literal argument (`get_secret(name_var)`) is **invisible** to the parser, so it
  cannot be declared and will fail at runtime with `SecretNotAvailableError`. Only literals
  are supported, by design — a computed name cannot be checked ahead of time.
- Unparseable code returns an empty set rather than raising, so a syntax error surfaces as
  a syntax error at execution, not as a confusing secrets error at save.

---

## 7. Consequences of immutability

`Secret` being create-and-delete-only is load-bearing in places that are easy to miss:

- **Rotation is delete + recreate**, usually under the same name. Anything that remembers a
  secret by **id** breaks on every rotation; anything that remembers it by **name** survives.
  This is why graph version snapshots record declared secret *names*
  ([secret_usage.md](secret_usage.md) covers the versioning fix) and why `resolve_named` is
  name-keyed.
- **Quickstart reuses** an existing secret rather than creating a duplicate per call, and
  `api_key` became optional there. Without reuse, every quickstart would leave another
  identical row behind, and `UniqueConstraint(org, name)` would start rejecting them.
- **Deleting a secret is silent by design at the DB layer** — every FK is
  `on_delete=SET_NULL` and the M2M rows just disappear. Nothing breaks loudly; a flow simply
  stops having a credential. That is precisely why the deletion-safety endpoint exists
  ([secret_usage.md](secret_usage.md)) — the UI has to tell the user what they are about to
  break, because the database will not.

---

## 8. What you must do

### 8.1 Adding a new credential field to a model

1. Add a nullable FK to `Secret` with `on_delete=SET_NULL`. Never a `CharField`.
2. **Exclude it from every import/export serializer.** Secret PKs are meaningless in
   another org, and `tests/import_export_tests/test_secret_export_exclusion.py` asserts no
   serializer exposes one. Add the new field name to that test's `FORBIDDEN_FIELD_NAMES`.
3. If the field must be writable via the API, use
   `OrgScopedPrimaryKeyRelatedField(queryset=Secret.objects.all())` — a plain
   `PrimaryKeyRelatedField` validates against the unfiltered table and is a cross-org hole.
   That field **requires `context={"request": request}`**; without it it denies every pk.
4. If the value must reach another service, add the pydantic carrier pair
   (`<field>_secret_id` with `Field(exclude=True)`, plus the plaintext `<field>` slot) and
   let `resolve_payload` fill it. Do not decrypt at the call site.
5. Register a usage source so deletion safety still tells the truth — see
   [secret_usage.md](secret_usage.md) §"Adding a source".
6. If the model is a graph child that versioning wipes and recreates, teach
   `GraphVersioningManager.collect_secret_declarations` / `restore_secret_declarations`
   about it, or a version restore will silently drop the reference.

### 8.2 Adding a new place user code can run

1. Add a `PythonCodeSite` to `PYTHON_CODE_SITES`. The declaration validator and the usage
   sources both pick it up automatically.
2. Decide whether it is graph-owned (goes in `GRAPH_PYTHON_CODE_SITES`, gated at session
   start) or org-owned (needs its own `assert_tool_secrets_declared` call at the point the
   session assembles it).
3. Deliver values through the child process **environment**, never by interpolating them
   into generated source — see [sandbox_secrets.md](sandbox_secrets.md).
4. Scrub the output before anything downstream reads it.

### 8.3 Things that will bite you

- **Never log a resolved payload.** Log the unresolved one. `redis_service.py` shows the
  pattern.
- **Never put a resolved value in `global_kwargs`.** It is repr-interpolated into generated
  source that gets written to disk, and it is nested inside `GraphData`, which becomes
  `Session.graph_schema`. Two leaks in one.
- **Never resolve in place.** `resolve_payload` copies for a reason.
- **Do not add a `default=` to `get_secret()`.** A silently-`None` credential fails later
  and more confusingly than an immediate exception.

---

## 9. Test map

All paths are relative to `src/django_app/` unless stated otherwise.

| Area | Tests |
|---|---|
| Encryption, tail, size limit | `tests/services_tests/test_secret_encryption.py` |
| Resolver: all three entry points, carriers | `tests/services_tests/test_secret_resolver.py`, `test_payload_secret_fields.py` |
| `secret_service` is the only writer | `tests/services_tests/test_secret_service_call_sites.py` |
| CRUD API, permissions | `tests/api_tests/test_secret_api.py` |
| Cross-org reference isolation | `tests/api_tests/test_secret_selection_cross_org.py`, `test_init_realtime_cross_org_secret.py`, `tests/services_tests/test_default_config_cross_org_secret.py` |
| No plaintext or ids in `graph_schema` | `tests/services_tests/test_graph_schema_no_plaintext.py` |
| Import/export exclusion guard | `tests/import_export_tests/test_secret_export_exclusion.py` |
| Copy services preserve the FK | `tests/services_tests/test_copy_services_secret_fk.py` |
| Allow-list: session start and save time | `tests/services_tests/test_secret_declaration_validator.py`, `tests/api_tests/test_secret_declaration_api.py` |
| Allow-list for org-owned tools | `tests/services_tests/test_tool_secret_declaration.py` |
| What actually gets injected | `tests/services_tests/test_declared_secret_injection.py`, `test_run_python_code_secrets.py`, `test_converter_emits_secret_ids.py` |
| Quickstart reuse | `tests/api_tests/test_quickstart_secret_reuse.py` |
| Telegram FK field | `tests/api_tests/test_telegram_trigger_secret_field.py` |
| Usage sources and payload | `tests/services_tests/test_secret_usage_sources.py`, `test_secret_usage_service.py` |
| Usage endpoints, query cost | `tests/api_tests/test_secret_usage_api.py` |
| Version round trip | `tests/graph_versioning_tests/test_secret_declarations.py`, `tests/api_tests/test_graph_version_secret_declarations.py` |
| Sandbox delivery and scrubbing | `src/sandbox/tests/chain_tests/test_execute_code_handler_env.py`, `test_secret_scrubber.py` |

The two sandbox suites live under `src/sandbox`, not `src/django_app`, and need a different
pytest invocation — see [sandbox_secrets.md](sandbox_secrets.md) §"Running the tests".
