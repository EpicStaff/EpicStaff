import { HttpClient, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { ActionCode, ResourceCode } from '@shared/models';
import { map, Observable } from 'rxjs';

import { withPermission } from '../../../core/http/permission-context';
import { ApiGetRequest } from '../../../core/models/api-request.model';
import { ImportResult } from '../../../core/models/import-result.model';
import { ConfigService } from '../../../services/config';
import { AuditDomainName } from '../models/audit-domain.models';
import { AuditPreset, AuditPresetBody, AuditPresetChanges } from '../models/audit-preset.models';

const EMPTY_PRESETS_PAGE: ApiGetRequest<AuditPreset> = { count: 0, next: null, previous: null, results: [] };

const DOMAIN_RESOURCES: Record<AuditDomainName, ResourceCode> = {
    sessions: ResourceCode.Audit,
    user_actions: ResourceCode.UserAudit,
};

@Injectable({ providedIn: 'root' })
export class AuditPresetsApiService {
    private readonly http = inject(HttpClient);
    private readonly configService = inject(ConfigService);

    private get baseUrl(): string {
        return `${this.configService.apiUrl}audit-filter-presets/`;
    }

    public getPresets(domain: AuditDomainName): Observable<AuditPreset[]> {
        const params = this.domainParams(domain).set('limit', '1000');
        return this.http
            .get<ApiGetRequest<AuditPreset>>(this.baseUrl, {
                params,
                context: withPermission(DOMAIN_RESOURCES[domain], ActionCode.Read, EMPTY_PRESETS_PAGE),
            })
            .pipe(map((page) => page.results));
    }

    public createPreset(
        domain: AuditDomainName,
        name: string,
        filterBody: AuditPresetBody,
        isShared: boolean
    ): Observable<AuditPreset> {
        return this.http.post<AuditPreset>(
            this.baseUrl,
            { name, filter_body: filterBody, is_shared: isShared },
            {
                params: this.domainParams(domain),
            }
        );
    }

    public updatePreset(domain: AuditDomainName, id: number, changes: AuditPresetChanges): Observable<AuditPreset> {
        return this.http.patch<AuditPreset>(`${this.baseUrl}${id}/`, changes, { params: this.domainParams(domain) });
    }

    public duplicatePreset(domain: AuditDomainName, id: number, isShared: boolean): Observable<AuditPreset> {
        return this.http.post<AuditPreset>(
            `${this.baseUrl}${id}/copy/`,
            { is_shared: isShared },
            { params: this.domainParams(domain) }
        );
    }

    public deletePreset(domain: AuditDomainName, id: number): Observable<void> {
        return this.http.delete<void>(`${this.baseUrl}${id}/`, { params: this.domainParams(domain) });
    }

    public exportPreset(domain: AuditDomainName, id: number): Observable<Blob> {
        return this.http.get(`${this.baseUrl}${id}/export/`, {
            params: this.domainParams(domain),
            responseType: 'blob',
        });
    }

    public exportPresets(domain: AuditDomainName, ids: number[]): Observable<Blob> {
        return this.http.post(
            `${this.baseUrl}export/`,
            { ids },
            { params: this.domainParams(domain), responseType: 'blob' }
        );
    }

    public importPresets(domain: AuditDomainName, file: File): Observable<ImportResult> {
        const formData = new FormData();
        formData.append('file', file);
        return this.http.post<ImportResult>(`${this.baseUrl}import/`, formData, { params: this.domainParams(domain) });
    }

    private domainParams(domain: AuditDomainName): HttpParams {
        return new HttpParams().set('domain', domain);
    }
}
