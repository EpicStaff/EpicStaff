import { HttpClient, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { ActionCode, ResourceCode } from '@shared/models';
import { map, Observable } from 'rxjs';

import { withPermission } from '../../../core/http/permission-context';
import { ApiGetRequest } from '../../../core/models/api-request.model';
import { ConfigService } from '../../../services/config';
import { AuditPreset, AuditPresetBody } from '../models/audit-preset.models';

const EMPTY_PRESETS_PAGE: ApiGetRequest<AuditPreset> = { count: 0, next: null, previous: null, results: [] };

@Injectable({ providedIn: 'root' })
export class AuditPresetsApiService {
    private readonly http = inject(HttpClient);
    private readonly configService = inject(ConfigService);

    private get baseUrl(): string {
        return `${this.configService.apiUrl}audit-filter-presets/`;
    }

    public getPresets(): Observable<AuditPreset[]> {
        const params = new HttpParams().set('limit', '1000');
        return this.http
            .get<ApiGetRequest<AuditPreset>>(this.baseUrl, {
                params,
                context: withPermission(ResourceCode.Audit, ActionCode.Read, EMPTY_PRESETS_PAGE),
            })
            .pipe(map((page) => page.results));
    }

    public createPreset(name: string, filterBody: AuditPresetBody): Observable<AuditPreset> {
        return this.http.post<AuditPreset>(this.baseUrl, { name, filter_body: filterBody });
    }

    public updatePreset(
        id: number,
        changes: { name?: string; filter_body?: AuditPresetBody }
    ): Observable<AuditPreset> {
        return this.http.patch<AuditPreset>(`${this.baseUrl}${id}/`, changes);
    }

    public duplicatePreset(id: number): Observable<AuditPreset> {
        return this.http.post<AuditPreset>(`${this.baseUrl}${id}/copy/`, {});
    }

    public deletePreset(id: number): Observable<void> {
        return this.http.delete<void>(`${this.baseUrl}${id}/`);
    }
}
