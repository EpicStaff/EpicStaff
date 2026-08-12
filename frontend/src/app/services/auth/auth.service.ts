import { HttpClient } from '@angular/common/http';
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

    private readonly accessKey = 'auth.access';

    private refreshInProgress$: Observable<string | null> | null = null;
    private statusCache$: Observable<FirstSetupStatus> | null = null;

    // ID of the organization created during initial superadmin setup
    defaultOrgId = signal<number | null>(null);

    private readonly accessTokenSignal = signal<string | null>(this.getCookie(this.accessKey));
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
                })
            );
    }

    login(email: string, password: string, rememberMe: boolean = false): Observable<boolean> {
        this.deleteLegacyRefreshCookie();
        return this.http
            .post<AccessToken>(`${this.baseUrl}login/`, { email, password }, { withCredentials: true })
            .pipe(
                tap((tokens) => this.storeAccessToken(tokens.access, rememberMe)),
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

        this.deleteLegacyRefreshCookie();

        this.refreshInProgress$ = this.http
            .post<AccessToken>(`${this.baseUrl}refresh/`, {}, { withCredentials: true })
            .pipe(
                tap((resp) => {
                    this.setCookie(this.accessKey, resp.access, this.getTokenExpiry(resp.access));
                    this.accessTokenSignal.set(resp.access);
                }),
                map((resp) => resp.access),
                catchError((err) => {
                    this.removeTokenAndNavToLogin();
                    return throwError(() => err);
                }),
                finalize(() => {
                    this.refreshInProgress$ = null;
                }),
                shareReplay(1)
            );

        return this.refreshInProgress$;
    }

    removeTokenAndNavToLogin(): void {
        this.deleteCookie(this.accessKey);
        this.deleteLegacyRefreshCookie();
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
        return this.getCookie(this.accessKey);
    }

    storeAccessToken(accessToken: string, persist: boolean = true): void {
        const accessExpiry = persist ? this.getTokenExpiry(accessToken) : undefined;
        this.setCookie(this.accessKey, accessToken, accessExpiry);
        this.accessTokenSignal.set(accessToken);
    }

    private setCookie(name: string, value: string, expires?: Date): void {
        const expStr = expires ? `; expires=${expires.toUTCString()}` : '';
        document.cookie = `${name}=${encodeURIComponent(value)}${expStr}; path=/; SameSite=Lax`;
    }

    private getCookie(name: string): string | null {
        const match = document.cookie.split('; ').find((row) => row.startsWith(`${name}=`));
        return match ? decodeURIComponent(match.split('=').slice(1).join('=')) : null;
    }

    private deleteCookie(name: string): void {
        document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/; SameSite=Lax`;
    }

    /**
     * Removes the legacy non-httpOnly `auth.refresh` cookie that older frontend versions wrote.
     * The httpOnly cookie set by the backend is not accessible from JS and stays untouched.
     */
    private deleteLegacyRefreshCookie(): void {
        const name = 'auth.refresh';
        const paths = ['/', location.pathname];
        const host = location.hostname;
        const domains = ['', host, `.${host}`];
        const expired = 'Thu, 01 Jan 1970 00:00:00 UTC';
        for (const p of paths) {
            for (const d of domains) {
                const pathAttr = `; path=${p}`;
                const domainAttr = d ? `; domain=${d}` : '';
                document.cookie = `${name}=; expires=${expired}${pathAttr}${domainAttr}; SameSite=Lax`;
            }
        }
    }

    private getTokenExpiry(token: string): Date | undefined {
        const payload = this.getTokenPayload(token);
        if (!payload?.exp) return undefined;
        return new Date(payload.exp * 1000);
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
