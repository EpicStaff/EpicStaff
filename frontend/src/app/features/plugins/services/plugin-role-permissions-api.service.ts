import { HttpClient, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ConfigService } from '../../../services/config';
import {
    PluginRolePermissionsResponse,
    PluginRolePermissionsUpdate,
    PluginRoleRowsResponse,
} from '../models/plugin-role-permissions.model';

/** The plugin rows of the Roles matrix (`/api/admin/plugin-role-permissions/**`). The org is a query parameter. */
@Injectable({ providedIn: 'root' })
export class PluginRolePermissionsApiService {
    private readonly http = inject(HttpClient);
    private readonly configService = inject(ConfigService);

    private get baseUrl(): string {
        return `${this.configService.apiUrl}admin/plugin-role-permissions/`;
    }

    /** The rows for a role about to be created in the organization. */
    getRows(orgId: number): Observable<PluginRoleRowsResponse> {
        const params = new HttpParams().set('org_id', String(orgId));
        return this.http.get<PluginRoleRowsResponse>(`${this.baseUrl}rows/`, { params });
    }

    /** A role's rows and grants; `orgId` only matters for a built-in role. */
    getRolePermissions(roleId: number, orgId?: number): Observable<PluginRolePermissionsResponse> {
        const params = orgId === undefined ? undefined : new HttpParams().set('org_id', String(orgId));
        return this.http.get<PluginRolePermissionsResponse>(`${this.baseUrl}${roleId}/`, { params });
    }

    /** Replaces the role's plugin permissions with `update`. */
    updateRolePermissions(
        roleId: number,
        update: PluginRolePermissionsUpdate
    ): Observable<PluginRolePermissionsResponse> {
        return this.http.put<PluginRolePermissionsResponse>(`${this.baseUrl}${roleId}/`, update);
    }
}
