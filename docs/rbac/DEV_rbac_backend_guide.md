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

All RBAC models live in `tables/models/rbac_models/`. All business logic lives in
`tables/services/rbac/`.

| Model | Table | Purpose |
|---|---|---|
| `User` | `rbac_user` | Custom `AUTH_USER_MODEL` (`tables.User`). Email login, `display_name`, `avatar`, global `is_superadmin`, `is_active`. No username/is_staff; Django admin is removed. |
| `Organization` | `rbac_organization` | Tenant. `name` (case-insensitive unique via `LOWER(name)` index), `is_active` (soft deactivation), `is_default` (partial unique constraint — at most one default org). |
| `OrganizationUser` | `rbac_organization_user` | Membership: (`user`, `org`) unique, carries exactly one `role`. Deleting the row revokes access. |
| `Role` | `rbac_role` | `is_built_in=True, org=NULL` for the four built-ins (immutable); custom roles carry `org`. |
| `RolePermission` | `rbac_role_permission` | One row per (role, resource_type) with an integer permission **bitmask**. |
| `ApiKey` | — | Service-to-service auth. Stores a plain SHA-256 hash + 12-char `es-` prefix; `key_type` is `system` or `user`. System keys (no owner) resolve to `SystemServicePrincipal` (superadmin-equivalent); user keys resolve to their owning user. No scopes field — see [api_keys.md](api_keys.md) for detail. |
| `PasswordResetToken` | `rbac_password_reset_token` | Single-use UUID token, TTL `PASSWORD_RESET_TOKEN_TTL` (default 900 s). |
| `OrgScopedModel` | abstract | Adds `org` FK (+ index) and `created_by` FK to any resource model. `org` is declared nullable in Python; NOT NULL is enforced per-table at the DB layer after backfill. |

### 2.1 Enums (`rbac_enums.py`)

```python
class ResourceType(models.TextChoices):
    ORGANIZATIONS, FLOWS, AGENTS, TOOLS, KNOWLEDGE_SOURCES,
    FILES, PROJECTS, LLM_CONFIGS, SECRETS, USERS, ROLES

class Permission(IntFlag):
    CREATE = 1; READ = 2; UPDATE = 4; DELETE = 8
    EXPORT = 16          # 32 retired (was DOWNLOAD, folded into EXPORT)
    USE = 64; LIST = 128 # reserved — present in bitmasks, not yet in the catalog UI
```

### 2.2 Built-in roles (seeded by migrations 0171 + 0183, idempotent)

Superadmin role row has **zero** `RolePermission` rows — authority comes exclusively from
`User.is_superadmin`. Current seeded bitmasks (`0183_seed_builtin_role_permissions.py`):

| resource_type | Org Admin | Member | Viewer |
|---|---|---|---|
| flows | 31 (CRUD+E) | 7 (CRU) | 66 (R+use) |
| agents | 31 (CRUD+E) | 7 (CRU) | 2 (R) |
| tools | 15 (CRUD) | 7 (CRU) | 2 (R) |
| knowledge_sources | 15 (CRUD) | 2 (R) | 2 (R) |
| files | 31 (CRUD+E) | 23 (CRU+E) | 2 (R) |
| projects | 31 (CRUD+E) | 7 (CRU) | 2 (R) |
| llm_configs | 15 (CRUD) | 2 (R) | 2 (R) |
| secrets | 207 (CRUD+use+list) | 192 (use+list) | 192 (use+list) |
| users | 15 (CRUD) | 0 | 0 |
| roles | 15 (CRUD) | 0 | 0 |
| organizations | 0 | 0 | 0 |

If you change a seed, do it with a new idempotent data migration — never edit an applied one.

---

## 3. Authentication layer

Global defaults (`django_app/settings.py`):

```python
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "tables.services.rbac.authentication.JwtAuthentication",
        "tables.services.rbac.authentication.ApiKeyAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}
```

**Every endpoint is authenticated by default.** You only ever *add* permission classes;
opening an endpoint requires an explicit `permission_classes = [AllowAny]` (currently only
first-setup, login, refresh, password-reset request/confirm, swagger-token).

Two authentication classes (`tables/services/rbac/authentication.py`), both global defaults:
- `JwtAuthentication` — `Authorization: Bearer <jwt>` → simplejwt (HS256, access 15 min,
  refresh 7 d, rotation + blacklist on). Custom claims: `email`, `is_superadmin`.
- `ApiKeyAuthentication` — `X-Api-Key: <key>` or `Authorization: ApiKey <key>` → delegates to
  `ApiKeyAuthenticator`, which resolves the raw key to an `ApiKey` row, then hands it to
  `PrincipalResolver` (`tables/services/rbac/api_key/principals.py`): a `system`-type key
  resolves to `SystemServicePrincipal` (superadmin-equivalent, no `email`/`pk`); a
  `user`-type key resolves to its owner. `request.user` is that principal, `request.auth`
  is the `ApiKey` row. A user key inherits the owner's live RBAC permissions per the
  `X-Organization-Id` header the caller sends — identical to that owner authenticating with
  a JWT. Key management endpoints (`/api/profile/api-keys/`, `/api/api-keys/`) are JWT-only
  (`DenyApiKeyAuth`) — see [api_keys.md](api_keys.md).

Connections that cannot carry headers (SSE, WebSocket) use single-use Redis tickets
(`TicketService`, `tables/services/rbac/ticket_service.py`): `POST /api/auth/sse-ticket/`
or `/api/auth/ws-ticket/` with JWT → 30 s single-use ticket consumed atomically via
`GETDEL`, passed as `?ticket=` on the stream URL.

Throttling: `LoginThrottle` (5/min, `ip|email` bucket) on login/swagger-token,
`PasswordResetRequestThrottle` (5/hour) on reset request, and the password-change request
endpoint reuses the login throttle.

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

`tables/services/rbac/permissions.py`. Declare on the view:

```python
class AgentViewSet(OrgScopedViewSetMixin, CopyActionMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasOrgPermission]   # order is contractual
    rbac_resource_type = ResourceType.AGENTS                   # REQUIRED
    rbac_action_map = {                                        # optional per-view map
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
(`tables/services/rbac/permission_assert.py`):

```python
org_id = OrgContextService().resolve(request=request)          # or the resolver mixin
assert_org_permission(request.user, org_id, ResourceType.FLOWS, Permission.CREATE)
```

The quickstart endpoint (`tables/views/views.py`) is the reference example.

### 5.3 Session / SSE surfaces — `assert_session_org_access`

Sessions have no org column; they are children of their graph. Non-ViewSet session
surfaces (SSE stream, get-updates, stop) authorize via
`assert_session_org_access(user, session, action)`
(`tables/services/rbac/session_access.py`): 404 when the session has no graph, then
membership + FLOWS bit check against `session.graph.org_id`. SSE resolves the user from
the single-use ticket first, then calls this.

### 5.4 Superadmin-only and global surfaces

- `IsSuperadmin` — org CRUD, cross-org user admin, grant/revoke superadmin, reset-user,
  admin password reset.
- `IsSuperadminOrReadOnly` — global singletons exposed as plain APIViews (default-config
  singletons, voice settings): any authenticated user reads, superadmin writes.
- `SuperadminWriteMixin` (`tables/views/mixins.py`) — same idea for ViewSets (global
  registry/catalog rows): safe actions need `IsAuthenticated`, write actions (plus any
  action named in `superadmin_write_actions`) need `IsSuperadmin`. Not org-scoped.

### 5.5 Service-layer guards (defense in depth)

Structural invariants are enforced inside services regardless of who the caller is, in
transactions with `SELECT FOR UPDATE`:

- `assert_not_last_active_superadmin` / `assert_not_last_org_admin` /
  `assert_role_is_assignable` / `assert_batch_preserves_org_admin`
  (`user_management_guards.py`)
- last-active-organization guard (`organization_management_service.py`)
- `RoleManagementService.assert_mutable` → `BuiltInRoleImmutableError` (403) for built-ins
- `PasswordRecoveryService.admin_reset` re-checks `is_superadmin` inside the service.

Follow the same pattern: view-level gate for the verb, service-level guard for the
invariant.

---

## 6. Row scope layer (queryset scoping)

All mixins live in `tables/views/mixins.py` and share `OrgScopedResolverMixin`
(`get_active_org_id()`). **Place the org mixin FIRST in the bases list** so its
`get_queryset`/`perform_create` wrap the concrete ViewSet's.

| Mixin | Use for | Declares | Behavior |
|---|---|---|---|
| `OrgScopedViewSetMixin` | Top-level resources owning an `org` FK (Graph, Agent, Crew, LLMConfig, SourceCollection, Label, …) | — | filters `org_id=active`, stamps `org_id` + `created_by` on create |
| `OrgScopedChildViewSetMixin` | Children scoped through a parent FK (nodes, edges, sessions, RealtimeAgent, …) | `org_filter_path = "graph__org_id"` | filters through the path; on create asserts the parent is in the active org (404 otherwise); does NOT stamp org |
| `OrgScopedHybridViewSetMixin` | Shared built-ins + per-org custom rows (LLMModel via `is_custom`, PythonCodeTool via `built_in`, …) | `global_visibility_q`, `custom_create_values` | lists built-ins OR own-org rows; creates always stamped org + forced out of the built-in subset |
| `OrgScopedQuerysetMixin` | Non-standard scope (multiple parents, hybrid-parent visibility) | `get_org_scope_q(org_id)`, optional `scope_distinct` | applies your Q |
| `OrgScopedServiceViewSetMixin` | Views delegating to services with raw ids (knowledge endpoints) | — | `get_in_active_org_or_404(model, pk, org_path=...)` helper |

`CopyActionMixin.copy` stamps `org_id=get_active_org_id()` when the host viewset is
org-scoped.

### 6.1 Serializer-level reference scoping (write isolation)

Queryset scoping protects reads; **FK references in writes** are protected by dedicated
fields (`tables/serializers/org_scoped_fields.py`):

- `OrgScopedPrimaryKeyRelatedField(queryset=..., org_lookup="org_id")` — strict targets
  (Agent, Crew, Graph, LLMConfig, RealtimeConfig, McpTool, PythonCodeToolConfig…).
  `org_lookup` accepts paths like `"crew__org_id"`.
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
  `tables/services/rbac/permission_catalog.py` (`RESOURCE_TYPE_METADATA`,
  `ACTION_METADATA`). This file is the **single source of truth** for which actions apply
  to which resource type; the FE matrix, role serializers, and bitmask↔codes conversion
  all read it.
- `GET /api/permissions/me/` (header required) — `{org_id, is_superadmin, role,
  permissions}` where `permissions` is `"*"` for superadmin or
  `{resource_type: [action_code, ...]}` with **every** catalog resource present (zero
  permissions surface as `[]`).
- Wire format is always action-code strings, never raw bitmask ints
  (`utils/permission_bitmask.py` converts both ways, filtering non-applicable bits).

### 7.3 Error envelope

`utils/exception_handler.custom_exception_handler` renders domain exceptions from
`tables/services/rbac/rbac_exceptions.py` as
`{"status_code": ..., "code": "...", "message": "..."}`. Reuse existing codes
(`org_context_required`, `org_membership_required`, `permission_denied`,
`built_in_role_immutable`, `last_org_admin`, `last_superadmin`, …) and add new exceptions
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
   `RESOURCE_TYPE_METADATA` entry + an idempotent seed migration granting bits to
   built-in roles + FE catalog pickup (automatic via the catalog endpoint).
6. **Tests** (pattern: `tests/api_tests/test_org_scoping_core.py`):
   - create lands in the active org with `created_by` stamped;
   - list returns only active-org rows;
   - cross-org detail → 404; cross-org FK reference in a write → 400 "Invalid pk";
   - viewer/member role matrix → 403 on denied verbs;
   - missing header → 400 `org_context_required`.

### 8.2 New child resource (no own org column)

No model change. ViewSet: `OrgScopedChildViewSetMixin` + `org_filter_path`
(`"graph__org_id"`, `"crew__org_id"`, `"agent__org_id"`, …) + `HasOrgPermission` with the
parent's resource type. The mixin already blocks creating a child under another org's
parent. In the serializer, the parent FK should still use `OrgScopedPrimaryKeyRelatedField`
so updates cannot re-point the child cross-org.

### 8.3 New hybrid resource (shared built-ins + org customs)

Model: `OrgScopedModel` + a discriminator flag (`built_in` or `is_custom`), `org` stays
nullable (built-ins keep `org=NULL` — do not flip NOT NULL).
ViewSet: `OrgScopedHybridViewSetMixin` with `global_visibility_q` and
`custom_create_values` (forcing new rows out of the built-in subset).
References to it from other serializers: `OrgVisiblePrimaryKeyRelatedField`.

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

| Concern | File (`src/django_app/tables/...`) |
|---|---|
| Auth backend (JWT + API key) | `services/rbac/authentication.py` |
| Login/logout/first-setup/reset-user/introspect views | `views/auth_views.py` |
| First-time setup | `services/rbac/first_setup_service.py`, `utils/superadmin_bootstrap.py` |
| Password recovery (request/confirm/admin/CLI) | `services/rbac/password_recovery_service.py` + `services/rbac/utils/*` |
| Profile + avatar + 2-step password change | `services/rbac/user_profile_service.py`, `views/user_profile_views.py` |
| Org CRUD (superadmin) | `services/rbac/organization_management_service.py`, `views/organization_admin_views.py` |
| User & membership admin | `services/rbac/user_management_service.py`, `user_management_guards.py`, `views/user_management_views.py` |
| Roles read + immutability guard | `services/rbac/role_management_service.py`, `views/role_admin_views.py` |
| Permission gate (ViewSet) | `services/rbac/permissions.py` (`HasOrgPermission`, `IsSuperadmin`, `IsSuperadminOrReadOnly`) |
| Permission gate (APIView) | `services/rbac/permission_assert.py` |
| Session/SSE authorization | `services/rbac/session_access.py`, `views/sse_views.py` |
| Org resolution | `services/rbac/org_context_service.py` |
| Effective permissions + resolver | `services/rbac/effective_permissions.py`, `permission_resolver.py` |
| Action maps & catalog | `services/rbac/permission_action_map.py`, `permission_catalog.py` |
| Bitmask helpers | `services/rbac/utils/permission_bitmask.py` |
| SSE/WS tickets | `services/rbac/ticket_service.py` |
| Queryset mixins | `views/mixins.py` |
| Serializer org fields | `serializers/org_scoped_fields.py` |
| Domain exceptions | `services/rbac/rbac_exceptions.py` |
| Throttles | `throttles.py` |
| Backfill helper for migrations | `migrations/_helpers.py` (`assign_default_org`) |
| Storage org enforcement | `views/storage_views.py`, `services/storage_service/manager.py` |

Reference test suites: `tests/api_tests/test_rbac_auth.py`,
`test_rbac_user_management.py`, `test_rbac_permission_enforcement.py`,
`test_rbac_organization_management.py`, `test_rbac_user_profile.py`,
`test_org_scoping_core.py`, `tests/services_tests/test_permission_resolver.py`.
