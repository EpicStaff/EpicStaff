import { HttpClient, HttpContext, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { ApiKeyStatus, GetApiKeyWithOwnerResponse } from '@shared/models';
import { Observable } from 'rxjs';

import { ORG_ID_OVERRIDE } from '../../../../core/interceptors/org-id-override.context';
import { ConfigService } from '../../../../services/config';

export interface AdminApiKeysListParams {
    /** Filter by owner user id. */
    user?: number;
    /** Filter by key status. */
    status?: ApiKeyStatus;
    /** Free-text search on key name / owner. */
    search?: string;
}

@Injectable({
    providedIn: 'root',
})
export class AdminApiKeysService {
    private readonly configService = inject(ConfigService);
    private readonly http = inject(HttpClient);

    private get apiUrl(): string {
        return this.configService.apiUrl + 'api-keys/';
    }

    /**
     * @param params  Server-side filter / search params.
     * @param orgId   Org override for superadmins (passed via `ORG_ID_OVERRIDE` context token).
     *                - `undefined` (default) → interceptor uses the active org as normal.
     *                - `null`                → omit `X-Organization-Id` (cross-org view).
     *                - `number`              → use this specific org id.
     */
    getApiKeys(params: AdminApiKeysListParams = {}, orgId?: number | null): Observable<GetApiKeyWithOwnerResponse[]> {
        let httpParams = new HttpParams();
        let context = new HttpContext();

        if (params.user != null) httpParams = httpParams.set('user', params.user);
        if (params.status) httpParams = httpParams.set('status', params.status);
        if (params.search) httpParams = httpParams.set('search', params.search);

        if (orgId !== undefined) {
            context = context.set(ORG_ID_OVERRIDE, orgId);
        }

        return this.http.get<GetApiKeyWithOwnerResponse[]>(this.apiUrl, { params: httpParams, context });
    }

    deleteApiKey(id: number): Observable<void> {
        return this.http.delete<void>(`${this.apiUrl}${id}/`);
    }

    revokeApiKey(id: number): Observable<GetApiKeyWithOwnerResponse> {
        return this.http.post<GetApiKeyWithOwnerResponse>(`${this.apiUrl}${id}/revoke/`, {});
    }
}
