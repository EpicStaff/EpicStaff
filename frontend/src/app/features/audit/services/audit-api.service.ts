import { HttpClient, HttpContext, HttpResponse } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { exhaustMap, first, Observable, switchMap, timeout, timer } from 'rxjs';

import { SKIP_AUTH_HEADER_OVERRIDE } from '../../../core/interceptors/skip-auth-header-override.context';
import { SKIP_FORBIDDEN_RELOAD } from '../../../core/interceptors/skip-forbidden-reload.context';
import { ConfigService } from '../../../services/config';
import { AuditDomainName, AuditFieldValues } from '../models/audit-domain.models';
import { AuditExportRequest } from '../models/audit-session.models';
import { AuditTokenService } from './audit-token.service';

const EXPORT_POLL_INTERVAL_MS = 1_000;
const EXPORT_TIMEOUT_MS = 5 * 60_000;

@Injectable({ providedIn: 'root' })
export class AuditApiService {
    private http = inject(HttpClient);
    private auditTokenService = inject(AuditTokenService);
    private configService = inject(ConfigService);

    private getDomainUrl(domain: AuditDomainName): string {
        return `${this.configService.auditorUrl}api/audit/${domain}`;
    }

    search<TRequest, TResponse>(domain: AuditDomainName, request: TRequest): Observable<TResponse> {
        // authInterceptor overwrites Authorization on every request by default - this one must
        // keep the audit-scoped token from AuditTokenService instead of the regular user JWT.
        // A 403 here means "this org has no AUDIT permission for you" - a permanent per-role
        // restriction, not stale cached permissions worth reloading the app over.
        const context = new HttpContext().set(SKIP_FORBIDDEN_RELOAD, true).set(SKIP_AUTH_HEADER_OVERRIDE, true);
        return this.auditTokenService.getToken().pipe(
            switchMap((token) =>
                this.http.post<TResponse>(`${this.getDomainUrl(domain)}/search`, request, {
                    headers: { Authorization: `Bearer ${token}` },
                    context,
                })
            )
        );
    }

    // The distinct values of `field` recorded for the org within retention, sorted; the auditor lists at most 200.
    getFieldValues(domain: AuditDomainName, field: string): Observable<AuditFieldValues> {
        const context = new HttpContext().set(SKIP_FORBIDDEN_RELOAD, true).set(SKIP_AUTH_HEADER_OVERRIDE, true);
        return this.auditTokenService.getToken().pipe(
            switchMap((token) =>
                this.http.get<AuditFieldValues>(`${this.getDomainUrl(domain)}/values/${encodeURIComponent(field)}`, {
                    headers: { Authorization: `Bearer ${token}` },
                    context,
                })
            )
        );
    }

    startExport(domain: AuditDomainName, request: AuditExportRequest): Observable<{ job_id: string }> {
        const context = new HttpContext().set(SKIP_FORBIDDEN_RELOAD, true).set(SKIP_AUTH_HEADER_OVERRIDE, true);
        return this.auditTokenService.getToken().pipe(
            switchMap((token) =>
                this.http.post<{ job_id: string }>(`${this.getDomainUrl(domain)}/export`, request, {
                    headers: { Authorization: `Bearer ${token}` },
                    context,
                })
            )
        );
    }

    // Starts an export job and polls it until the file is ready; errors with a TimeoutError if that takes too long.
    downloadExport(domain: AuditDomainName, request: AuditExportRequest): Observable<HttpResponse<Blob>> {
        return this.startExport(domain, request).pipe(
            switchMap(({ job_id }) =>
                timer(0, EXPORT_POLL_INTERVAL_MS).pipe(
                    exhaustMap(() => this.getExportFile(domain, job_id)),
                    first((response) => response.status === 200)
                )
            ),
            timeout({ first: EXPORT_TIMEOUT_MS })
        );
    }

    // 202 while the export job is still running, 200 with the file once it is ready
    getExportFile(domain: AuditDomainName, jobId: string): Observable<HttpResponse<Blob>> {
        const context = new HttpContext().set(SKIP_FORBIDDEN_RELOAD, true).set(SKIP_AUTH_HEADER_OVERRIDE, true);
        return this.auditTokenService.getToken().pipe(
            switchMap((token) =>
                this.http.get(`${this.getDomainUrl(domain)}/export/${encodeURIComponent(jobId)}`, {
                    headers: { Authorization: `Bearer ${token}` },
                    context,
                    responseType: 'blob',
                    observe: 'response',
                })
            )
        );
    }
}
