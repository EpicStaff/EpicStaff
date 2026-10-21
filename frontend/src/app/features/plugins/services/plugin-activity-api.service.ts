import { HttpClient, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ApiGetRequest } from '../../../core/models/api-request.model';
import { ConfigService } from '../../../services/config';
import {
    OrganizationServiceAccount,
    PluginActivityEvent,
    PluginActivityQuery,
    PluginAdminActivityQuery,
} from '../models/plugin-activity.model';

/**
 * What plugins did and what was done to them, newest first. The organization endpoints answer for the active
 * organization (the org interceptor adds its header) and need `audit: read`; the admin endpoint is the SuperAdmin's
 * cross-organization view of one plugin.
 */
@Injectable({ providedIn: 'root' })
export class PluginActivityApiService {
    private readonly http = inject(HttpClient);
    private readonly configService = inject(ConfigService);

    /** One page of the active organization's plugin events; never events of the whole deployment. */
    listOrganizationActivity(query: PluginActivityQuery): Observable<ApiGetRequest<PluginActivityEvent>> {
        let params = pageParams(query.page, query.pageSize);
        if (query.plugin) params = params.set('plugin', query.plugin);
        if (query.action) params = params.set('action', query.action);
        return this.http.get<ApiGetRequest<PluginActivityEvent>>(`${this.configService.apiUrl}plugins/activity/`, {
            params,
        });
    }

    /** The plugins with a backend acting in the active organization, sorted by plugin name. */
    listOrganizationServiceAccounts(): Observable<OrganizationServiceAccount[]> {
        return this.http.get<OrganizationServiceAccount[]>(`${this.configService.apiUrl}plugins/service-accounts/`);
    }

    /** One page of a plugin's events in every organization, and of the whole deployment. */
    listPluginActivity(
        identifier: string,
        query: PluginAdminActivityQuery
    ): Observable<ApiGetRequest<PluginActivityEvent>> {
        let params = pageParams(query.page, query.pageSize);
        if (query.organizationId !== null && query.organizationId !== undefined) {
            params = params.set('organization_id', String(query.organizationId));
        }
        if (query.action) params = params.set('action', query.action);
        return this.http.get<ApiGetRequest<PluginActivityEvent>>(
            `${this.configService.apiUrl}admin/plugins/${encodeURIComponent(identifier)}/activity/`,
            { params }
        );
    }
}

function pageParams(page: number, pageSize: number): HttpParams {
    return new HttpParams().set('page', String(page)).set('page_size', String(pageSize));
}
