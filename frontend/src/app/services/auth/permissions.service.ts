import { HttpClient } from '@angular/common/http';
import { inject, Injectable, signal } from '@angular/core';
import {
    ActionCode,
    ActivePermissions,
    CatalogResponse,
    MyOrgPermissionsResponse,
    OrgCapability,
    ResourceCode,
} from '@shared/models';
import { StorageService } from '@shared/services';
import { Observable, of, tap } from 'rxjs';

import { ConfigService } from '../config';

@Injectable({
    providedIn: 'root',
})
export class PermissionsService implements StorageService {
    private readonly http = inject(HttpClient);
    private readonly configService = inject(ConfigService);

    private get baseUrl(): string {
        return `${this.configService.apiUrl}permissions/`;
    }

    private readonly _active = signal<ActivePermissions | null>(null);
    readonly active = this._active.asReadonly();

    private readonly _isSuperadmin = signal(false);

    private readonly _catalog = signal<CatalogResponse | null>(null);
    readonly catalog = this._catalog.asReadonly();

    /** Cross-org capabilities from `GET /api/permissions/me/orgs/`. */
    private readonly _orgCaps = signal<MyOrgPermissionsResponse | null>(null);
    readonly orgCaps = this._orgCaps.asReadonly();

    setActivePermissions(p: ActivePermissions | null): void {
        this._active.set(p);
    }

    setSuperadmin(value: boolean): void {
        this._isSuperadmin.set(value);
    }

    can(resource: ResourceCode, action: ActionCode): boolean {
        if (this._isSuperadmin()) return true;

        const p = this._active();
        if (p === null) return false;
        if (p.permissions === '*') return true;
        const actions = p.permissions[resource];
        return Array.isArray(actions) && actions.includes(action);
    }

    canAny(resource: ResourceCode, actions: ActionCode[]): boolean {
        return actions.some((action) => this.can(resource, action));
    }

    /** Multi-org gate: can the current user do `action` on `resource` in org `orgId`?
     *  Backed by `/me/orgs/` capabilities. Superadmin short-circuits to true. */
    canInOrg(orgId: number, resource: ResourceCode, action: ActionCode): boolean {
        if (this._isSuperadmin()) return true;
        const caps = this._orgCaps();
        const org = caps?.orgs?.find((o) => o.org.id === orgId);
        return !!org && (org.permissions[resource]?.includes(action) ?? false);
    }

    /** Cross-org gate: does the caller have `action` on `resource` in AT LEAST ONE org?
     *  Backed by `/me/orgs/` — independent of the active-org selector.
     *  Use this for cross-org pages like the workspace admin panel. */
    canInAnyOrg(resource: ResourceCode, action: ActionCode): boolean {
        if (this._isSuperadmin()) return true;
        const caps = this._orgCaps();
        return !!caps?.orgs?.some((o) => o.permissions[resource]?.includes(action) ?? false);
    }

    /** Orgs where the current user can perform `action` on `resource`.
     *  Returns `[]` for superadmins — callers should fall back to the full org list. */
    orgsWith(resource: ResourceCode, action: ActionCode): { id: number; name: string }[] {
        if (this._isSuperadmin()) return [];
        const caps = this._orgCaps();
        return (
            caps?.orgs
                ?.filter((o: OrgCapability) => o.permissions[resource]?.includes(action) ?? false)
                .map((o) => o.org) ?? []
        );
    }

    isPlatformAction(resource: ResourceCode, action: ActionCode): boolean {
        const catalog = this._catalog();
        if (!catalog) return false;
        const resType = catalog.resource_types.find((r) => r.code === resource);
        return !!resType && (resType.platform_actions ?? []).includes(action);
    }

    get isSuperadmin(): boolean {
        return this._isSuperadmin();
    }

    get roleName(): string | null {
        return this._active()?.role?.name ?? null;
    }

    /** Fetches and caches the static permissions catalog. Safe to call multiple times. */
    loadCatalog(): Observable<CatalogResponse> {
        const cached = this._catalog();
        if (cached) return of(cached);
        return this.http
            .get<CatalogResponse>(`${this.baseUrl}catalog/`)
            .pipe(tap((catalog) => this._catalog.set(catalog)));
    }

    /** Fetches the current user's permissions for the active org.
     *  Requires X-Organization-Id header (attached automatically by the interceptor). */
    loadActivePermissions(): Observable<ActivePermissions> {
        return this.http.get<ActivePermissions>(`${this.baseUrl}me/`).pipe(
            tap((permissions) => {
                this._active.set(permissions);
                this.setSuperadmin(permissions.is_superadmin);
            })
        );
    }

    /** Fetches the current user's cross-org capabilities.
     *  Does NOT use the X-Organization-Id header (excluded in the interceptor). */
    loadOrgPermissions(): Observable<MyOrgPermissionsResponse> {
        return this.http.get<MyOrgPermissionsResponse>(`${this.baseUrl}me/orgs/`).pipe(
            tap((res) => {
                this._orgCaps.set(res);
                this.setSuperadmin(res.is_superadmin);
            })
        );
    }

    /** Whether the caller can access the workspace admin panel at all.
     *  True iff superadmin, or has read on Organizations/Users/Roles/Secrets in any org. */
    canAccessWorkspace(): boolean {
        return this.resolveDefaultWorkspaceTab() !== null;
    }

    /** First workspace tab route the caller can access, or `null` if none.
     *  Superadmin → `/workspace/main`. Ordered: organizations → users → roles → api-keys. */
    resolveDefaultWorkspaceTab(): string | null {
        if (this._isSuperadmin()) return '/workspace/main';
        if (this.canInAnyOrg(ResourceCode.Organizations, ActionCode.Read)) return '/workspace/organizations';
        if (this.canInAnyOrg(ResourceCode.Users, ActionCode.Read)) return '/workspace/users';
        if (this.canInAnyOrg(ResourceCode.Roles, ActionCode.Read)) return '/workspace/roles';
        if (this.canInAnyOrg(ResourceCode.Secrets, ActionCode.Read)) return '/workspace/api-keys';
        return null;
    }

    resolveDefaultRoute(): string {
        const active = this._active();
        if (this._isSuperadmin()) return '/workspace/main';
        if (active === null) return '/unassigned';

        if (this.can(ResourceCode.Projects, ActionCode.Read)) return '/projects/my';
        if (this.can(ResourceCode.Agents, ActionCode.Read)) return '/staff';
        if (this.can(ResourceCode.Tools, ActionCode.Read)) return '/tools';
        if (this.can(ResourceCode.Flows, ActionCode.Read)) return '/flows/my';
        if (this.can(ResourceCode.KnowledgeSources, ActionCode.Read)) return '/files/knowledge-sources';
        if (this.can(ResourceCode.Files, ActionCode.Read)) return '/files/storage';

        return '/profile';
    }

    clear(): void {
        this._active.set(null);
        this._isSuperadmin.set(false);
        this._catalog.set(null);
        this._orgCaps.set(null);
    }
}
