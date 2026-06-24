# Frontend Implementation Guide — Roles & Permissions

> **Audience:** Angular FE developers integrating the new RBAC permission framework.
> **Companion docs:** [`roles_and_permissions.md`](./roles_and_permissions.md) (BE reference — payload shapes, error envelopes), [`user_profile.md`](./user_profile.md) (profile endpoint, org-switch flow), [`auth_endpoints.md`](./auth_endpoints.md) § "Active-organization header".

This guide walks through everything the FE needs to wire up to make the new permission framework work in the UI. The BE is fully live; the FE deliverables below are what unblocks the user-facing surface.

---

## TL;DR — what changed and what you have to do

### What landed on the BE

- **Permission framework.** Every authenticated user has a role per organization with a permission bitmask covering 11 resource types (Organizations, Users, Roles, Flows, Agents, Tools, Knowledge Sources, Files, Projects, LLM Configs, Secrets) and up to 5 actions per resource (Create / Read / Update / Delete / Export).
- **Active-org header.** Endpoints that need to know which workspace the caller is operating in read it from an `X-Organization-Id` request header. Missing → 400. Wrong → 403.
- **5 new endpoints.** Permission catalog, "what can I do here", role list (active-context + target-context variants), role detail.
- **Profile extended.** `GET /api/profile/` now echoes `active_organization_id` and `active_permissions` when the header is set — single round-trip workspace bootstrap.

### What the FE has to do

1. Wire an HTTP interceptor that attaches `X-Organization-Id` to every outgoing request.
2. Bootstrap the active org on login from `/api/profile/`.`memberships[]`.
3. Cache `active_permissions` in a service (signal-based recommended) and expose a `can()` helper for UI gating.
4. Build the org switcher dropdown in the profile menu.
5. Build the Role Information modal (renders the catalog × role matrix).
6. Handle mid-session 403 `org_membership_required` (the org was deactivated or the user was removed) by clearing state and prompting org re-pick.
7. Render the "no orgs yet" empty state for new users with zero memberships.

---

## Mental model — three concepts you need to internalize

### 1. Active org vs target org

There are **two** ways the BE accepts an org context:

| | Active org | Target org |
|---|---|---|
| Where it lives | `X-Organization-Id` HTTP header | URL path: `/api/admin/organizations/{org_id}/...` |
| What it means | "The workspace I'm currently working in" | "The specific org I'm administering right now" |
| When used | Resource lists, my permissions, role pickers, profile | Admin operations on a specific org (often from cross-org admin views) |
| FE responsibility | Set once via HTTP interceptor; update on org switch | Just construct the URL — header is ignored on these endpoints |

You will **almost always** be in the "active org" case. Target-org endpoints exist so a superadmin can administer org #5 while their active workspace is org #1 — they don't have to "switch" workspaces just to rename an org.

### 2. Superadmin bypass

`is_superadmin=True` users skip every permission check on the BE. The `/api/permissions/me/` response for a superadmin is:

```json
{ "is_superadmin": true, "role": null, "permissions": "*" }
```

Notice `permissions: "*"` — a literal string, not an object. Your `can()` helper has to handle both `"*"` (allow everything) and the per-resource dict shape (check the action list). See § "Permission state service" below.

Superadmins can set `X-Organization-Id` to **any** existing org id and the BE accepts it — no membership check. This is how the admin panel lets a superadmin "look into" any org.

### 3. Zero-membership users have a valid profile

A user can exist with zero `OrganizationUser` rows — an admin created them but hasn't added them to an org yet. They can:

- Log in.
- See `/api/profile/` (memberships array is empty).
- See nothing workspace-related.

They **cannot**:

- Call `/api/permissions/me/` (returns 400 — no active org to ask about).
- Call any active-context endpoint (same — 400 without header).

UX: show the profile menu and a "waiting for an admin to add you to a workspace" empty state. Do not try to set `X-Organization-Id` until `memberships[]` is non-empty.

---

## Implementation checklist (in order)

Recommend tackling these in sequence; each one unblocks the next.

- [ ] **1.** HTTP interceptor attaches `X-Organization-Id` from a service-managed `activeOrgId` source.
- [ ] **2.** `ActiveOrgService` (or extend the existing auth service) holds `activeOrgId` as a signal. Reads / writes go through a single setter that persists to localStorage.
- [ ] **3.** Bootstrap flow: on app boot, call `/api/profile/` (no header). If `memberships[]` is empty → empty-state page. Otherwise: pick last-active from localStorage if still a member, else first membership. Set `activeOrgId`. Refetch `/api/profile/` (now with header).
- [ ] **4.** `PermissionsService` caches `active_permissions` from the second `/api/profile/` call. Exposes `can(resourceType, action) → boolean`.
- [ ] **5.** Wire `*ngIf="permissions.can('flows', 'create')"` (or a `[hasPermission]` structural directive) on every UI element that creates/edits/deletes resources.
- [ ] **6.** Org switcher dropdown component in the profile menu. On change, update `activeOrgId`, refetch profile, replace cached permissions, redirect to workspace home (or refresh the current route's data).
- [ ] **7.** Global HTTP error interceptor: on `403 org_membership_required`, clear `activeOrgId`, redirect to org-picker; on `403 permission_denied`, show "you don't have access to this action" toast.
- [ ] **8.** Role Information modal: fetch `GET /api/permissions/catalog/` once at app boot (cache forever), fetch `GET /api/admin/roles/{id}/` when modal opens, render the matrix.
- [ ] **9.** Optional now / required later: superadmin "all orgs" view in the admin panel uses target-context endpoints (URL kwarg) instead of the active-org header.

---

## Section 1 — HTTP interceptor for `X-Organization-Id`

Angular 19 functional interceptor (preferred over class-based for new code):

```typescript
// active-org.interceptor.ts
import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { ActiveOrgService } from './active-org.service';

export const activeOrgInterceptor: HttpInterceptorFn = (req, next) => {
  const activeOrg = inject(ActiveOrgService);
  const orgId = activeOrg.activeOrgId();

  // Don't attach to /auth/, /first-setup/, /password-reset/* — they pre-date workspace.
  // Don't attach to /admin/organizations/{org_id}/... — those use URL kwarg.
  // For everything else, attach if we have a value.
  if (orgId && !shouldSkip(req.url)) {
    req = req.clone({
      setHeaders: { 'X-Organization-Id': String(orgId) },
    });
  }
  return next(req);
};

function shouldSkip(url: string): boolean {
  return (
    url.includes('/api/auth/') ||
    /\/admin\/organizations\/\d+\//.test(url)
  );
}
```

Register in `app.config.ts`:

```typescript
provideHttpClient(withInterceptors([activeOrgInterceptor, /* others */])),
```

**Why a skip-list?** The header is harmless on endpoints that ignore it, but skipping is cleaner and avoids accidental coupling.

---

## Section 2 — `ActiveOrgService`

Single source of truth for the active org id. Signal-based for modern Angular 19:

```typescript
// active-org.service.ts
import { Injectable, signal } from '@angular/core';

const STORAGE_KEY = 'epicstaff.activeOrgId';

@Injectable({ providedIn: 'root' })
export class ActiveOrgService {
  private readonly _activeOrgId = signal<number | null>(null);
  readonly activeOrgId = this._activeOrgId.asReadonly();

  constructor() {
    const cached = localStorage.getItem(STORAGE_KEY);
    if (cached) {
      const parsed = Number(cached);
      if (Number.isFinite(parsed)) this._activeOrgId.set(parsed);
    }
  }

  set(orgId: number | null): void {
    this._activeOrgId.set(orgId);
    if (orgId === null) {
      localStorage.removeItem(STORAGE_KEY);
    } else {
      localStorage.setItem(STORAGE_KEY, String(orgId));
    }
  }
}
```

**Don't** read `activeOrgId` directly from `localStorage` anywhere else — always go through the service so the signal stays the source of truth.

---

## Section 3 — Bootstrap flow

Runs on app boot (or after login). Two-phase: profile without header, then profile with header.

```typescript
// auth-bootstrap.service.ts
async bootstrap(): Promise<BootstrapResult> {
  // Phase 1: profile without header. Lists memberships.
  const initial = await firstValueFrom(
    this.http.get<ProfileResponse>('/api/profile/')
  );

  if (initial.memberships.length === 0) {
    return { state: 'no-memberships', profile: initial };
  }

  // Phase 2: pick active org.
  const cachedId = this.activeOrg.activeOrgId();
  const stillValid =
    cachedId !== null &&
    initial.memberships.some((m) => m.organization.id === cachedId);
  const targetId = stillValid ? cachedId! : initial.memberships[0].organization.id;
  this.activeOrg.set(targetId);

  // Phase 3: refetch profile WITH header (interceptor attaches it).
  const full = await firstValueFrom(
    this.http.get<ProfileResponse>('/api/profile/')
  );

  // active_permissions is embedded; cache it.
  this.permissions.setActivePermissions(full.active_permissions);

  return { state: 'ready', profile: full };
}
```

**Special case**: the cached `activeOrgId` is for an org the user is no longer a member of (admin removed them). The `stillValid` check above falls back to their first current membership. If you want to surface this ("you were removed from Acme Inc"), keep the cached id around and diff against the new profile to detect the change.

---

## Section 4 — `PermissionsService` + `can()` helper

```typescript
// permissions.service.ts
import { Injectable, signal } from '@angular/core';

export type ActionCode =
  | 'create' | 'read' | 'update' | 'delete'
  | 'export';

export type ResourceCode =
  | 'organizations' | 'users' | 'roles'
  | 'flows' | 'agents' | 'tools' | 'knowledge_sources'
  | 'files' | 'projects' | 'llm_configs' | 'secrets';

export interface ActivePermissions {
  is_superadmin: boolean;
  role: { id: number; name: string } | null;
  permissions: '*' | Record<string, string[]>;
}

@Injectable({ providedIn: 'root' })
export class PermissionsService {
  private readonly _active = signal<ActivePermissions | null>(null);
  readonly active = this._active.asReadonly();

  setActivePermissions(p: ActivePermissions | null): void {
    this._active.set(p);
  }

  /** Returns true iff the current user can perform `action` on `resource`
   *  in the active org. Superadmin always returns true. No active org → false. */
  can(resource: ResourceCode, action: ActionCode): boolean {
    const p = this._active();
    if (p === null) return false;
    if (p.is_superadmin) return true;
    if (p.permissions === '*') return true; // defensive — superadmin envelope
    const actions = p.permissions[resource];
    return Array.isArray(actions) && actions.includes(action);
  }

  get isSuperadmin(): boolean {
    return this._active()?.is_superadmin === true;
  }

  get roleName(): string | null {
    return this._active()?.role?.name ?? null;
  }
}
```

### Using `can()` in templates

```html
<!-- show "+ New flow" button only if user can create flows -->
<button *ngIf="permissions.can('flows', 'create')" (click)="createFlow()">
  + New flow
</button>

<!-- gray-out a delete action when the user lacks the permission -->
<button
  [disabled]="!permissions.can('flows', 'delete')"
  (click)="deleteFlow()"
>
  Delete
</button>
```

### A structural directive (optional, syntactic sugar)

```typescript
@Directive({ selector: '[hasPermission]', standalone: true })
export class HasPermissionDirective {
  private readonly tpl = inject(TemplateRef<unknown>);
  private readonly vcr = inject(ViewContainerRef);
  private readonly perms = inject(PermissionsService);

  @Input() set hasPermission(value: [ResourceCode, ActionCode]) {
    this.vcr.clear();
    if (this.perms.can(value[0], value[1])) {
      this.vcr.createEmbeddedView(this.tpl);
    }
  }
}
```

Template:

```html
<button *hasPermission="['flows', 'create']">+ New flow</button>
```

**Hide vs disable** — rule of thumb:

- **Hide** primary actions (create button, settings menu items) the user has no permission for. Don't leave them around as visual noise.
- **Disable** secondary actions inside an already-visible context (a "Delete" button in a row's action menu) so the user understands the option exists but they can't use it. Tooltip explaining why is a nice touch.

---

## Section 5 — Org switcher

Lives in the profile menu (bottom-left, per design). Renders `memberships[]` from `/api/profile/`. Logic:

```typescript
async switchOrg(newOrgId: number): Promise<void> {
  if (newOrgId === this.activeOrg.activeOrgId()) return;
  this.activeOrg.set(newOrgId);
  // Refetch profile with the new header so we get fresh active_permissions.
  const profile = await firstValueFrom(
    this.http.get<ProfileResponse>('/api/profile/')
  );
  this.permissions.setActivePermissions(profile.active_permissions);
  // Either reload the current route's data or navigate to workspace home.
  // Reload is simpler if you have a lot of resource lists.
  this.router.navigate(['/workspace'], { skipLocationChange: false });
}
```

**Single-org case**: `memberships.length === 1` → render the org name as a static label, not a dropdown.

**Inactive org currently active** (deactivated by superadmin mid-session): the next gated request returns `403 org_membership_required`. Handle it in the error interceptor (Section 7) — clear `activeOrgId`, redirect to org-picker.

---

## Section 6 — Role Information modal

Two requests:

1. `GET /api/permissions/catalog/` — once at app boot. Cache forever (it's static). Returns `actions[]` + `resource_types[]` with `applicable_actions` per resource.
2. `GET /api/admin/roles/{id}/` — when the modal opens for a specific role. Returns the role's `permissions[]` (array of `{resource_type, actions[]}`).

Render the matrix by merging:

```typescript
function renderMatrix(catalog: Catalog, role: Role): Cell[][] {
  return catalog.resource_types.map((rt) => {
    const roleEntry = role.permissions.find((p) => p.resource_type === rt.code);
    return catalog.actions.map((action) => {
      const applicable = rt.applicable_actions.includes(action.code);
      if (!applicable) return { kind: 'dash' };           // render "—"
      const checked = roleEntry?.actions.includes(action.code) ?? false;
      return { kind: 'checkbox', checked };
    });
  });
}
```

**Built-in Superadmin row is special** — the BE returns it with empty `permissions: []` because superadmin authority is the user flag, not the bitmask. Detect by `is_built_in && name === 'Superadmin'` and render every applicable cell as checked.

**`assigned_count`** — displays "N users have this role". For the Superadmin row this number is typically 0 (or low) because `is_superadmin=True` users don't necessarily have a `Superadmin` membership row. Don't surface this number for the Superadmin row, or label it "members" with a tooltip explaining that `is_superadmin` users are counted separately on the Users tab.

---

## Section 7 — Error handling

The new error envelope codes you need to handle:

| Code | Status | When | UI response |
|---|---|---|---|
| `org_context_required` | 400 | `X-Organization-Id` missing or non-integer on a header-required endpoint | Should not happen — your interceptor sets it. If it does, you have a bug (calling a gated endpoint before bootstrap completes). Log + crash to surface fast. |
| `org_membership_required` | 403 | Active org is one the user is no longer a member of (deactivated org, or admin removed them) | Clear `activeOrgId`, force `bootstrap()` to re-pick from current memberships. Toast: "Your access to this workspace was revoked." |
| `permission_denied` | 403 | User lacks the permission for the action they attempted | Toast: "You don't have permission to do that." Plus your UI should have hidden/disabled the action — this 403 indicates a UI-gating bug you should track. |
| `built_in_role_immutable` | 403 | Tried to edit/delete a built-in role (Superadmin, Org Admin, Member, Viewer) | The role-detail modal should never offer edit/delete for `is_built_in=true` rows. If you see this, fix the modal. |
| `not_authenticated` | 401 | Token expired / missing | Existing auth-refresh logic. |

Global HTTP interceptor sketch:

```typescript
export const errorInterceptor: HttpInterceptorFn = (req, next) => {
  const activeOrg = inject(ActiveOrgService);
  const permissions = inject(PermissionsService);
  const router = inject(Router);
  const toast = inject(ToastService);

  return next(req).pipe(
    catchError((err: HttpErrorResponse) => {
      const code = err.error?.code;
      if (err.status === 403 && code === 'org_membership_required') {
        activeOrg.set(null);
        permissions.setActivePermissions(null);
        toast.warn('Your access to this workspace was revoked.');
        router.navigate(['/select-workspace']);
      } else if (err.status === 403 && code === 'permission_denied') {
        toast.warn("You don't have permission to do that.");
      } else if (err.status === 400 && code === 'org_context_required') {
        // Bug: a gated call slipped through before bootstrap.
        console.error('Missing X-Organization-Id on', req.url);
      }
      return throwError(() => err);
    })
  );
};
```

---

## Section 8 — Endpoint reference (FE-side)

Full payload shapes in [`roles_and_permissions.md`](./roles_and_permissions.md). Below is the FE integration view.

### `GET /api/permissions/catalog/`

- **When to call:** once at app boot, cache forever. The catalog is static; it only changes on BE deploys.
- **No header required.**
- **Use it to:** render the Role Information matrix (rows + columns + applicable cells).

### `GET /api/permissions/me/`

- **When to call:** rarely directly — `/api/profile/` already embeds the same payload in `active_permissions`. Use this endpoint if you specifically want to refresh permissions without refetching the whole profile (e.g., long-running sessions after admin role changes).
- **Header required:** `X-Organization-Id`.
- **Use it to:** drive `can()` checks.

### `GET /api/admin/roles/`

- **When to call:** when populating a role-picker dropdown (e.g., "assign role" UI) for the active workspace.
- **Header required:** `X-Organization-Id`.
- **Returns:** built-in roles always + (once custom roles ship) that org's custom roles.

### `GET /api/admin/roles/{id}/`

- **When to call:** when the Role Information modal opens.
- **No header required** — the role row carries `org_id` and the BE self-resolves access.

### `GET /api/admin/organizations/{org_id}/roles/`

- **When to call:** rare — only superadmin "audit another org" flows in the admin panel. Most code uses `/api/admin/roles/` with the header instead.
- **Auth:** caller needs `READ` on `roles` in `{org_id}` (Superadmin and Org Admin pass by default).

### `GET /api/profile/` (extended)

- **When to call:** on every workspace bootstrap and after every org switch.
- **Header behavior:**
  - No header → returns profile with `active_organization_id: null`, `active_permissions: null`. Safe for zero-membership users.
  - Header with valid org you're a member of → embedded `active_organization_id` and `active_permissions`.
  - Header with an org you can't access → fields are `null` (NOT 403). This is the only endpoint with this soft-fail behavior.

### `/api/admin/organizations/{org_id}/users/...` (existing — gate changed)

- **No FE behavior change.** Path is the same. The BE swapped its permission class under the hood. Same 200/403 responses for the same callers.

---

## Section 9 — Common pitfalls

| Pitfall | Why it bites | Fix |
|---|---|---|
| Calling `/api/permissions/me/` without setting the header | 400 `org_context_required`. Easy to miss in test envs. | Always go through `bootstrap()` first. The interceptor is the single point that knows the header. |
| Setting `X-Organization-Id` in component code | Bypasses the interceptor — sets it once on one request, then loses it. Inconsistent state. | Only `ActiveOrgService.set()` writes the active org. Never `headers.set('X-Organization-Id', ...)` by hand. |
| Treating `permissions: '*'` as a dict | `for (const k in permissions.permissions)` iterates string characters. Crash. | Check `permissions === '*'` (or `is_superadmin === true`) **before** indexing. The `can()` helper already does this. |
| Hiding admin endpoints by checking role name (`role.name === 'Org Admin'`) | Custom roles (future) will have different names but the same permissions. Breaks the gate. | Check the permission, not the role name. `permissions.can('users', 'update')` not `roleName === 'Org Admin'`. |
| Caching active permissions across org switches without resetting | User switches from Org Admin context to Member context but UI still shows admin buttons. | Always call `permissions.setActivePermissions(...)` with the fresh value (or `null`) after every org switch. |
| Showing the org switcher dropdown to single-membership users | Looks busy / confusing. | If `memberships.length === 1`, render the name as static text. |
| Not handling the zero-membership user | A logged-in user with no org gets a broken workspace screen. | Detect `memberships.length === 0` after the first `/api/profile/` call and render the empty state. |
| Refreshing tokens but forgetting that permissions might have changed | User's role got upgraded by admin mid-session but UI still gates as old role. | After token refresh in long-lived sessions, optionally call `/api/permissions/me/` to refresh. Or just refetch `/api/profile/` periodically. |

---

## Section 10 — End-to-end walkthrough

A typical session, start to finish:

1. **App loads, no token yet.** Router redirects to `/login`.
2. **User logs in.** `POST /api/auth/login/` returns access + refresh tokens. Tokens stored.
3. **Bootstrap kicks off.** `bootstrap()` calls `GET /api/profile/` (no header — interceptor skips because `activeOrgId` is null).
4. **Profile returns with `memberships[]`.** Let's say the user has 2 memberships: `[{org: Acme, role: Org Admin}, {org: Beta, role: Member}]`. localStorage has `activeOrgId=5` (Beta's id) from last session. Still valid → set to 5.
5. **Refetch profile with header.** Interceptor now attaches `X-Organization-Id: 5`. Response includes `active_organization_id: 5`, `active_permissions: {role: {name: "Member"}, permissions: {...}}`.
6. **Permissions service caches the matrix.** UI gating signals fire — `can('flows', 'create')` returns true (Member can create flows).
7. **Router navigates to `/workspace`.** Workspace lists flows. The `GET /api/flows/` call (when that endpoint becomes org-scoped) will attach `X-Organization-Id: 5` automatically and return Beta's flows.
8. **User clicks org switcher, selects Acme.** `switchOrg(acmeId)` updates `activeOrgId`, refetches profile, replaces cached permissions (now Org Admin → can do more). Router refreshes the workspace route.
9. **An admin (in another tab) deactivates Acme.** Next gated request returns `403 org_membership_required`. Error interceptor clears `activeOrgId`, redirects to `/select-workspace` with a toast.
10. **User picks Beta again.** Cycle repeats.

---

## Appendix — Type definitions

Drop these into a shared `permissions.types.ts`:

```typescript
export type ActionCode =
  | 'create' | 'read' | 'update' | 'delete'
  | 'export';

export type ResourceCode =
  | 'organizations' | 'users' | 'roles'
  | 'flows' | 'agents' | 'tools' | 'knowledge_sources'
  | 'files' | 'projects' | 'llm_configs' | 'secrets';

export interface CatalogResponse {
  actions: { code: ActionCode; label: string; bit: number }[];
  resource_types: {
    code: ResourceCode;
    label: string;
    group: 'admin' | 'workspace' | 'config';
    description: string;
    applicable_actions: ActionCode[];
  }[];
}

export interface ActivePermissions {
  is_superadmin: boolean;
  role: { id: number; name: string } | null;
  permissions: '*' | Record<ResourceCode, ActionCode[]>;
}

export interface PermissionsMeResponse {
  org_id: number;
  is_superadmin: boolean;
  role: { id: number; name: string } | null;
  permissions: '*' | Record<ResourceCode, ActionCode[]>;
}

export interface RoleResponse {
  id: number;
  name: string;
  description: string | null;
  is_built_in: boolean;
  scope: 'global' | 'org' | string;   // "org-{id}" for custom roles
  org_id: number | null;
  assigned_count: number;
  permissions: {
    resource_type: ResourceCode;
    actions: ActionCode[];
  }[];
}

export interface MembershipNested {
  id: number;
  organization: { id: number; name: string; is_active: boolean };
  role: { id: number; name: string };
  joined_at: string;
}

export interface ProfileResponse {
  id: number;
  email: string;
  display_name: string | null;
  avatar_url: string | null;
  is_superadmin: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  memberships: MembershipNested[];
  active_organization_id: number | null;
  active_permissions: ActivePermissions | null;
}
```

---

## Glossary

- **Active org** — the workspace the user is currently working in. Lives in `X-Organization-Id` header. One value at a time.
- **Target org** — the org being administered, may differ from active org. Lives in URL path (`/api/admin/organizations/{org_id}/...`).
- **Built-in role** — Superadmin / Org Admin / Member / Viewer. Immutable (cannot be edited or deleted via API). `is_built_in=true` in role responses.
- **Custom role** — future feature. Org-scoped, editable. Coexists with built-ins in `/api/admin/roles/` once it lands.
- **Permission bitmask** — internal storage. Each action is a bit (create=1, read=2, update=4, delete=8, ...). FE never sees the integer; only action-code arrays.
- **Catalog** — the static taxonomy of resource types × applicable actions. Source of truth for "which cells of the matrix are valid".
- **Effective permissions** — the resolved set of permissions for a (user, org) pair after applying role bitmasks. Returned as either `"*"` (superadmin) or a `Record<ResourceCode, ActionCode[]>` (everyone else).

---

## Questions / contact

BE behavior questions → check the companion reference doc [`roles_and_permissions.md`](./roles_and_permissions.md). Stuck on something not covered there? File an issue and tag the RBAC owner.
