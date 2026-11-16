import { HttpClient, HttpHeaders, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import {
    ActionCode,
    BulkDeleteOptions,
    BulkDeleteResponse,
    ResourceCode,
    SystemOneConfig,
    SystemOneConfigWrite,
} from '@shared/models';
import { bulkDeleteParams } from '@shared/utils';
import { map, Observable } from 'rxjs';

import { withPermission } from '../../../core/http/permission-context';
import { ApiGetRequest } from '../../../core/models/api-request.model';
import { ConfigService } from '../../../services/config';

@Injectable({ providedIn: 'root' })
export class SystemOneConfigService {
    private readonly http = inject(HttpClient);
    private readonly configService = inject(ConfigService);
    private readonly headers = new HttpHeaders({ 'Content-Type': 'application/json' });

    private get apiUrl(): string {
        return this.configService.apiUrl + 'system-one-configs/';
    }

    getAll(): Observable<SystemOneConfig[]> {
        return this.http
            .get<ApiGetRequest<SystemOneConfig>>(this.apiUrl, {
                headers: this.headers,
                params: new HttpParams().set('limit', '1000'),
                context: withPermission<ApiGetRequest<SystemOneConfig>>(ResourceCode.LlmConfigs, ActionCode.Read, {
                    count: 0,
                    next: null,
                    previous: null,
                    results: [],
                }),
            })
            .pipe(map((response) => response.results));
    }

    create(data: SystemOneConfigWrite): Observable<SystemOneConfig> {
        return this.http.post<SystemOneConfig>(this.apiUrl, data, { headers: this.headers });
    }

    update(id: number, data: Partial<SystemOneConfigWrite>): Observable<SystemOneConfig> {
        return this.http.patch<SystemOneConfig>(`${this.apiUrl}${id}/`, data, { headers: this.headers });
    }

    bulkDelete(ids: number[], options: BulkDeleteOptions = {}): Observable<BulkDeleteResponse> {
        return this.http.post<BulkDeleteResponse>(
            `${this.apiUrl}bulk-delete/`,
            { ids },
            { params: bulkDeleteParams(options) }
        );
    }
}
