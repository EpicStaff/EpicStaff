import { HttpClient, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import {
    ActionCode,
    CreateOrganizationRequest,
    GetOrganizationResponse,
    ResourceCode,
    UpdateOrganizationRequest,
} from '@shared/models';
import { Observable } from 'rxjs';

import { withCrossOrgPermission } from '../../../../core/http/permission-context';
import { ApiGetRequest } from '../../../../core/models/api-request.model';
import { ConfigService } from '../../../../services/config';

export interface ListOrganizationsParams {
    is_active?: boolean;
    search?: string;
    ordering?: string;
    page?: number;
    page_size?: number;
}

@Injectable({
    providedIn: 'root',
})
export class AdminOrganizationsService {
    private readonly configService = inject(ConfigService);
    private readonly http = inject(HttpClient);

    private get apiUrl(): string {
        return this.configService.apiUrl + 'admin/organizations/';
    }

    createOrganization(data: CreateOrganizationRequest): Observable<GetOrganizationResponse> {
        return this.http.post<GetOrganizationResponse>(this.apiUrl, data);
    }

    /** GET /api/admin/organizations/ — paginated + permission-aware. */
    list(params: ListOrganizationsParams = {}): Observable<ApiGetRequest<GetOrganizationResponse>> {
        let httpParams = new HttpParams();
        if (params.is_active !== undefined) httpParams = httpParams.set('is_active', String(params.is_active));
        if (params.search) httpParams = httpParams.set('search', params.search);
        if (params.ordering) httpParams = httpParams.set('ordering', params.ordering);
        if (params.page !== undefined) httpParams = httpParams.set('page', String(params.page));
        if (params.page_size !== undefined) httpParams = httpParams.set('page_size', String(params.page_size));
        return this.http.get<ApiGetRequest<GetOrganizationResponse>>(this.apiUrl, {
            params: httpParams,
            context: withCrossOrgPermission<ApiGetRequest<GetOrganizationResponse>>(
                ResourceCode.Organizations,
                ActionCode.Read,
                { count: 0, next: null, previous: null, results: [] }
            ),
        });
    }

    updateOrganization(id: number, data: UpdateOrganizationRequest): Observable<GetOrganizationResponse> {
        return this.http.patch<GetOrganizationResponse>(`${this.apiUrl}${id}/`, data);
    }

    deactivateOrganization(id: number): Observable<void> {
        return this.http.post<void>(`${this.apiUrl}${id}/deactivate/`, {});
    }

    reactivateOrganization(id: number): Observable<void> {
        return this.http.post<void>(`${this.apiUrl}${id}/reactivate/`, {});
    }
}
