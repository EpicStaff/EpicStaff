import { HttpClient, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { ActionCode, ApiKeyStatus, GetApiKeyWithOwnerResponse, ResourceCode } from '@shared/models';
import { Observable } from 'rxjs';

import { withCrossOrgPermission } from '../../../../core/http/permission-context';
import { ApiGetRequest } from '../../../../core/models/api-request.model';
import { ConfigService } from '../../../../services/config';

export interface AdminApiKeysListParams {
    /** Filter by owner user id. */
    user?: number;
    /** Filter by key status. */
    status?: ApiKeyStatus;
    /** Free-text search on key name / prefix. Does NOT match owner name or email —
     *  filter by owner via the `user` param instead. */
    search?: string;
    /** Cross-org scoping. Sent as comma-separated `?org_ids=`. Empty/omitted means "every org
     *  the caller can read in". Passing an org the caller cannot read causes a 403. */
    orgIds?: number[];
}

@Injectable({
    providedIn: 'root',
})
export class AdminApiKeysService {
    private readonly configService = inject(ConfigService);
    private readonly http = inject(HttpClient);

    private get apiUrl(): string {
        return this.configService.apiUrl + 'admin/api-keys/';
    }

    getApiKeys(params: AdminApiKeysListParams = {}): Observable<ApiGetRequest<GetApiKeyWithOwnerResponse>> {
        let httpParams = new HttpParams();
        if (params.user != null) httpParams = httpParams.set('user', params.user);
        if (params.status) httpParams = httpParams.set('status', params.status);
        if (params.search) httpParams = httpParams.set('search', params.search);
        if (params.orgIds?.length) httpParams = httpParams.set('org_ids', params.orgIds.join(','));

        return this.http.get<ApiGetRequest<GetApiKeyWithOwnerResponse>>(this.apiUrl, {
            params: httpParams,
            context: withCrossOrgPermission<ApiGetRequest<GetApiKeyWithOwnerResponse>>(
                ResourceCode.ApiKeys,
                ActionCode.Read,
                { count: 0, next: null, previous: null, results: [] }
            ),
        });
    }

    /** DELETE /api/admin/api-keys/{id}/ — authorised by `api_keys` delete. */
    deleteApiKey(id: number): Observable<void> {
        return this.http.delete<void>(`${this.apiUrl}${id}/`);
    }

    /** POST /api/admin/api-keys/{id}/revoke/ — retires the key; also authorised by `api_keys` delete. */
    revokeApiKey(id: number): Observable<GetApiKeyWithOwnerResponse> {
        return this.http.post<GetApiKeyWithOwnerResponse>(`${this.apiUrl}${id}/revoke/`, {});
    }
}
