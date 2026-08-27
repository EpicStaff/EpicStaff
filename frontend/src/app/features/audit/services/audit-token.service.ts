import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { catchError, finalize, map, Observable, of, shareReplay, switchMap, tap, throwError } from 'rxjs';

import { AuthService } from '../../../services/auth/auth.service';
import { ConfigService } from '../../../services/config';

interface AuditTokenResponse {
    token: string;
    expires_in: number;
}

@Injectable({ providedIn: 'root' })
export class AuditTokenService {
    private http = inject(HttpClient);
    private authService = inject(AuthService);
    private configService = inject(ConfigService);

    private static readonly REFRESH_MARGIN_MS = 30_000;

    private cachedToken: string | null = null;
    private expiresAt = 0;
    private pending$: Observable<string> | null = null;

    private get tokenUrl(): string {
        return `${this.configService.apiUrl}audit/token/`;
    }

    getToken(): Observable<string> {
        if (this.cachedToken && Date.now() < this.expiresAt - AuditTokenService.REFRESH_MARGIN_MS) {
            return of(this.cachedToken);
        }
        if (this.pending$) {
            return this.pending$;
        }

        const accessToken = this.authService.getAccessToken();
        if (!accessToken) return throwError(() => new Error('No access token available'));

        this.pending$ = this.mintToken(accessToken).pipe(
            catchError((err: HttpErrorResponse) => {
                if (err.status !== 401) return throwError(() => err);
                return this.authService
                    .refreshToken()
                    .pipe(switchMap((newToken) => (newToken ? this.mintToken(newToken) : throwError(() => err))));
            }),
            tap(({ token, expires_in }) => {
                this.cachedToken = token;
                this.expiresAt = Date.now() + expires_in * 1000;
            }),
            map(({ token }) => token),
            catchError((err) => {
                this.cachedToken = null;
                this.expiresAt = 0;
                return throwError(() => err);
            }),
            finalize(() => (this.pending$ = null)),
            shareReplay(1)
        );

        return this.pending$;
    }

    private mintToken(accessToken: string): Observable<AuditTokenResponse> {
        return this.http.post<AuditTokenResponse>(
            this.tokenUrl,
            {},
            { headers: { Authorization: `Bearer ${accessToken}` } }
        );
    }
}
