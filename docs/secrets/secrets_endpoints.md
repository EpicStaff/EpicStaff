# Secrets Endpoints

The HTTP surface for managing credentials: `/api/secrets/` CRUD plus the
deletion-safety usage endpoint. For how values are encrypted, resolved and delivered see
[DEV_secrets_backend_guide.md](DEV_secrets_backend_guide.md); for what the usage payload
means see [secret_usage.md](secret_usage.md).

---

## The viewset

`SecretViewSet` (`tables/views/model_view_sets.py`) is **create / read / delete only**:

```python
class SecretViewSet(
    OrgScopedViewSetMixin,
    mixins.ListModelMixin, mixins.CreateModelMixin,
    mixins.RetrieveModelMixin, mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticated, DenyApiKeyAuth, HasOrgPermission]
    rbac_resource_type = ResourceType.SECRETS
    rbac_action_map = {**DEFAULT_ACTION_MAP, "usage": Permission.READ}
```

Three things to note:

- **No PUT, no PATCH.** A `Secret`'s name and value are immutable; rotating means creating
  a new one and repointing references. This is not an omission to be fixed.
- **`DenyApiKeyAuth`.** These endpoints are JWT-only. An API key cannot enumerate or create
  secrets even if its owner's role would allow it — the same treatment key-management
  endpoints get.
- **`usage` is mapped explicitly.** `HasOrgPermission` default-denies any custom `@action`
  that is not in `rbac_action_map`, so the mapping is required, not decorative.

Because `OrgScopedViewSetMixin` comes first in the bases, the queryset is filtered to the
active org and `org` / `created_by` are stamped on create. The active org comes from the
`X-Organization-Id` header.

### Permissions

`ResourceType.SECRETS` bitmasks as seeded (see
[../rbac/roles_and_permissions.md](../rbac/roles_and_permissions.md)):

| Role | Bitmask | Effect |
|---|---|---|
| Org Admin | 207 (CRUD + use + list) | full management |
| Member | 192 (use + list) | may reference secrets, cannot create or delete |
| Viewer | 192 (use + list) | same as Member |

So a Member can select an existing secret for a node but cannot create or delete one.

---

## `GET /api/secrets/`

Every secret in the active org. Includes `usage_count` per row.

```json
[
  {
    "id": 12,
    "name": "STRIPE_KEY",
    "tail": "ab12",
    "metadata": {},
    "org": 1,
    "created_by": 3,
    "created_at": "2026-08-01T10:00:00Z",
    "updated_at": "2026-08-01T10:00:00Z",
    "usage_count": { "readable": 2, "hidden": 1 }
  }
]
```

`value` is **never** in a response — it is `write_only`. `tail` is the last 4 plaintext
characters, or `""` for values shorter than 9 characters.

`usage_count` is an **object, not an integer**, and it is filtered by the caller's
permissions:

| Key | Meaning |
|---|---|
| `readable` | distinct resources referencing this secret that the caller holds READ on |
| `hidden` | distinct resources referencing it that the caller may **not** see |

`readable + hidden` is the total number of distinct resources referencing the secret, and is
the same for every caller in the org — only the split between the two moves. The field is a
pair because a secret is typically referenced from several resource kinds at once and a
caller may hold `flows:READ` without `llm_configs:READ`, so one number cannot say both how
much is inspectable and how much would break on delete.

Three states the UI has to tell apart:

| Response | Meaning |
|---|---|
| `{"readable": 0, "hidden": 0}` | not referenced anywhere |
| `{"readable": 2, "hidden": 1}` | referenced 3 times; 2 are inspectable |
| `{"readable": 0, "hidden": 1}` | referenced, but by nothing the caller can see — **not** the same as unused |

**Deletion warnings must use `readable + hidden`, never `readable` alone.** Deleting nulls
the reference on *every* referencing resource, including the ones the caller cannot see, so a
warning computed from `readable` would fall silent on exactly the case where it matters most.
What permission filtering hides is *which* resources, never *whether* there are any.

The whole list costs a fixed number of queries regardless of how many secrets the org has —
one prepared count map is computed per request, not per row. See
[secret_usage.md](secret_usage.md) for the counting rules, the readable/hidden split, and why
this is not simply a row count.

## `GET /api/secrets/{id}/`

One secret, same shape as a list row. Another org's secret is a **404**, not a 403 — a 403
would confirm the row exists.

Unlike the list, this computes the count for that one secret only, in a single query,
instead of building the whole org's map to read one key out of it. It reports the same
numbers the list reports for that secret.

## `POST /api/secrets/`

```json
{ "name": "STRIPE_KEY", "value": "sk-live-51H...", "metadata": {} }
```

`value` is required and write-only. The response is the created row (with
`usage_count: {"readable": 0, "hidden": 0}`), and the plaintext is not echoed back.

| Failure | Status | Detail |
|---|---|---|
| Name already used in this org | 400 | `A secret with this name already exists in this organization.` |
| `value` over 8192 bytes | 400 | `secret_too_large` |
| `value` missing or blank | 400 | standard DRF field error |
| Role lacks CREATE on `secrets` | 403 | |
| Authenticated with an API key | 403 | `DenyApiKeyAuth` |

Uniqueness is enforced by `OrgScopedUniqueTogetherValidator` on `["name"]`, which scopes
the check to the active org — a plain `UniqueTogetherValidator` would leak the existence of
another org's identically-named secret.

`usage_count` is read-only: sending it is ignored, not stored or echoed.

## `DELETE /api/secrets/{id}/`

Hard delete. No soft-delete, no `is_active`.

**It always succeeds, and it does not check usage.** Every referencing FK is
`on_delete=SET_NULL` and the `PythonCode.secrets` M2M rows simply disappear, so nothing
raises — an LLM config quietly loses its key, and a Python node that calls
`get_secret("NAME")` starts failing at runtime with `SecretNotAvailableError`.

That is exactly why the usage endpoint exists: the UI is expected to call it first and warn.
The backend deliberately does not block the delete, because "this secret is in use" is a
judgement for the user, not an error.

Computes no usage at all, so it costs nothing beyond the lookup.

## `GET /api/secrets/{id}/usage/`

Every resource in the active org that references this secret **and that the caller holds READ
on**, for the deletion-safety dialog. `Permission.READ` on `secrets` gets you the endpoint;
what it *lists* is then filtered per resource type.

```json
{
  "readable_total": 3,
  "hidden_total": 1,
  "categories": [
    {
      "key": "flows",
      "items": [
        {
          "id": 12,
          "name": "Payments flow",
          "nodes": [
            { "name": "charge_card", "node_type": "python", "code_field": "python_code" }
          ]
        }
      ]
    },
    { "key": "tools", "items": [{ "name": "Stripe refund", "type": "mcp_tool" }] },
    { "key": "llm_configs", "items": [{ "name": "gpt-4o prod", "type": "llm_config" }] }
  ]
}
```

`readable_total` is the number of items actually listed across `categories`; `hidden_total`
counts the referencing resources withheld from it. There is no `total` key — the two
aggregates are the complete set, and a client wanting the unfiltered figure adds them.

An unused secret returns `{"readable_total": 0, "hidden_total": 0, "categories": []}` — a
category is present only when it has items, so the frontend never renders an empty group.

**A category the caller cannot read is omitted exactly like an empty one**, never returned
with an empty `items` array. That is deliberate: this endpoint returns resource *names*, so a
present-but-empty category would disclose which *kind* of resource is hiding the secret. The
consequence is that `{"readable_total": 0, "hidden_total": 2, "categories": []}` and
`{"readable_total": 0, "hidden_total": 0, "categories": []}` differ only in `hidden_total` —
the UI must read that field to tell "used, invisible to you" from "unused."

Field meanings, the `readable_total`-vs-node-count distinction, the `code_field` values, and
how visibility is resolved per source are documented in
[secret_usage.md](secret_usage.md). The response schema and all three examples are also in
Swagger (`tables/swagger_schemas/secret_schemas.py`).

404 for another org's secret, same as retrieve.

---

## Referencing a secret from another endpoint

Secrets are selected by **id**, never by sending a plaintext key. Two shapes:

**Single FK** — the write field is the model field name **plus `_id`**:

| Endpoint | Write field |
| --- | --- |
| `/api/llm-configs/` | `api_key_secret_id` |
| `/api/embedding-configs/` | `api_key_secret_id` |
| `/api/realtime-model-configs/`, `/api/realtime-transcription-model-configs/` | `api_key_secret_id` |
| `/api/openai-realtime-configs/` | `api_key_secret_id`, `transcription_api_key_secret_id` |
| `/api/elevenlabs-realtime-configs/`, `/api/gemini-realtime-configs/` | `api_key_secret_id` |
| `/api/mcp-tools/` | `auth_secret_id` |
| `/api/twilio-channels/` | `auth_token_secret_id` |
| `/api/webhook-triggers/` | `auth_secret_id` (write-only), `ngrok_config.auth_token_secret_id` |
| telegram trigger nodes | `telegram_bot_api_key_secret_id` |

`/api/openai-realtime-configs/` is the only one carrying two — a realtime session can use a
different credential for transcription than for the model itself.

```json
POST /api/llm-configs/
{ "custom_name": "gpt-4o prod", "model": 4, "api_key_secret_id": 12 }
```
**Declaration list** — anything owning a `PythonCode` takes `secret_ids`, the allow-list of
secrets that code may read:

```json
{ "code": "def main(**kwargs):\n    return get_secret(\"STRIPE_KEY\")\n",
  "entrypoint": "main", "libraries": [], "secret_ids": [12] }
```

Both use org-scoped related fields, so **another org's secret id is rejected exactly like a
nonexistent one** — `Invalid pk "N" - object does not exist`, revealing nothing.

`secret_ids` is write-only. Saving code that calls `get_secret()` for a name not in
`secret_ids` is rejected at save time:

```json
{ "secret_ids": ["Code calls get_secret(\"STRIPE_KEY\") but that secret is not selected for this node. Selected: none. Available in this organization: STRIPE_KEY. Select them under Secrets, or remove the calls."] }
```

That save-time check is a convenience, not the boundary — the enforced gate runs at session
start. See [DEV_secrets_backend_guide.md](DEV_secrets_backend_guide.md) §6.

### Changing a reference needs `secrets:USE`

Every field in this section is additionally gated: **changing** which secret a resource
references requires `Permission.USE` on `secrets`, on top of whatever permission the endpoint
itself demands. Creating a resource that references a secret counts as a change; so does
clearing one.

The reference is treated as *state*, not an operation, so the gate only fires on an actual
delta:

| Payload | Needs `secrets:USE`? |
|---|---|
| field omitted | no |
| field present, same value as persisted | no |
| field present, different value (including `null`) | **yes** |

That distinction is what makes `POST /api/graphs/{id}/save/` workable — it resubmits the
whole graph on every save, so a caller editing an unrelated node resends every secret field
unchanged and needs nothing. Refusals come back as a normal DRF field error:

```json
{ "auth_secret_id": ["Changing the secrets referenced here requires the \"Use\" permission on Secrets. The existing selection was left unchanged. Ask an organization admin to grant it."] }
```

Enforcement lives in `SecretReferenceGuardMixin` — mechanism, coverage guarantees, and how to
diverge one request path are in
[DEV_rbac_backend_guide.md](../rbac/DEV_rbac_backend_guide.md) §5.6.

---

## Quickstart

`POST /api/quickstart/` accepts an optional `api_key`. When the org already has a secret
holding that credential it is **reused** rather than duplicated; `api_key` being optional is
the only breaking change this made to the existing contract. 
