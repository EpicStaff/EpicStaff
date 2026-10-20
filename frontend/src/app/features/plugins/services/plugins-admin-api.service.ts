import { HttpClient, HttpEvent, HttpEventType, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { filter, map, Observable } from 'rxjs';

import { ApiGetRequest } from '../../../core/models/api-request.model';
import { ConfigService } from '../../../services/config';
import {
    PackageReview,
    PluginDetail,
    PluginGrant,
    PluginSummary,
    PluginUploadEvent,
} from '../models/plugin-admin.model';

/** SuperAdmin plugin endpoints (`/api/admin/plugins/**`). Cross-org: the org interceptor sends no org header here. */
@Injectable({ providedIn: 'root' })
export class PluginsAdminApiService {
    private readonly http = inject(HttpClient);
    private readonly configService = inject(ConfigService);

    private get baseUrl(): string {
        return `${this.configService.apiUrl}admin/plugins/`;
    }

    listPlugins(): Observable<PluginSummary[]> {
        return this.http.get<PluginSummary[]>(this.baseUrl);
    }

    getPlugin(identifier: string): Observable<PluginDetail> {
        return this.http.get<PluginDetail>(this.pluginUrl(identifier));
    }

    /** Uploads a `.esplugin` package: progress while the bytes go up, then the review of the stored package. */
    uploadPackage(file: File): Observable<PluginUploadEvent> {
        const body = new FormData();
        body.append('file', file, file.name);
        return this.http
            .post<PackageReview>(`${this.baseUrl}packages/`, body, { reportProgress: true, observe: 'events' })
            .pipe(
                map((event) => toUploadEvent(event)),
                filter((event): event is PluginUploadEvent => event !== null)
            );
    }

    getPackageReview(packageId: number): Observable<PackageReview> {
        return this.http.get<PackageReview>(`${this.baseUrl}packages/${packageId}/review/`);
    }

    approvePackage(packageId: number, untrustedAcknowledged: boolean): Observable<PluginDetail> {
        return this.http.post<PluginDetail>(`${this.baseUrl}packages/${packageId}/approve/`, {
            untrusted_acknowledged: untrustedAcknowledged,
        });
    }

    rejectPackage(packageId: number): Observable<void> {
        return this.http.post<void>(`${this.baseUrl}packages/${packageId}/reject/`, null);
    }

    /** One page of the plugin's grants, sorted by organization name. */
    listGrants(identifier: string, page: number, pageSize: number): Observable<ApiGetRequest<PluginGrant>> {
        const params = new HttpParams().set('page', String(page)).set('page_size', String(pageSize));
        return this.http.get<ApiGetRequest<PluginGrant>>(`${this.pluginUrl(identifier)}grants/`, { params });
    }

    createGrant(identifier: string, organizationId: number): Observable<PluginGrant> {
        return this.http.post<PluginGrant>(`${this.pluginUrl(identifier)}grants/`, { organization_id: organizationId });
    }

    private pluginUrl(identifier: string): string {
        return `${this.baseUrl}${encodeURIComponent(identifier)}/`;
    }
}

function toUploadEvent(event: HttpEvent<PackageReview>): PluginUploadEvent | null {
    if (event.type === HttpEventType.UploadProgress) {
        return { kind: 'progress', loaded: event.loaded, total: event.total ?? null };
    }
    if (event.type === HttpEventType.Response && event.body) {
        return { kind: 'done', review: event.body };
    }
    return null;
}
