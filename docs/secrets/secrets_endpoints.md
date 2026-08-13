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
    "usage_count": 3
  }
]
```

`value` is **never** in a response — it is `write_only`. `tail` is the last 4 plaintext
characters, or `""` for values shorter than 9 characters.

`usage_count` is the number of distinct resources referencing the secret. The whole list
costs a fixed number of queries regardless of how many secrets the org has — one prepared
count map is computed per request, not per row. See [secret_usage.md](secret_usage.md) for
the counting rules and why this is not simply a row count.

## `GET /api/secrets/{id}/`

One secret, same shape as a list row. Another org's secret is a **404**, not a 403 — a 403
would confirm the row exists.

Unlike the list, this computes the count for that one secret only, in a single query,
instead of building the whole org's map to read one key out of it.

## `POST /api/secrets/`

```json
{ "name": "STRIPE_KEY", "value": "sk-live-51H...", "metadata": {} }
```

`value` is required and write-only. The response is the created row (with
`usage_count: 0`), and the plaintext is not echoed back.

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

Every resource in the active org that references this secret, for the deletion-safety
dialog. `Permission.READ` on `secrets`.

```json
{
  "total": 3,
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
    { "key": "tools", "items": [{ "name": "Stripe refund" }] },
    { "key": "llm_configs", "items": [{ "name": "gpt-4o prod" }] }
  ]
}
```

An unused secret returns `{"total": 0, "categories": []}` — a category is present only when
it has items, so the frontend never renders an empty group.

Field meanings, the `total`-vs-node-count distinction, and the `code_field` values are
documented in [secret_usage.md](secret_usage.md). The response schema and examples are also
in Swagger (`tables/swagger_schemas/secret_schemas.py`).

404 for another org's secret, same as retrieve.

---

## Referencing a secret from another endpoint

Secrets are selected by **id**, never by sending a plaintext key. Two shapes:

**Single FK** — configs and MCP tools take `api_key_secret` / `auth_secret`:

```json
POST /api/llm-configs/
{ "custom_name": "gpt-4o prod", "model": 4, "api_key_secret": 12 }
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

---

## Quickstart

`POST /api/quickstart/` accepts an optional `api_key`. When the org already has a secret
holding that credential it is **reused** rather than duplicated; `api_key` being optional is
the only breaking change this made to the existing contract. 
