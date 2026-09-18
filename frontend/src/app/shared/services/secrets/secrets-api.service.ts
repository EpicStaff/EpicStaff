import { HttpClient, HttpContext } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { CreateSecretRequest, Secret, SecretUsageResponse } from '@shared/models';
import { map, Observable } from 'rxjs';

import { SKIP_FORBIDDEN_RELOAD } from '../../../core/interceptors/skip-forbidden-reload.context';
import { ConfigService } from '../../../services/config';
import { ApiGetResponse } from '../transcription-llms/transcription-models.service';

@Injectable({
    providedIn: 'root',
})
export class SecretsApiService {
    private configService = inject(ConfigService);
    private http = inject(HttpClient);

    private get apiUrl(): string {
        return this.configService.apiUrl + 'secrets/';
    }

    createSecret(dto: CreateSecretRequest): Observable<Secret> {
        return this.http.post<Secret>(this.apiUrl, dto);
    }

    getSecrets(): Observable<Secret[]> {
        // Fetched by every secret picker (node panels, tool dialogs) regardless of the viewer's
        // role — a member/viewer legitimately has no access to this endpoint, and that's a
        // permanent per-role restriction, not a sign of stale permissions worth reloading over.
        const context = new HttpContext().set(SKIP_FORBIDDEN_RELOAD, true);
        return this.http
            .get<ApiGetResponse<Secret>>(this.apiUrl, { context })
            .pipe(map((response) => response.results));
    }

    getSecretById(id: number): Observable<Secret> {
        return this.http.get<Secret>(this.apiUrl + id + '/');
    }

    getSecretUsage(id: number): Observable<SecretUsageResponse> {
        return this.http.get<SecretUsageResponse>(this.apiUrl + id + '/usage/');
    }

    deleteSecret(id: number): Observable<void> {
        return this.http.delete<void>(this.apiUrl + id + '/');
    }
}
