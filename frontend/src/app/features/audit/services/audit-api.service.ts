import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable, switchMap } from 'rxjs';

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
        return this.auditTokenService.getToken().pipe(
            switchMap((token) =>
                this.http.post<SessionSearchResponse>(this.sessionsSearchUrl, request, {
                    headers: { Authorization: `Bearer ${token}` },
                })
            )
        );
    }
}
