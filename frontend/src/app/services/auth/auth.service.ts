import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Router } from '@angular/router';
import { FirstSetupRequest, FirstSetupResponse, FirstSetupStatus, GetMeResponse } from '@shared/models';
import { catchError, finalize, map, Observable, of, shareReplay, tap, throwError } from 'rxjs';

import { ConfigService } from '../config';

interface TokenPair {
    access: string;
    refresh: string;
}

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

    private readonly accessKey = 'auth.access';
    private readonly refreshKey = 'auth.refresh';

    private refreshInProgress$: Observable<string | null> | null = null;
    private statusCache$: Observable<FirstSetupStatus> | null = null;

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
        return this.http.post<FirstSetupResponse>(`${this.baseUrl}first-setup/`, payload).pipe(
            tap(() => {
                this.statusCache$ = null;
            })
        );
    }

    login(email: string, password: string, rememberMe: boolean = false): Observable<boolean> {
        return this.http.post<TokenPair>(`${this.baseUrl}login/`, { email, password }).pipe(
            tap((tokens) => this.storeTokens(tokens, rememberMe)),
            map(() => true)
        );
    }

    logout(): Observable<void> {
        const refreshToken = this.getRefreshToken();

        if (!refreshToken) {
            this.removeTokensAndNavToLogin();
            return of();
        }

        return this.http.post<void>(`${this.baseUrl}logout/`, { refresh: refreshToken }).pipe(
            tap(() => this.removeTokensAndNavToLogin()),
            catchError((err) => throwError(() => err))
        );
    }

    refreshToken(): Observable<string | null> {
        if (this.refreshInProgress$) {
            return this.refreshInProgress$;
        }

        const refresh = this.getRefreshToken();
        if (!refresh) return of(null);

        this.refreshInProgress$ = this.http.post<TokenPair>(`${this.baseUrl}refresh/`, { refresh }).pipe(
            tap((resp) => {
                this.setCookie(this.accessKey, resp.access, this.getTokenExpiry(resp.access));
                if (resp.refresh) {
                    this.setCookie(this.refreshKey, resp.refresh, this.getTokenExpiry(resp.refresh));
                }
            }),
            map((resp) => resp.access),
            catchError((err) => {
                this.removeTokensAndNavToLogin();
                return throwError(() => err);
            }),
            finalize(() => {
                this.refreshInProgress$ = null;
            }),
            shareReplay(1)
        );

        return this.refreshInProgress$;
    }

    getCurrentUser(): Observable<GetMeResponse> {
        return this.http.get<GetMeResponse>(`${this.baseUrl}me/`);
    }

    removeTokensAndNavToLogin(): void {
        this.deleteCookie(this.accessKey);
        this.deleteCookie(this.refreshKey);

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

    getRefreshToken(): string | null {
        return this.getCookie(this.refreshKey);
    }

    storeTokens(tokens: TokenPair, persist: boolean = true): void {
        const accessExpiry = persist ? this.getTokenExpiry(tokens.access) : undefined;
        const refreshExpiry = persist ? this.getTokenExpiry(tokens.refresh) : undefined;
        this.setCookie(this.accessKey, tokens.access, accessExpiry);
        this.setCookie(this.refreshKey, tokens.refresh, refreshExpiry);
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
