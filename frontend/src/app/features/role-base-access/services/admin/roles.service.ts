import { HttpClient, HttpParams } from '@angular/common/http';
import { inject, Injectable, signal } from '@angular/core';
import {
    CreateRoleRequest,
    DeleteRolePreviewResponse,
    DeleteRoleResponse,
    GetRoleResponse,
    RolesListResponse,
    UpdateRoleRequest,
} from '@shared/models';
import { StorageService } from '@shared/services';
import { Observable, tap } from 'rxjs';

import { ConfigService } from '../../../../services/config';

export interface LoadRolesParams {
    orgIds?: number[];
    page?: number;
    pageSize?: number;
}

@Injectable({
    providedIn: 'root',
})
export class RolesService implements StorageService {
    private readonly configService = inject(ConfigService);
    private readonly http = inject(HttpClient);

    private get apiUrl(): string {
        return this.configService.apiUrl + 'admin/roles/';
    }

    /** Built-in role templates (Superadmin / Org Admin / Member / Viewer). Immutable. */
    private readonly _builtIn = signal<GetRoleResponse[]>([]);
    readonly builtInRoles = this._builtIn.asReadonly();

    /** Custom roles for the current filter, across whichever orgs the caller can read. */
    private readonly _custom = signal<GetRoleResponse[]>([]);
    readonly customRoles = this._custom.asReadonly();

    private readonly _count = signal(0);
    readonly count = this._count.asReadonly();

    loadRoles(params: LoadRolesParams = {}): Observable<RolesListResponse> {
        let httpParams = new HttpParams();
        if (params.orgIds?.length) {
            httpParams = httpParams.set('org_ids', params.orgIds.join(','));
        }
        if (params.page !== undefined) {
            httpParams = httpParams.set('page', String(params.page));
        }
        if (params.pageSize !== undefined) {
            httpParams = httpParams.set('page_size', String(params.pageSize));
        }
        return this.http.get<RolesListResponse>(this.apiUrl, { params: httpParams }).pipe(
            tap((res) => {
                this._builtIn.set(res.built_in_roles ?? []);
                this._custom.set(res.results ?? []);
                this._count.set(res.count ?? 0);
            })
        );
    }

    /** GET /api/admin/roles/{id}/ */
    getRoleById(id: number): Observable<GetRoleResponse> {
        return this.http.get<GetRoleResponse>(`${this.apiUrl}${id}/`);
    }

    /** POST /api/admin/roles/ */
    createRole(dto: CreateRoleRequest): Observable<GetRoleResponse> {
        return this.http
            .post<GetRoleResponse>(this.apiUrl, dto)
            .pipe(tap((role) => this._custom.update((list) => [...list, role])));
    }

    /** PATCH /api/admin/roles/{id}/ */
    updateRole(id: number, dto: UpdateRoleRequest): Observable<GetRoleResponse> {
        return this.http
            .patch<GetRoleResponse>(`${this.apiUrl}${id}/`, dto)
            .pipe(
                tap((updated) => this._custom.update((list) => list.map((r) => (r.id === updated.id ? updated : r))))
            );
    }

    /** DELETE /api/admin/roles/{id}/?dry_run=true — returns members that would be reassigned. */
    previewDeleteRole(id: number): Observable<DeleteRolePreviewResponse> {
        return this.http.delete<DeleteRolePreviewResponse>(`${this.apiUrl}${id}/`, {
            params: new HttpParams().set('dry_run', 'true'),
        });
    }

    /** DELETE /api/admin/roles/{id}/ */
    deleteRole(id: number): Observable<DeleteRoleResponse> {
        return this.http
            .delete<DeleteRoleResponse>(`${this.apiUrl}${id}/`)
            .pipe(tap(() => this._custom.update((list) => list.filter((r) => r.id !== id))));
    }

    clear(): void {
        this._builtIn.set([]);
        this._custom.set([]);
        this._count.set(0);
    }
}
