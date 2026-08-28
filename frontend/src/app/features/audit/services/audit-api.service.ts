import { HttpClient, HttpContext } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable, switchMap } from 'rxjs';

import { SKIP_AUTH_HEADER_OVERRIDE } from '../../../core/interceptors/skip-auth-header-override.context';
import { SKIP_FORBIDDEN_RELOAD } from '../../../core/interceptors/skip-forbidden-reload.context';
import { ConfigService } from '../../../services/config';
import { SessionSearchRequest, SessionSearchResponse } from '../models/audit-session.models';
import { AuditTokenService } from './audit-token.service';

@Injectable({ providedIn: 'root' })
export class AuditApiService {
    private http = inject(HttpClient);
    private auditTokenService = inject(AuditTokenService);
    private configService = inject(ConfigService);

    private get sessionsSearchUrl(): string {
        return `${this.configService.auditorUrl}api/audit/sessions/search`;
    }

    searchSessions(request: SessionSearchRequest): Observable<SessionSearchResponse> {
        // authInterceptor overwrites Authorization on every request by default - this one must
        // keep the audit-scoped token from AuditTokenService instead of the regular user JWT.
        // A 403 here means "this org has no AUDIT permission for you" - a permanent per-role
        // restriction, not stale cached permissions worth reloading the app over.
        const context = new HttpContext().set(SKIP_FORBIDDEN_RELOAD, true).set(SKIP_AUTH_HEADER_OVERRIDE, true);
        return this.auditTokenService.getToken().pipe(
            switchMap((token) =>
                this.http.post<SessionSearchResponse>(this.sessionsSearchUrl, request, {
                    headers: { Authorization: `Bearer ${token}` },
                    context,
                })
            )
        );
    }
}
