import { HttpClient } from '@angular/common/http';
import { computed, inject, Injectable, signal } from '@angular/core';
import {
    GetMeResponse,
    PasswordChangeConfirmRequest,
    PasswordChangeVerifyRequest,
    PasswordChangeVerifyResponse,
    TokenPair,
    UpdateMeRequest,
    UserRole,
} from '@shared/models';
import { AppStorageService } from '@shared/services';
import { map, Observable, of, switchMap } from 'rxjs';
import { tap } from 'rxjs/operators';

import { ROLE_LABELS } from '../../features/role-base-access/constants/role-labels.constant';
import { ConfigService } from '../config';
import { ActiveOrgService } from './active-org.service';
import { PermissionsService } from './permissions.service';

@Injectable({
    providedIn: 'root',
})
export class ProfileService {
    private readonly http = inject(HttpClient);
    private readonly configService = inject(ConfigService);
    private readonly activeOrgService = inject(ActiveOrgService);
    private readonly permissionsService = inject(PermissionsService);
    private readonly appStorageService = inject(AppStorageService);

    private get baseUrl(): string {
        return `${this.configService.apiUrl}profile/`;
    }

    private readonly currentUser = signal<GetMeResponse | null>(null);
    currentUserSignal = this.currentUser.asReadonly();

    isMeSuperAdmin = computed(() => this.currentUser()?.is_superadmin ?? false);

    systemRole = computed(() => {
        const user = this.currentUser();
        if (!user) return '—';
        if (user.is_superadmin) return ROLE_LABELS[UserRole.SUPER_ADMIN];
        const highestRole = user.memberships.reduce<UserRole | null>(
            (best, m) => (best === null || m.role.id < best ? (m.role.id as UserRole) : best),
            null
        );
        return highestRole !== null ? (ROLE_LABELS[highestRole] ?? '—') : '—';
    });

    /** Simple single fetch — use for refreshing profile data mid-session. */
    getCurrentUser(): Observable<GetMeResponse> {
        return this.http.get<GetMeResponse>(this.baseUrl).pipe(tap((user) => this.setUser(user)));
    }

    /** Bootstrap: picks active org, then fetches active permissions.
     *  Reuses cached profile if already fetched; otherwise fetches profile first.
     *  Called once by the route resolver on app load. */
    bootstrapUser(): Observable<GetMeResponse> {
        const cachedUser = this.currentUserSignal();
        const user$ = cachedUser
            ? of(cachedUser)
            : this.http.get<GetMeResponse>(this.baseUrl).pipe(tap((u) => this.setUser(u)));

        return user$.pipe(
            switchMap((user) => {
                if (user.memberships.length === 0) {
                    this.permissionsService.setActivePermissions(null);
                    return of(user);
                }

                const cachedId = this.activeOrgService.activeOrgId();
                const stillValid = cachedId !== null && user.memberships.some((m) => m.organization.id === cachedId);
                const orgId = stillValid ? cachedId! : user.memberships[0].organization.id;
                this.activeOrgService.set(orgId);

                // Fetch active permissions with X-Organization-Id header now attached by the interceptor
                return this.permissionsService.loadActivePermissions().pipe(map(() => user));
            })
        );
    }

    updateCurrentUser(dto: UpdateMeRequest): Observable<GetMeResponse> {
        return this.http.patch<GetMeResponse>(this.baseUrl, dto).pipe(tap((user) => this.setUser(user)));
    }

    updateAvatar(avatar: FormData): Observable<GetMeResponse> {
        return this.http
            .post<GetMeResponse>(`${this.baseUrl}avatar/`, avatar)
            .pipe(tap((res) => this.updateUser({ avatar_url: res.avatar_url })));
    }

    deleteAvatar(): Observable<void> {
        return this.http.delete<void>(`${this.baseUrl}avatar/`).pipe(tap(() => this.updateUser({ avatar_url: null })));
    }

    requestPasswordChange(dto: PasswordChangeVerifyRequest): Observable<PasswordChangeVerifyResponse> {
        return this.http.post<PasswordChangeVerifyResponse>(`${this.baseUrl}password-change/request/`, dto);
    }

    confirmPasswordChange(dto: PasswordChangeConfirmRequest): Observable<TokenPair> {
        return this.http.post<TokenPair>(`${this.baseUrl}password-change/confirm/`, dto);
    }

    /** Switches the active organization: clears all caches, sets the new org,
     *  then reloads permissions for the new org context. Order MATTERS */
    switchOrg(orgId: number): Observable<void> {
        this.appStorageService.clearAll();
        this.activeOrgService.set(orgId);
        return this.permissionsService.loadActivePermissions().pipe(map(() => undefined));
    }

    clearCurrentUser(): void {
        this.currentUser.set(null);
    }

    private setUser(user: GetMeResponse): void {
        this.currentUser.set(user);
    }

    private updateUser(partial: Partial<GetMeResponse>): void {
        const current = this.currentUser();
        if (!current) return;
        this.currentUser.set({ ...current, ...partial });
    }
}
