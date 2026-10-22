# RBAC Backend Developer Guide

Consolidated reference for how the EpicStaff RBAC system works end to end and — most
importantly — **what you must do to cover a new endpoint, model, or feature with RBAC**.
Everything described here is actual runtime behavior of the `django_app` service.

Related focused docs: [auth_endpoints.md](auth_endpoints.md),
[roles_and_permissions.md](roles_and_permissions.md), [organization_scoping.md](organization_scoping.md),
[organization_management.md](organization_management.md), [user_management.md](user_management.md),
[user_profile.md](user_profile.md), [password_recovery.md](password_recovery.md), [sse_auth.md](sse_auth.md).

---

## 1. Mental model

Every request passes through four independent layers. When you build a new endpoint you
must decide, for each layer, which mechanism applies:

```
┌────────────────────────────────────────────────────────────────────────┐
│ 1. AUTHENTICATION   Who is calling?                                    │
│    JwtAuthentication + ApiKeyAuthentication (global defaults)          │
│    → request.user                                                      │
├────────────────────────────────────────────────────────────────────────┤
│ 2. ORG CONTEXT      Which organization is the caller working in?       │
│    OrgContextService: URL kwarg `org_id` > `X-Organization-Id` header  │
│    Validates membership (superadmin bypasses membership, not existence)│
├────────────────────────────────────────────────────────────────────────┤
│ 3. VERB GATE        May this role perform this action on this          │
│    resource type? HasOrgPermission / assert_org_permission             │
│    (resource_type × action bit against the role's bitmask)   → 403     │
├────────────────────────────────────────────────────────────────────────┤
│ 4. ROW SCOPE        Which rows may the caller see/touch?               │
│    OrgScoped*Mixin queryset filters + OrgScoped/OrgVisible PK fields   │
│    Cross-org rows behave as nonexistent               → 404 / 400      │
└────────────────────────────────────────────────────────────────────────┘
```

Two invariants shape everything:

- **Superadmin bypass** happens inside `PermissionResolver` and `OrgContextService` —
  views and services never special-case `is_superadmin` themselves (except endpoints that
  are architecturally superadmin-only and use `IsSuperadmin`).
- **No existence leaks.** A row in another org must be indistinguishable from a missing
  row: detail lookups → 404, FK references in writes → the standard
  `Invalid pk "N" - object does not exist` 400.

---

## 2. Data model

Six of the seven RBAC models live in `rbac/models/` (the `rbac` Django app). All RBAC
business logic — access control, governance, identity, profile, scoping, validation —
lives under `src/django_app/rbac/`; see §10 for the full file index.

| Model | Table | File (`src/django_app/...`) | Purpose |
|---|---|---|---|
| `User` | `rbac_user` | `tables/models/user.py` (stays in `tables` — see note below) | Custom `AUTH_USER_MODEL` (`tables.User`). Email login, `display_name`, `avatar`, global `is_superadmin`, `value`. No username/is_staff; Django admin is removed. |
| `Organization` | `rbac_organization` | `rbac/models/organization.py` | Tenant. `name` (case-insensitive unique via `LOWER(name)` index), `value` (soft deactivation), `is_default` (partial unique constraint — at most one default org). |
| `OrganizationUser` | `rbac_organization_user` | `rbac/models/organization_user.py` | Membership: (`user`, `org`) unique, carries exactly one `role`. Deleting the row revokes access. |
| `Role` | `rbac_role` | `rbac/models/role.py` | `is_built_in=True, org=NULL` for the four built-ins (immutable); custom roles carry `org`. |
| `RolePermission` | `rbac_role_permission` | `rbac/models/role.py` | One row per (role, resource_type) with an integer permission **bitmask**. |
| `ApiKey` | — | `rbac/models/api_key.py` | Service-to-service auth. Stores a plain SHA-256 hash + 12-char `es-` prefix; `key_type` is `system` or `user`. System keys (no owner) resolve to `SystemServicePrincipal` (superadmin-equivalent); user keys resolve to their owning user. No scopes field — see [api_keys.md](api_keys.md) for detail. |
| `PasswordResetToken` | `rbac_password_reset_token` | `rbac/models/password_reset_token.py` | Single-use reset grant, TTL `PASSWORD_RESET_TOKEN_TTL` (default 900 s). Stores only `token_hash` (SHA-256 of a `secrets.token_urlsafe(32)` value) — the raw token exists once, in the emailed link, so a read of this table is not replayable. The row's existence *is* the grant: consuming or superseding one deletes it, so there is no `is_used` flag and no accumulation of spent verifiers. Generation, hashing and deletion live in `PasswordResetTokenRepository`. |
| `OrgScopedModel` | abstract | `rbac/models/org_scoped.py` | Adds `org` FK (+ index) and `created_by` FK to any resource model. `org` is declared nullable in Python; NOT NULL is enforced per-table at the DB layer after backfill. |

**Why `User` stays in `tables`.** `AUTH_USER_MODEL` is re-resolved on every
migration-graph build. Pointing it at `rbac.User` would retroactively change the
dependencies of every one of the 17 already-applied migrations that reference the user
model, aborting `migrate` on any existing database. See
`docs/superpowers/specs/2026-09-21-rbac-app-extraction-design.md` §2 for the full
argument. `rbac` models that need the user FK import it as `tables.models.user.User` —
one of the two deliberate exceptions the `rbac`-must-not-import-`tables` CI check allows
(the other is `tables.swagger_schemas.common_schemas`, a shared constants module).

### 2.1 Enums (`rbac/models/enums.py`)

```python
class ResourceType(models.TextChoices):
    (
        ORGANIZATIONS,
        ROLES,
        MEMBERSHIPS,
        API_KEYS,
        FLOWS,
        AGENTS,
        TOOLS,
    )
    (
        KNOWLEDGE_SOURCES,
        FILES,
        PROJECTS,
        LLM_CONFIGS,
        SECRETS,
        VOICE,
        SURFACES,
    )
    WEBHOOKS
    KEY_VALUE_TABLES


class Permission(IntFlag):
    CREATE = 1
    READ = 2
    UPDATE = 4
    DELETE = 8
    EXPORT = 16  # 32 retired (was DOWNLOAD, folded into EXPORT)
    USE = 64  # catalog action of `secrets` only; enforced by SecretReferenceGuard and SecretInjectionGuard
    LIST = 128  # reserved — not in the catalog, checked nowhere
    RUN = 256  # catalog action of `flows` only; start/stop runs and write trigger nodes
```

### 2.2 Built-in roles (declared in `rbac/access/builtin_roles.json`)

The four built-in roles — name, description and every permission they hold — are declared in
**`rbac/access/builtin_roles.json`**. The file is the state, not a patch:
`python manage.py seed_builtin_roles` (run by `entrypoint.sh` on every container start, right
after `migrate`) makes the database match it exactly.

```json
"Member": {
  "description": "Builds and edits workspace resources; no organization administration.",
  "permissions": {
    "flows": ["create", "read", "update", "run"],
    "knowledge_sources": ["read"]
  }
}
```

- **Absence is revocation.** An action missing from a resource's list is removed from the role;
  a resource missing from `permissions` is removed entirely. To take a permission away, delete
  it from the file.
- **Only grantable actions are accepted.** Each action must be in that resource's
  `applicable_actions` in `rbac/access/catalog.py`, so `use` on `flows`, `list` anywhere, or a
  platform action is refused. To grant a new kind of action, add it to the catalog and enforce
  it first. This keeps every stored bit one the code enforces and the matrix can show — the
  escalation ceiling compares these masks, so a dead bit can still refuse a legitimate
  assignment.
- **An invalid file stops startup.** The whole file is validated before anything is written
  (unknown role, resource or action; empty list; a built-in role missing from the file;
  grants on Superadmin), every error is reported at once, and the writes run in one
  transaction.
- **Roles are never deleted.** A missing built-in role is created and a changed description is
  updated; a built-in role in the database that the file does not name is only warned about —
  memberships cascade from it.
- **Superadmin** has `"permissions": {}` — its authority is `User.is_superadmin`.

`key_value_tables` has no `use` action; its built-in grants are in `builtin_roles.json` like
every other resource. A Key-Value node's mode decides which `key_value_tables` bits configuring
it needs (`MODE_PERMISSIONS` in `tables/services/key_value_table_service.py`: read → R, write →
C and U, delete → R and D, since a delete node's session message shows the deleted values).

**To change a built-in role:** edit the JSON, run
`make django-tests ARGS="tests/command_tests/test_seed_builtin_roles.py tests/services_tests/test_builtin_role_permissions.py"`,
restart the `django_app` container. Running Django outside Docker? `make django-migrate` does not
apply the file — run `make django-manage CMD="seed_builtin_roles"` after it. **Never write a data migration for built-in roles** — the
seeder would overwrite it on the next start. Migrations `0171` … `0246`, which seeded them
before, are history: they still run on a fresh database and the command reconciles right
after. Tests get the same state: `tests/conftest.py` runs the same seeder after `flush`.

Permissions are resolved from the database on every request and never cached in the JWT, so a
change applies on the first request after the container restarts.

---

## 3. Authentication layer

Global defaults (`django_app/settings/rest_framework.py`):

```python
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rbac.identity.authentication.JwtAuthentication",
        "rbac.identity.authentication.ApiKeyAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}
```

**Every endpoint is authenticated by default.** You only ever *add* permission classes;
opening an endpoint requires an explicit `permission_classes = [AllowAny]` (currently only
first-setup, login, refresh, password-reset request/confirm, swagger-token).

Two authentication classes (`rbac/identity/authentication.py`), both global defaults:
- `JwtAuthentication` — `Authorization: Bearer <jwt>` → simplejwt (HS256, access 15 min,
  refresh 7 d, rotation + blacklist on). Custom claims: `email`, `is_superadmin`,
  `hash_password` (`CHECK_REVOKE_TOKEN=True`: binds the token to the password hash).
- `ApiKeyAuthentication` — `X-Api-Key: <key>` or `Authorization: ApiKey <key>` → delegates to
  `ApiKeyAuthenticator`, which resolves the raw key to an `ApiKey` row, then hands it to
  `PrincipalResolver` (`rbac/identity/api_keys/principals.py`): a `system`-type key
  resolves to `SystemServicePrincipal` (superadmin-equivalent, no `email`/`pk`); a
  `user`-type key resolves to its owner. `request.user` is that principal, `request.auth`
  is the `ApiKey` row. A user key inherits the owner's live RBAC permissions per the
  `X-Organization-Id` header the caller sends — identical to that owner authenticating with
  a JWT. Key management endpoints (`/api/profile/api-keys/`,
  `/api/admin/api-keys/`) are JWT-only (`DenyApiKeyAuth`) — see
  [api_keys.md](api_keys.md). Every write on the governance surface
  (`/api/admin/roles|memberships|organizations|users/`, including permanent
  deletion) is JWT-only, and the SYSTEM key is rejected there even on reads
  (`RestrictApiKeyToUserKeyReads`, prepended first by the `get_permissions` of
  `CrossOrgAdminViewSet` and of `UserAdminViewSet`): a leaked credential must not
  be able to rewrite governance or erase accounts or tenants. `reset-user` and the
  admin password reset are JWT-only via `DenyApiKeyAuth`. Those two, and permanent
  deletion of users and organizations, are superadmin-only by construction — they
  add no `ResourceType` and no `Permission` bit, so no custom role can ever be
  granted them.

Connections that cannot carry headers (SSE, WebSocket) use single-use Redis tickets
(`TicketService`, `rbac/identity/tickets.py`): `POST /api/auth/sse-ticket/`
or `/api/auth/ws-ticket/` with JWT → 30 s single-use ticket consumed atomically via
`GETDEL`, passed as `?ticket=` on the stream URL. Redis stores only
`sha256(ticket)` as the key, so Redis read access yields no replayable ticket.

Throttling (`rbac/throttles.py`; `NotifyEmailThrottle` lives in `tables/throttles.py`) — every
anonymous credential-adjacent endpoint is covered. Exceeding any bucket returns `429` with
`Retry-After`; where a view lists two throttles, a request must pass both.

| Throttle | Endpoint(s) | Bucket | Default rate |
|---|---|---|---|
| `LoginThrottle` | login, swagger-token | `ip\|email` | 5/min |
| `LoginThrottle` | profile password-change request | `ip` (the body has no `email`) | 5/min |
| `LoginIpThrottle` | login, swagger-token | `ip` | 20/min |
| `PasswordResetRequestThrottle` | password-reset request | `ip\|email` | 5/hour |
| `PasswordResetRequestIpThrottle` | password-reset request | `ip` | 20/hour |
| `PasswordResetConfirmThrottle` | password-reset confirm | `ip` | 10/hour |
| `TokenRefreshThrottle` | token refresh | `ip` | 30/min |
| `NotifyEmailThrottle` | notify/email | authenticated user id | 10/hour |

The `ip|email` buckets limit what one address can do to one account without one user's attempts
using up the allowance of everyone behind the same NAT. They never stop an address that names a
new email on each request, since every email is a fresh bucket; that is what `LoginIpThrottle` and
`PasswordResetRequestIpThrottle` cap. `LoginThrottle` takes the email from the request body
whatever the view, so on the password-change request, whose body carries only
`current_password`, its key is the caller's IP alone, in the same `login` scope as logins that
send no email. A caller who adds an `email` field there picks the bucket instead.

`PasswordResetConfirmThrottle` and `TokenRefreshThrottle` key on IP alone because their requests
carry no identifier to compose with — the refresh token arrives in an HttpOnly cookie, and on
confirm the only caller-supplied value is the token being guessed, so keying on it would give an
attacker a fresh bucket per attempt. All four IP-only throttles subclass DRF's `AnonRateThrottle`,
which supplies the IP key and skips authenticated callers; their views set no authentication
classes, so every caller is anonymous and the throttle always applies.

HTTP first-setup (`POST /api/auth/first-setup/`) is itself gated by
`settings.FIRST_SETUP_MODE` (default `cli_only`): it returns `403
first_setup_disabled` unless the mode is `open`. The other creation path,
always available regardless of the mode, is `manage.py create_superadmin`.
See [auth_endpoints.md](auth_endpoints.md) and
[first_setup_operations.md](first_setup_operations.md).

---

## 4. Org context layer

`OrgContextService.resolve(request, view_kwargs)` (`org_context_service.py`) is the single
implementation. Resolution order:

1. URL kwarg `org_id` (target-context; used by `/api/admin/organizations/{org_id}/...`).
   The header is **ignored** on these endpoints.
2. `X-Organization-Id` header (active-context; everything else).

Then membership is asserted: a non-superadmin must have an `OrganizationUser` row in that
org **and the org must be active**. Errors:

| Condition | Exception | HTTP |
|---|---|---|
| Header/kwarg missing or non-integer | `OrgContextRequiredError` (`org_context_required`) | 400 |
| Not a member / org inactive (non-superadmin) | `OrgMembershipRequiredError` (`org_membership_required`) | 403 |

Superadmin skips the membership check (may target any org, including inactive ones).
The resolved id is cached per-request as `request._rbac_active_org_id` — both
`OrgScopedResolverMixin.get_active_org_id()` and the serializer fields share that cache,
so resolution runs at most once per request.

The **only** endpoint with soft-fail semantics is `GET /api/profile/`: a missing/invalid
header yields `active_organization_id: null` + `active_permissions: null` instead of an
error, so zero-membership users can still boot the FE.

---

## 5. Verb gate layer (permission checks)

### 5.1 ViewSets — `HasOrgPermission`

`rbac/access/gates.py`. Declare on the view:

```python
class AgentViewSet(OrgScopedViewSetMixin, CopyActionMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasOrgPermission]  # order is contractual
    rbac_resource_type = ResourceType.AGENTS  # REQUIRED
    rbac_action_map = {  # optional per-view map
        **DEFAULT_ACTION_MAP,
        "copy": Permission.CREATE,
        "export": Permission.EXPORT,
    }
```

Behavior:
- Missing `rbac_resource_type` → `ImproperlyConfigured` at request time (fail loud).
- Superadmin returns `True` before any DB work.
- The required bit is looked up from `rbac_action_map` first, `DEFAULT_ACTION_MAP` second
  (`list/retrieve→READ, create→CREATE, update/partial_update→UPDATE, destroy→DELETE`).
- **A custom `@action` that is not in either map is denied for every non-superadmin.**
  This is deliberate default-deny: every custom action must be mapped explicitly.
- Resolution: `OrgContextService` → `PermissionResolver.resolve(user, org_id)` →
  `EffectivePermissions.can(resource_type, bit)` → 403 with a specific message on failure.

`PermissionResolver` costs ~2 SQL per gated request (membership + role permissions).
A Redis cache seam is documented in the resolver for later.

### 5.2 Plain APIViews — `assert_org_permission`

No DRF `action` exists, so use the functional gate
(`rbac/access/asserts.py`):

```python
org_id = OrgContextService().resolve(request=request)  # or the resolver mixin
assert_org_permission(request.user, org_id, ResourceType.FLOWS, Permission.CREATE)
```

The quickstart endpoint (`tables/views/views.py`) is the reference example.

### 5.3 Session / SSE surfaces — `assert_session_org_access`

Sessions have no org column; they are children of their graph. Non-ViewSet session
surfaces (SSE stream, get-updates, stop) authorize via
`assert_session_org_access(user, session, action)`
(`tables/services/session_access.py`): 404 when the session has no graph, then
membership + FLOWS bit check against `session.graph.org_id`. SSE resolves the user from
the single-use ticket first, then calls this. Reading a session (SSE, get-updates) needs
`READ`; stopping one needs `RUN`, as starting one does (`get_runnable_graph`).

`RUN` also gates writing a trigger node (webhook, Telegram, schedule), because one starts
runs by itself. Which node types are triggers is declared once, by `starts_runs=True` on
their `NodeTypeConfig` in `tables/services/graph_bulk_save_service/registry.py`
(`TRIGGER_NODE_LIST_KEYS`, `TRIGGER_NODE_MODELS`); `tables/services/trigger_nodes.py`
derives everything else from them:

- Writing one trigger node — the bulk save and `TriggerNodeRunPermissionMixin`
  (`tables/views/mixins.py`) — calls `trigger_node_access.assert_may_write`, which raises
  `TriggerNodesRequireRunPermissionError` (403 `trigger_nodes_require_run_permission`).
  `trigger_node_access` is the shared `TriggerNodeAccess` instance.
  Updating a `WebhookTrigger` that a live trigger node is attached to
  (`TriggerNodeInspector.has_any_attached_to_webhook_trigger`) goes through the same
  check in `WebhookTriggerViewSet.update`, since re-keying, re-pathing or re-tunnelling
  it can bring those nodes live. `GET /api/webhook-triggers/{id}/flows/`
  (`flows_using_trigger`, webhooks READ) names those flows in advance, from
  `TriggerNodeInspector.graphs_attached_to_webhook_trigger`; it lists their names only
  when the caller also holds READ on flows, and always returns the count.
- Recreating trigger nodes by copy, import, partial import or version create-graph /
  restore raises `FlowWithTriggerNodesRequiresRunPermissionError`
  (403 `flow_with_trigger_nodes_requires_run_permission`) through
  `trigger_node_access.assert_user_may_recreate` (views) or `assert_may_recreate` (the
  import services, with the `effective_permissions` the caller passes in). One "holds a
  trigger node" decision per source shape, on `TriggerNodeInspector`:
  `has_any_in_graph` (stored flow, copy), `has_any_in_export` (full import file),
  `has_any_in_node_entries` (the nodes a partial import creates) and
  `has_any_in_flow_entry` (version snapshot). The views check after the org-scoped
  fetch, so another org's id stays a 404; the import services check before their
  transaction opens.
- `run-python-code` needs RUN for code a trigger node owns, named by target
  (`CodeRunTarget.owner_is_trigger_node`) or by `python_code_id`
  (`trigger_node_owns_python_code`).

A new trigger node type only needs the flag.
See `roles_and_permissions.md` → "Running flows: the `run` action" for the endpoint list.

### 5.4 Superadmin-only and global surfaces

- `IsSuperadmin` — org CRUD, cross-org user admin, grant/revoke superadmin, reset-user,
  admin password reset.
- `IsSuperadminOrReadOnly` — global singletons exposed as plain APIViews (default-config
  singletons, voice settings): any authenticated user reads, superadmin writes.
- `SuperadminWriteMixin` (`rbac/scoping/mixins.py`) — same idea for ViewSets (global
  registry/catalog rows): safe actions need `IsAuthenticated`, write actions (plus any
  action named in `superadmin_write_actions`) need `IsSuperadmin`. Not org-scoped.

`CrossOrgResourceService` (`rbac/governance/cross_org_base.py`) is the base every cross-org
admin surface (roles, memberships, organizations, API keys) extends for its precise per-org
authorization. It splits the decision in two: **visibility decides the 404, the permission bit
decides the 403.**

`resolve_for_write(actor, org_id, action)` resolves the caller's permissions in one target org
and raises the resource's own 404 unless the row is visible to them. A row is visible when the
caller is a member of its org **and** holds either READ on the resource there **or** the
`action` being attempted. So there are two 404 conditions — not a member, or a member who can
neither read the resource nor perform this action on it — and only a visible row can go on to
produce a 403 from `assert_can`. Returning 403 for an invisible row would confirm an id the
read surface reports as missing. READ-**or**-action, rather than READ alone, is what keeps the
deliberate write-without-read grant working: a role carrying `delete` but not `read` must be
able to delete, not be told the row does not exist. `action` is a required argument precisely
so every call site states which verb it authorizes.

`authorize_any_org(actor, org_ids, action)` is the existential counterpart: it authorizes a row
scoped through a *set* of orgs instead of a single column — an API key's scope is every
organization its owner belongs to — and applies the same split over that set. The row is
visible when **at least one** reachable org grants READ or `action`, and authorized when at
least one grants `action`; sharing no org at all still 404s, exactly as `resolve_for_write`
does for one.
`delegated_scope_q`, an optional class attribute a subclass may declare, is an extra queryset
restriction `apply_org_scope` applies only when a delegated (non-superadmin) caller is being
org-scoped at all — never to a superadmin, who already bypasses the org filter entirely.
`ApiKeyManagementService` sets it to exclude superadmin-owned keys from a delegated admin's
list, since the superadmin's own request already reaches them without it.

### 5.5 Service-layer guards (defense in depth)

Structural invariants are enforced inside services regardless of who the caller is, in
transactions with `SELECT FOR UPDATE`:

- `assert_not_last_org_admin` /
  `assert_role_is_assignable` / `assert_batch_preserves_org_admin`
  (`user_management_guards.py`). `role_is_assignable` is the same rule as a
  predicate, for the assignable-roles filter.
- **the escalation ceiling** — `assert_within_ceiling`
  (`rbac/access/asserts.py`) over
  `EffectivePermissions.covers`: you cannot grant authority you do not hold.
  One comparison, two call paths — authoring a custom role
  (`RoleManagementService.create_role` / `update_role`, the bits written in) and
  assigning any role (`MembershipManagementService.add_member` / `change_role`,
  the bits it grants). It never inspects `is_built_in`, so built-in Org Admin
  and an over-ceiling custom role are refused identically, and it compares only
  the catalog's grantable action bits per resource (`grantable_bits_for`) so a stored bit
  that is not an action of its resource cannot block a legitimate grant. Superadmin bypasses
  inside `covers`.
- last-active-superadmin guard (`user_management_service.py`)
- last-active-organization guard (`organization_management_service.py`)
- `RoleManagementService.assert_mutable` → `BuiltInRoleImmutableError` (403) for built-ins
- `PasswordRecoveryService.admin_reset` re-checks `is_superadmin` inside the service.
- bootstrap advisory lock (`acquire_bootstrap_lock`,
  `rbac/identity/bootstrap_lock.py`) — `FirstSetupService.setup()` and
  `ResetUserService.reset()` both take a PostgreSQL transaction-scoped
  advisory lock before checking whether a user exists, so concurrent callers
  cannot race past that check and create two bootstrap superadmins.

Follow the same pattern: view-level gate for the verb, service-level guard for the
invariant.

---

### 5.6 `secrets:USE` on secret references — write time and injection time

One check lives in neither the view nor a service the view calls: whether the caller may
change **which Secret a resource references, or where it sends it**. It is enforced on
every write path (API serializers, import), and re-checked when a session payload is
built. The pieces:

| Piece | Where | What it does |
|---|---|---|
| `SecretReferenceGuard` | `tables/services/secrets/reference_guard.py` | Pure service. `assert_permitted(actor=SecretActor(user, org_id), changes=[...])` raises `SecretUseDeniedError(field_name, message)` (a plain domain exception) for the first change that changes something, unless the actor holds `secrets:USE`. Never sees a serializer or a request. |
| `SecretPolicy` subclasses | `tables/services/secrets/policies/` | Per entity: which fields are guarded and where a secret goes. Run without DRF, so import/restore/copy can use them. Registered in `SECRET_POLICIES`. |
| `SecretReferenceGuardMixin` | `tables/serializers/utils/secret_reference_guard_mixin.py` | Thin adapter: builds a `RowWrite` from the serializer, asks its `secret_policy` for the changes, builds the actor from the request, turns `SecretUseDeniedError` into `ValidationError({field_name: message})`. |
| `PersistedValueMixin.persisted_value(source)` | `tables/serializers/utils/persisted_value.py` | The one extension point for "what does the saved row hold here". Shared by the guard mixin and `KeptLinkPrimaryKeyRelatedField`. |
| `SecretInjectionGuard` | `tables/services/secrets/injection_guard.py` | Injection-time re-check in the payload builder (below). |

```python
MCP_TOOL_SECRET_POLICY = SecretPolicy(reference_fields=("auth_secret_id",))


class McpToolSerializer(SecretReferenceGuardMixin, serializers.ModelSerializer):
    secret_policy = MCP_TOOL_SECRET_POLICY
```

A policy that only lists fields is a plain `SecretPolicy` instance; one that decides a
destination or records an approver is a subclass (`LLMConfigSecretPolicy`). Every policy
instance is registered in `SECRET_POLICIES`, and the adapter makes a single call,
`SecretReferenceGuard.authorize_write(policy=..., write=..., resolve_actor=...)`, which
raises `SecretUseDeniedError` or returns the approval attrs the write earns (below).

**The delta rule.** A secret reference is *state, not an operation*. Omitted from the
payload → no change; present but equal to the persisted value → no change; different →
`secrets:USE` required. This is what makes the guard usable from `graph/{id}/save`, which
submits the whole graph on every save and would otherwise demand `USE` from anyone editing
an unrelated node. The policy describes every guarded field the write sets (a
`SecretReferenceChange(field_name, incoming, current)`); the guard decides what counts as
a change. Linked rows compare by pk through `linked_ids(value)` (`tables.services.secrets`),
which reads a related manager through `all_objects`, so a link to a binned row still counts
as "what the row links to now". A field the writer does not expose as writable is skipped,
so one policy serves a serializer and its narrower variants.

**No request, no permission.** The adapter passes no actor when there is no `request` in
serializer context, and the guard denies a missing actor (with a warning log) — fail-safe,
not fail-open. Any service that drives these serializers must thread the request through
(`GraphBulkSaveService` does). The adapter builds the actor only when something changed:
resolving the active org costs a query and fails outright on a request without the header,
and an unchanged write must need neither (`SecretReferenceGuard.requires_use`).

**Header markers.** A secret can also be referenced *by name*: `SecretResolver` replaces
every `epicstaff_secret(<name>)` marker in an `extra_headers` value with the plaintext of the
org's secret of that name when it resolves a session payload. Such a field is listed in the
policy's `header_fields`, and the same delta rule applies to the **set of marker names**
(`extract_secret_marker_names`, shared with the resolver, so both read the same regex). Editing
a header's other text, adding a header without a marker, or resending the same markers
needs nothing; adding, renaming or removing a marker needs `USE`. On create the persisted
set is empty, so any marker needs `USE`.

```python
class LLMConfigSecretPolicy(SecretPolicy):
    reference_fields = ("api_key_secret_id",)
    header_fields = ("extra_headers",)
    approval_model = LLMConfig
    approval_label = "LLM config"
```

**Destination changes.** Holding a reference is only half of it; the other half is where the
request carrying it goes. A policy whose row decides that overrides two methods, both taking
a `RowWrite` (the persisted row, the incoming attrs, the writable `{field name: source}` map
and a `persisted_value` reader — plain data, no serializer): `destination(write)` returns
`{field name: value}` once the write is saved, and `carries_secret(write)` says whether a
secret travels there. `write.value_after_save(source, persisted_attribute=...)` and
`write.writable_values_after_save(exclude=...)` are the helpers for writing them. On
**update**, when a destination value changes and a secret travels, the guard requires `USE`
(`SecretDestinationChange`) and names the changed field. `carries_secret` runs only for a
destination that actually moved, so its queries cost nothing on an ordinary edit. Create is
not checked: a new row reaches a secret only through a reference, which the rules above
already gate.

**The destination of a model-backed config is the model's identity, not its `base_url`.**
Routing depends on more than the base URL: litellm also routes on the model name (a Hugging
Face model named `https://…` becomes the endpoint when no base URL is set), the provider,
`api_version` and the deployment, and its rules change between versions. So
`model_destination(model)` (`tables.services.secrets.policies`) trusts only the superadmin
catalog: every built-in model (`is_custom=False`, no org) — and no model at all — is the one
destination `CATALOG_DESTINATION`; a custom model is its own destination, its pk. Switching
a secret-bearing config among catalog models needs nothing; pointing it at any custom model,
or moving it between custom models (or off one), needs `USE`. Changes inside a custom model
are gated on the model row itself: its destination is **every writable field except an
explicit cosmetic list** (`LLM_MODEL_NON_ROUTING_FIELDS`, `EMBEDDING_MODEL_NON_ROUTING_FIELDS`;
blank compared as null), so a field added later is gated until someone decides it does not
route.

| Policy (serializer) | Destination | Carries a secret when |
|---|---|---|
| `LLMConfigSecretPolicy` (`LLMConfigSerializer`) | `model` → `model_destination`; `base_url` → the config's own, read by nothing today but gated so wiring it up later is not a bypass | `api_key_secret` is set or `extra_headers` holds a marker, after the change |
| `LLMModelSecretPolicy` (`LLMModelSerializer`) | `name`, `llm_provider`, `deployment_id`, `api_version`, `base_url` (all writable fields except `description`, `is_visible`, `capabilities`, `tags`) — everything `ConverterService` and the knowledge service send on | any `LLMConfig` using the model carries one (update only; an `exists()` on the key first, then the headers) |
| `EmbeddingConfigSecretPolicy` (`EmbeddingConfigSerializer`) | `model` → `model_destination` | `api_key_secret` is set, after the change |
| `EmbeddingModelSecretPolicy` (`EmbeddingModelSerializer`) | `name`, `embedding_provider`, `deployment`, `base_url` (all writable fields except `is_visible`, `tags`) | any `EmbeddingConfig` using the model has `api_key_secret` (one `exists()`, update only) |
| `OpenAIRealtimeConfigSecretPolicy` (`OpenAIRealtimeConfigSerializer`) | `base_url` (its own; the realtime clients connect to `{base_url}?model=…`, so `model_name` sits in the query string and cannot move the host) | `api_key_secret` or `transcription_api_key_secret` is set, after the change |

Gemini, ElevenLabs and the deprecated `RealtimeConfig` / `RealtimeTranscriptionConfig`
have no `base_url`, so their policies declare no destination. Creating a model or config
with any field values does not need `USE`. The config viewsets `select_related("model")`
because every update reads the persisted model.

**Second layer: no URL in a model name.** `reject_url_in_model_name`
(`tables/validators/model_name_validator.py`) rejects an `LLMModel` or `EmbeddingModel`
name containing `://` on create and update, through the API serializers and the import
serializers alike. No catalog name contains one.

**Import.** Secret FKs never travel in an export file, but header markers do, and they
resolve by name in the importing org. `LLMConfigStrategy.secret_binding_approval` passes
`RowWrite.for_new_row(data)` and `LLM_CONFIG_SECRET_POLICY` to
`SecretReferenceGuard.authorize_write` with the importing user and org as the actor, turns
`SecretUseDeniedError` into a `ValidationError` saying nothing was imported, and hands the
returned approval to the create (`BaseConfigStrategy.create_entity` saves it with the row). A newly created config with markers needs
`USE`; a reused equivalent config changes nothing and is not checked. The import serializer
is listed in `HEADER_EXEMPT` in `test_secret_reference_coverage.py` for that reason.

**Diverging one request path.** A subclass that must guard differently — a `*BulkSerializer`
(graph save subclasses the node serializers) or an endpoint-specific variant — sets its own
`secret_policy`, leaving the class its siblings share unchanged. Narrowing a path's
protection must be justified in `EXEMPT` in the coverage test.

**Nested serializers.** A nested serializer has no instance of its own, so it overrides
`persisted_value`: `NgrokConfigInlineSerializer` reads the parent trigger's `ngrok` row,
`PythonCodeSerializer` reads the parent's `python_code`, and `WebhookTriggerNestedSerializer`
reads `auth_secret_id` one hop away on its `WebhookTriggerAuth` row.

**Injection time (defence in depth).** The write rules make pointing a secret-bearing config
at a custom destination require `USE`. Before a secret id leaves Django, the payload builder
also checks that a person who still holds `USE` approved the row's secret binding. This
catches an approver who has since lost `USE`, left the org or been deleted, and a binding no
`USE` holder ever approved (NULL fails closed). It does **not** detect a direct database edit
of the destination: such an edit leaves the approver in place.
`SecretInjectionGuard.assert_injection_permitted(config)` runs in
`ConverterService.convert_llm_config_data`, `convert_embedding_config_to_pydantic`,
`convert_rt_agent_definition_chat_to_pydantic` (OpenAI realtime), wherever a RAG embedder or
LLM secret id is emitted (`injectable_api_key_secret_id`: the converter's knowledge nodes,
`RealtimeSurfaceService`, `IndexingService`), and in `llm_clients.resolve_llm_api_key`, the
one way a direct LLM call (Flow Assistant, CDT explain) gets its key -- async callers run it
in `sync_to_async`, because the check queries. `get_llm_client` converts with the
check-free `ConverterService.build_llm_config_data`. The configs checked are those whose
policy has an `approval_model`. The rule:

- The config's policy decides (`SecretPolicy.sends_secret_to_custom_destination`): a
  destination whose values are all empty or `CATALOG_DESTINATION`, or a config carrying no
  secret, is **not checked** and costs no query.
- Otherwise the config's **approver** (`secret_binding_approved_by`, from
  `SecretBindingApprovedModel` on `LLMConfig`, `EmbeddingConfig` and `OpenAIRealtimeConfig`)
  must still hold `secrets:USE` in the config's org, judged through the same
  `SecretReferenceGuard` / `PermissionResolver` path (`SecretReferenceGuard.may_use`).
- It **fails closed**: no approver (never approved, or the user was deleted), an approver
  who left the org, or one who lost `USE` → `SecretInjectionDeniedError` (400), naming the
  config and asking an admin with `secrets:USE` to re-save it. Never a secret value.
- In a session run the error ends the session in `ERROR` with that reason and nothing is
  published, like `UndeclaredSecretError`.
- `SessionManagerService.create_session_data` wraps the build in
  `secret_injection_guard.batch()`, so each config and each (approver, org) pair is looked up
  once per build however many nodes share it.

**Who becomes the approver.** Decided in one place, `SecretReferenceGuard`, for every writer
(serializer adapter, import, quickstart); the policy only says whether a row records one
(`approval_model`) and what to stamp (`SecretPolicy.binding_approval(actor)`):

- `authorize_write`: a change that needed `USE` and was permitted — attaching or changing a
  secret, a header marker or a secret-bearing destination, including creating a row that
  carries a secret — makes its actor the approver. An actor that is not a person (the system
  API-key principal) records NULL here: it changed the binding, and no person approved it.
- `authorize_write`, on a save of a persisted row whose secret goes somewhere custom with no
  gated change: a **person** holding `USE` re-approves it (this is how an admin restores
  delivery by re-saving). Anyone else — a member without `USE` changing the temperature, or
  the system API-key principal — leaves the approver untouched (`approval_by_use_holder`).
- Import: `LLMConfigStrategy` passes the importing user's approval into the create.
- Quickstart: `QuickstartService.quickstart` stamps the requesting user on the configs it
  creates (LLM, embedding, OpenAI realtime) only if they are a person holding `USE`
  (`approval_by_use_holder`); otherwise they stay NULL, and a bundle on a custom model is not
  delivered until an admin re-saves it.

The field is never writable by a client and is not in API or export payloads. Configs are
not copied as standalone entities, and a restore keeps the row, so neither path changes the
approver.

Migration `0273_secret_binding_approved_by` backfills existing rows that send a secret
somewhere custom: the approver becomes the last editor (or the creator when no editor is
recorded — no last edit, or one whose editor is NULL), only if that user holds `secrets:USE` in the row's org at migration time; otherwise
it stays NULL and the row's secret is not delivered until an admin re-saves it.

**Adding a guarded entity:** declare its policy in the matching `policies/` module — a
`SecretPolicy(reference_fields=..., header_fields=...)` instance, or a subclass instance when
it decides a destination — add it to `SECRET_POLICIES`, and set
`secret_policy = <THE_POLICY>` on each serializer that writes the entity. If its row routes a
secret somewhere custom, override `destination` and `carries_secret`, add a row to the table
above, add API tests next to `test_secret_use_llm_headers_and_destination.py`, and — if a
payload builder injects it — mix `SecretBindingApprovedModel` into the model, set
`approval_model`/`approval_label` on the policy (that registers it with
`SecretInjectionGuard`) and call the guard where its secret id is emitted. `test_secret_reference_coverage.py` fails for a Secret field no policy
guards, a writable header or `base_url` field without a policy that covers it (or an
`*_EXEMPT` entry with a reason), a policy missing from `SECRET_POLICIES` or used by no
serializer, a policy field name that is not a writable field of any serializer using it,
and a serializer whose `validate()` never reaches the guard. An FK-shaped destination is
pinned by name in `FK_DESTINATION_SERIALIZERS`, and the model policies' routing-field sets
are pinned in `test_model_serializers_treat_every_routing_field_as_destination`.


---

## 6. Row scope layer (queryset scoping)

All mixins live in `rbac/scoping/mixins.py` and share `OrgScopedResolverMixin`
(`get_active_org_id()`). **Place the org mixin FIRST in the bases list** so its
`get_queryset`/`perform_create` wrap the concrete ViewSet's.

| Mixin | Use for | Declares | Behavior |
|---|---|---|---|
| `OrgScopedViewSetMixin` | Top-level resources owning an `org` FK (Graph, AgentDefinition, LLMConfig, SourceCollection, Label, …) | — | filters `org_id=active`, stamps `org_id` + `created_by` on create |
| `OrgScopedChildViewSetMixin` | Children scoped through a parent FK (nodes, edges, sessions, RealtimeAgent, …) | `org_filter_path = "graph__org_id"` | filters through the path; on create asserts the parent is in the active org (404 otherwise); does NOT stamp org |
| `OrgScopedHybridViewSetMixin` | Shared built-ins + per-org custom rows (LLMModel via `is_custom`, PythonCodeTool via `built_in`, …) | `global_visibility_q`, `custom_create_values` | lists built-ins OR own-org rows; creates always stamped org + forced out of the built-in subset |
| `BuiltInWriteProtectedMixin` | Any hybrid registry whose built-ins must be immutable via the API (the four provider `*Model` tables) | — | 403 `built_in_model_immutable` on update/destroy of an `org IS NULL` row, **including for superadmin**; place after the org mixin |
| `OrgScopedQuerysetMixin` | Non-standard scope (multiple parents, hybrid-parent visibility) | `get_org_scope_q(org_id)`, optional `scope_distinct` | applies your Q |
| `OrgScopedServiceViewSetMixin` | Views delegating to services with raw ids (knowledge endpoints) | — | `get_in_active_org_or_404(model, pk, org_path=...)` helper |

`CopyActionMixin.copy` stamps `org_id=get_active_org_id()` when the host viewset is
org-scoped.

### 6.1 Serializer-level reference scoping (write isolation)

Queryset scoping protects reads; **FK references in writes** are protected by dedicated
fields (`rbac/scoping/fields.py`):

- `OrgScopedPrimaryKeyRelatedField(queryset=..., org_lookup="org_id")` — strict targets
  (AgentDefinition, Graph, LLMConfig, RealtimeConfig, McpTool, PythonCodeToolConfig…).
  `org_lookup` accepts paths like `"graph__org_id"`.
- `OrgVisiblePrimaryKeyRelatedField(queryset=...)` — hybrid targets (LLMModel,
  EmbeddingModel, Realtime*Model, PythonCodeTool): built-ins (`built_in=True` /
  `is_custom=False`) OR own-org rows. Use this one for hybrid targets, otherwise built-ins
  become unreferenceable.
- `org_visible_q(model, org_id)` / `org_visible_queryset(model, org_id)` — the same rule
  for non-serializer code paths (e.g. string-encoded `tool_ids` resolution).

Both fields **require `context={"request": request}`**. Without it they deny all pks
(empty queryset) and log a warning — fail-safe, not fail-open. Services that construct
serializers manually (e.g. `graph_bulk_save_service/service.py`) must thread the request
into every serializer context.

Serializer rules for org-scoped models:

1. `read_only_fields = ["org", "created_by"]` always (the mixin stamps them; the client
   never chooses the org).
2. Every writable FK/M2M pointing at an org-scoped model must use one of the two fields
   above — a plain `PrimaryKeyRelatedField` (or an implicit one from `fields="__all__"`)
   validates against the unfiltered table and is a cross-org injection hole.
3. Prefer explicit `fields = [...]` over `fields = "__all__"` so a new FK added to the
   model cannot silently ship unscoped.

---

## 7. Wire contracts

### 7.1 Headers

| Header | Meaning |
|---|---|
| `Authorization: Bearer <jwt>` | End-user auth |
| `X-Api-Key` / `Authorization: ApiKey <key>` | Service auth: a user key inherits its owner's permissions; the system key acts as a superadmin service principal |
| `X-Organization-Id: <int>` | Active org for active-context endpoints. CORS-allowlisted in settings. |

### 7.2 Permissions for the FE

- `GET /api/permissions/catalog/` — static taxonomy from
  `rbac/access/catalog.py` (`RESOURCE_TYPE_METADATA`,
  `ACTION_METADATA`). This file is the **single source of truth** for which actions apply
  to which resource type; the FE matrix, role serializers, and bitmask↔codes conversion
  all read it.
- `GET /api/permissions/me/` (header required) — `{org_id, is_superadmin, role,
  permissions}` where `permissions` is `"*"` for superadmin or
  `{resource_type: [action_code, ...]}` with **every** catalog resource present (zero
  permissions surface as `[]`).
- Wire format is always action-code strings, never raw bitmask ints
  (`rbac/access/bitmask.py` converts both ways, filtering non-applicable bits).

### 7.3 Error envelope

`utils/exception_handler.custom_exception_handler` renders domain exceptions from
`rbac/exceptions.py` as
`{"status_code": ..., "code": "...", "message": "..."}`. Reuse existing codes
(`org_context_required`, `org_membership_required`, `permission_denied`,
`built_in_role_immutable`, `built_in_model_immutable`, `last_org_admin`,
`last_superadmin`, …) and add new exceptions
to that module — never raw `Response({"error": ...})`.

---

## 8. Recipes — covering new code with RBAC

### 8.1 New top-level org-owned resource

1. **Model** — inherit the mixin first: `class Widget(OrgScopedModel, models.Model)`.
   If the model had a globally-unique `name`, drop `unique=True` and add a per-org
   `UniqueConstraint(fields=["org", "name"])`.
2. **Migrations** — three steps, per the established convention (run `makemigrations`
   for schema steps; hand-write only the RunPython/RunSQL bodies):
   - schema: nullable `org` + `created_by`;
   - backfill: `assign_default_org(apps, "tables.Widget")` from
     `tables/migrations/_helpers.py` (assigns the `is_default` org, creating it if the DB
     predates RBAC);
   - `RunSQL` `ALTER TABLE ... ALTER COLUMN org_id SET NOT NULL`.
3. **ViewSet**:

   ```python
   class WidgetViewSet(OrgScopedViewSetMixin, viewsets.ModelViewSet):
       permission_classes = [IsAuthenticated, HasOrgPermission]
       rbac_resource_type = ResourceType.<CLOSEST_TYPE>
       queryset = Widget.objects.all()          # NEVER pre-filter the manager
       serializer_class = WidgetSerializer
   ```

   Map any custom `@action` in `rbac_action_map` or it is default-denied.
4. **Serializer** — explicit `fields`, `read_only_fields = ["org", "created_by"]`,
   org-scoped fields for FK references (§6.1).
5. **Resource type** — reuse the closest existing `ResourceType`. Only add a new one when
   the resource genuinely needs its own permission column; that requires: enum value +
   `RESOURCE_TYPE_METADATA` entry + the resource's grants for each built-in role in
   `rbac/access/builtin_roles.json` (no migration, §2.2) + FE catalog pickup (automatic via
   the catalog endpoint).
6. **Tests** (pattern: `tests/api_tests/test_org_scoping_core.py`):
   - create lands in the active org with `created_by` stamped;
   - list returns only active-org rows;
   - cross-org detail → 404; cross-org FK reference in a write → 400 "Invalid pk";
   - viewer/member role matrix → 403 on denied verbs;
   - missing header → 400 `org_context_required`.

### 8.2 New child resource (no own org column)

No model change. ViewSet: `OrgScopedChildViewSetMixin` + `org_filter_path`
(`"graph__org_id"`, `"agent_node__graph__org_id"`, `"session__graph__org_id"`, …) + `HasOrgPermission` with the
parent's resource type. The mixin already blocks creating a child under another org's
parent. In the serializer, the parent FK should still use `OrgScopedPrimaryKeyRelatedField`
so updates cannot re-point the child cross-org.

### 8.3 New hybrid resource (shared built-ins + org customs)

Model: `OrgScopedModel` + a discriminator flag (`built_in` or `is_custom`), `org` stays
nullable (built-ins keep `org=NULL` — do not flip NOT NULL). Name uniqueness must be
**per-org plus a partial constraint for the built-in subset** — Postgres treats NULLs as
distinct, so a `UniqueConstraint(org, name, ...)` alone leaves built-ins uncovered, while a
global one lets one org's private name block another's (pitfall #9).
ViewSet: `OrgScopedHybridViewSetMixin` with `global_visibility_q` and
`custom_create_values` (forcing new rows out of the built-in subset), then
`BuiltInWriteProtectedMixin` — the hybrid queryset deliberately includes built-ins so they
are *readable*, and the same queryset backs `get_object`, so without the second mixin every
org can edit and delete them.
Serializer: the discriminator flag and any `predefined`-style provenance flag must be
`read_only` — `custom_create_values` only guards create, so a writable flag lets a `PATCH`
promote an org's row into the shared bucket.
References to it from other serializers: `OrgVisiblePrimaryKeyRelatedField`.

**Resolution by name, not pk** (seeding commands, quickstart, importers) must filter on
`org` explicitly, and must state a *precedence* when both a built-in and an own-org row can
match: `org_visible_queryset(...)` returns both, and `.first()` on it has no `ORDER BY`, so
the result is whatever Postgres feels like returning. See
`QuickstartService._get_or_create_llm_model` for the pattern (own-org wins), and
`upload_models.py` for the built-ins-only form (`org__isnull=True`) — Django strips
`__`-lookups from `get_or_create`/`update_or_create` create params, so that filter narrows
the lookup without leaking into the created row.

### 8.4 Plain APIView / service-delegating endpoint

```python
class MyView(OrgScopedResolverMixin, APIView):          # or OrgScopedServiceViewSetMixin
    def post(self, request):
        org_id = self.get_active_org_id()
        assert_org_permission(request.user, org_id, ResourceType.FLOWS, Permission.CREATE)
        obj = self.get_in_active_org_or_404(Graph, pk)   # if fetching by raw id
        service.do_thing(org_id=org_id, ...)             # pass org_id explicitly
```

Services must take `org_id` as an explicit parameter — never resolve the org inside a
service, and never trust ids in the payload without an org-scoped fetch.

### 8.5 Streaming (SSE/WS) endpoint

1. Client obtains a ticket (`/api/auth/sse-ticket/` or `/ws-ticket/`).
2. Your consumer/view consumes it (`sse_ticket_service.consume(ticket)`) → user or 401
   `invalid_sse_ticket`.
3. Authorize against the org that owns the streamed object (for sessions:
   `assert_session_org_access`). Never trust an org id supplied in the query string.

### 8.6 Global (non-org) resource

Registry/catalog/config singletons: `SuperadminWriteMixin` (ViewSet) or
`IsSuperadminOrReadOnly` (APIView). Do not org-scope. If ordinary org members must be able
to write it, it is not global — scope it instead.

### 8.7 Import/export & background paths

Any code creating resources outside a normal ViewSet (importers, quickstart, copy
services) must receive the resolved `org_id` from the view layer and stamp it on every
created row (see `tables/import_export/strategies/graph.py::create_entity` and
`GraphCopyService`). Never look up the default org as a fallback for a request-driven
path — the default org is only for bootstrap and data migrations.

---

## 9. Common pitfalls (each one has been a real bug)

1. **`fields = "__all__"` on a serializer whose model gained an org-scoped FK** — the FK
   materializes as an unscoped `PrimaryKeyRelatedField` → cross-org injection.
2. **Constructing serializers without `context={"request": ...}`** in services — org
   fields deny everything (fail-safe) and the write breaks; thread the request through.
3. **Custom `@action` not added to `rbac_action_map`** — 403 for every non-superadmin;
   symptoms look like a permissions bug, cause is the deliberate default-deny.
4. **Org mixin not first in the MRO** — its `get_queryset` never runs; rows leak.
5. **Filtering in the model manager instead of the view** — breaks migrations, admin
   tooling, and superadmin behavior. Keep org filtering in the view layer.
6. **Returning 403 for a cross-org row on a detail route** — leaks existence; queryset
   scoping already produces the correct 404. Only the verb gate returns 403.
7. **Checking membership but not the permission bits** (or vice versa) on hand-rolled
   APIViews — use `assert_org_permission`, which does both via the resolver.
8. **Forgetting `custom_create_values` on a hybrid viewset** — a created row defaults
   into the built-in subset and becomes visible to every org.
9. **New unique constraint left global** instead of per-org — org A blocks org B from
   using a name it cannot even see.
10. **Trusting payload-supplied user/org identifiers** — the authenticated context
    (`request.user`, resolved org id) is the only source of truth.

---

## 10. Service & file index

| Concern | File (`src/django_app/...`) |
|---|---|
| Auth backend (JWT + API key) | `rbac/identity/authentication.py` |
| Login/logout/first-setup/reset-user/introspect views | `rbac/views/auth.py` |
| First-time setup | `rbac/identity/first_setup.py`, `rbac/identity/superadmin_bootstrap.py` |
| First-setup mode gate | `rbac/identity/first_setup_mode.py` |
| Bootstrap advisory lock (first-setup + reset-user) | `rbac/identity/bootstrap_lock.py` |
| CLI superadmin creation | `rbac/management/commands/create_superadmin.py` |
| Password recovery (request/confirm/admin/CLI) | `rbac/identity/passwords/recovery.py` + `rbac/identity/passwords/*` |
| Profile + avatar + 2-step password change | `rbac/profile/service.py`, `rbac/views/profile.py` |
| Profile-change broadcast (presence card refresh) | `rbac/signals.py` (`profile_updated`, sent by `rbac/views/profile.py`), received by `tables/signals/profile_signals.py`, which calls `tables/graph_collab/notifications.py` (`GraphEditNotifier.notify_profile_updated`) |
| Cross-org management base | `rbac/governance/cross_org_base.py` (`CrossOrgResourceService`), `rbac/views/cross_org_base.py` (`CrossOrgAdminViewSet` + `superadmin_actions` mixed gate) — reused by roles / memberships / orgs / API keys |
| Org management (list/read/rename permission-aware; create/deactivate superadmin) | `rbac/governance/organizations.py`, `rbac/views/organizations.py` |
| Membership management (cross-org, MEMBERSHIPS-gated, assignment ceiling) + assignable-user lookup | `rbac/governance/memberships.py`, `rbac/views/memberships.py` |
| User account admin (superadmin: create / grant-revoke SA / activate-deactivate) | `rbac/governance/users.py`, `rbac/governance/guards.py`, `rbac/views/users.py` |
| Roles CRUD + authoring ceiling + immutability guard + `?assignable_org_ids=` filter + the org-scoped `assigned_count` | `rbac/governance/roles.py`, `rbac/views/roles.py` |
| Escalation ceiling (shared by authoring and assignment) | `rbac/access/asserts.py` (`assert_within_ceiling`), `rbac/access/effective.py` (`covers`, `bits_of`) |
| API key management (cross-org, API_KEYS-gated: list/revoke/delete members' keys) | `rbac/governance/api_keys.py`, `rbac/views/api_keys_admin.py` |
| Permission gate (ViewSet) | `rbac/access/gates.py` (`HasOrgPermission`, `IsSuperadmin`, `IsSuperadminOrReadOnly`) |
| Permission gate (APIView) | `rbac/access/asserts.py` |
| Session/SSE authorization | `tables/services/session_access.py`, `tables/views/sse_views.py` (stays in `tables` — sessions are children of the graph, not an RBAC concept) |
| Org resolution | `rbac/access/org_context.py` |
| Effective permissions + resolver | `rbac/access/effective.py`, `rbac/access/resolver.py` |
| Action maps & catalog | `rbac/access/action_map.py`, `rbac/access/catalog.py` |
| Built-in roles (state + seeder + command) | `rbac/access/builtin_roles.json`, `rbac/access/builtin_roles.py`, `rbac/management/commands/seed_builtin_roles.py` |
| Bitmask helpers | `rbac/access/bitmask.py` |
| SSE/WS tickets | `rbac/identity/tickets.py` |
| Queryset mixins | `rbac/scoping/mixins.py` |
| Serializer org fields | `rbac/scoping/fields.py` |
| Domain exceptions | `rbac/exceptions.py` |
| Throttles | `rbac/throttles.py` |
| Backfill helper for migrations | `tables/migrations/_helpers.py` (`assign_default_org`, stays in `tables` — a migration-time helper, not an RBAC runtime concern) |
| Storage org enforcement | `tables/views/storage_views.py`, `tables/services/storage_service/manager.py` |

Reference test suites: `tests/api_tests/test_rbac_auth.py`,
`test_rbac_user_management.py`, `test_rbac_permission_enforcement.py`,
`test_rbac_organization_management.py`, `test_rbac_user_profile.py`,
`test_org_scoping_core.py`, `tests/services_tests/test_permission_resolver.py`,
`tests/graph_collab/test_presence_state_updated.py` (profile-change broadcast;
this suite requires `daphne`).
