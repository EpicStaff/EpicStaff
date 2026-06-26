import { HttpClient } from '@angular/common/http';
import { inject, Injectable, signal } from '@angular/core';
import { ActionCode, ActivePermissions, CatalogResponse, ResourceCode } from '@shared/models';
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

    private readonly _catalog = signal<CatalogResponse | null>(null);
    readonly catalog = this._catalog.asReadonly();

    setActivePermissions(p: ActivePermissions | null): void {
        this._active.set(p);
    }

    can(resource: ResourceCode, action: ActionCode): boolean {
        const p = this._active();
        if (p === null) return false;
        if (p.is_superadmin) return true;
        if (p.permissions === '*') return true;
        const actions = p.permissions[resource];
        return Array.isArray(actions) && actions.includes(action);
    }

    get isSuperadmin(): boolean {
        return this._active()?.is_superadmin === true;
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
        return this.http
            .get<ActivePermissions>(`${this.baseUrl}me/`)
            .pipe(tap((permissions) => this._active.set(permissions)));
    }

    clear(): void {
        this._active.set(null);
        this._catalog.set(null);
    }
}
