import { HttpClient, HttpContext } from '@angular/common/http';
import { inject, Injectable, signal } from '@angular/core';
import { Router } from '@angular/router';
import {
    AccessToken,
    ConfirmResetPasswordRequest,
    ConfirmResetPasswordResponse,
    FirstSetupRequest,
    FirstSetupResponse,
    FirstSetupStatus,
    ResetPasswordRequest,
    ResetPasswordResponse,
} from '@shared/models';
import { AppStorageService } from '@shared/services';
import { catchError, finalize, map, Observable, of, shareReplay, tap, throwError } from 'rxjs';

import { SKIP_FORBIDDEN_RELOAD } from '../../core/interceptors/skip-forbidden-reload.context';
import { ConfigService } from '../config';
import { ProfileService } from './profile.service';

interface TokenDecoded {
    exp: number;
    iat: number;
    jti: string;
    token_type: string;
    user_id: number;
}

@Injectable({ providedIn: 'root' })
export class AuthService {
    private readonly http = inject(HttpClient);
    private readonly configService = inject(ConfigService);
    private readonly router = inject(Router);
    private readonly currentUserService = inject(ProfileService);
    private readonly appStorage = inject(AppStorageService);

    private refreshInProgress$: Observable<string | null> | null = null;
    private statusCache$: Observable<FirstSetupStatus> | null = null;

    // ID of the organization created during initial superadmin setup
    defaultOrgId = signal<number | null>(null);

    // Access token lives ONLY in memory. The refresh token lives ONLY in a
    // backend-managed HttpOnly cookie and is not accessible from JS.
    private readonly accessTokenSignal = signal<string | null>(null);
    public readonly accessToken = this.accessTokenSignal.asReadonly();

    private get baseUrl(): string {
        return `${this.configService.apiUrl}auth/`;
    }

    getStatus(): Observable<FirstSetupStatus> {
        if (!this.statusCache$) {
            this.statusCache$ = this.http.get<FirstSetupStatus>(`${this.baseUrl}first-setup/`).pipe(
                catchError((err) => {
                    this.statusCache$ = null;
                    return throwError(() => err);
                }),
                shareReplay(1)
            );
        }
        return this.statusCache$;
    }

    runSetup(payload: FirstSetupRequest): Observable<FirstSetupResponse> {
        return this.http
            .post<FirstSetupResponse>(`${this.baseUrl}first-setup/`, payload, { withCredentials: true })
            .pipe(
                tap((resp) => {
                    this.defaultOrgId.set(resp.organization.id);
                    this.statusCache$ = null;
                    this.accessTokenSignal.set(resp.access);
                })
            );
    }

    login(email: string, password: string, rememberMe: boolean): Observable<boolean> {
        return this.http
            .post<AccessToken>(
                `${this.baseUrl}login/`,
                { email, password, remember_me: rememberMe },
                { withCredentials: true }
            )
            .pipe(
                tap((tokens) => this.accessTokenSignal.set(tokens.access)),
                map(() => true)
            );
    }

    logout(): Observable<void> {
        this.currentUserService.clearCurrentUser();
        this.appStorage.clearAll();

        return this.http.post<void>(`${this.baseUrl}logout/`, {}, { withCredentials: true }).pipe(
            tap(() => this.removeTokenAndNavToLogin()),
            catchError(() => {
                this.removeTokenAndNavToLogin();
                return of(undefined);
            })
        );
    }

    invalidatetoken() {
        this.accessTokenSignal.set(
            'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoicmVmcmVzaCIsImV4cCI6MTc5MDY4NzU3NywiaWF0IjoxNzkwMDgyNzc3LCJqdGkiOiJlYzMxNWYwYWZhYzk0ZWMwYmIxNTA2OWUwZTEzMGIwYyIsInVzZXJfaWQiOjIsImVtYWlsIjoiYm9oZGFuLnN5ZGlyQGh5cy1lbnRlcnByaXNlLmNvbSIsImlzX3N1cGVyYWRtaW4iOnRydWUsInJlbWVtYmVyX21lIjpmYWxzZX0.ZHs0sQs3wFL69kHwH4y2PKHE1WiKVNMo01meDxEXDdd'
        );
    }

    requestResetPassword(data: ResetPasswordRequest): Observable<ResetPasswordResponse> {
        return this.http
            .post<ResetPasswordResponse>(`${this.baseUrl}password-reset/request/`, data)
            .pipe(catchError((err) => throwError(() => err)));
    }

    confirmResetPassword(data: ConfirmResetPasswordRequest): Observable<ConfirmResetPasswordResponse> {
        return this.http
            .post<ResetPasswordResponse>(`${this.baseUrl}password-reset/confirm/`, data)
            .pipe(catchError((err) => throwError(() => err)));
    }

    refreshToken(): Observable<string | null> {
        if (this.refreshInProgress$) {
            return this.refreshInProgress$;
        }

        const context = new HttpContext().set(SKIP_FORBIDDEN_RELOAD, true);

        this.refreshInProgress$ = this.http
            .post<AccessToken>(`${this.baseUrl}refresh/`, {}, { context, withCredentials: true })
            .pipe(
                tap((resp) => this.accessTokenSignal.set(resp.access)),
                map((resp) => resp.access),
                catchError((err) => {
                    this.accessTokenSignal.set(null);
                    return throwError(() => err);
                }),
                finalize(() => {
                    this.refreshInProgress$ = null;
                }),
                shareReplay(1)
            );

        return this.refreshInProgress$;
    }

    /**
     * Called once at application startup. Tries to restore authentication from the HttpOnly refresh cookie.
     */
    restoreSession(): Observable<void> {
        return this.refreshToken().pipe(
            catchError(() => {
                this.accessTokenSignal.set(null);
                return of(null);
            }),
            map(() => void 0)
        );
    }

    removeTokenAndNavToLogin(): void {
        this.accessTokenSignal.set(null);
        void this.router.navigate(['/login']);
    }

    isAuthenticated(): boolean {
        const token = this.getAccessToken();
        if (!token) return false;
        const payload = this.getTokenPayload(token);
        if (!payload?.exp) return false;
        const now = Math.floor(Date.now() / 1000);
        return payload.exp > now;
    }

    getAccessToken(): string | null {
        return this.accessTokenSignal();
    }

    storeAccessToken(accessToken: string): void {
        this.accessTokenSignal.set(accessToken);
    }

    private getTokenPayload(token: string): TokenDecoded | null {
        try {
            const parts = token.split('.');
            if (parts.length !== 3) return null;
            const base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
            const padded = base64 + '='.repeat((4 - (base64.length % 4)) % 4);
            const decoded = atob(padded);
            return JSON.parse(decoded);
        } catch {
            return null;
        }
    }
}
