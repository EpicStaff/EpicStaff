import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { CreateSecretRequest, Secret } from '@shared/models';
import { map, Observable } from 'rxjs';

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
        return this.http.get<ApiGetResponse<Secret>>(this.apiUrl).pipe(map((response) => response.results));
    }

    getSecretById(id: number): Observable<Secret> {
        return this.http.get<Secret>(this.apiUrl + id + '/');
    }

    deleteSecret(id: number): Observable<void> {
        return this.http.delete<void>(this.apiUrl + id + '/');
    }
}
