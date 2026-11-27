import { HttpClient, HttpContext } from '@angular/common/http';
import { computed, inject, Injectable, signal } from '@angular/core';
import { ROLE_LABELS } from '@shared/constants';
import {
    AccessToken,
    CreateApiKeyRequest,
    CreateApiKeyResponse,
    EMPTY_SHORTCUT_SETTINGS,
    GetMeResponse,
    GetMyApiKeyResponse,
    Organization,
    PasswordChangeConfirmRequest,
    PasswordChangeVerifyRequest,
    PasswordChangeVerifyResponse,
    PreferenceSection,
    ShortcutSettings,
    UpdateMeRequest,
    UserPreferences,
    UserRole,
} from '@shared/models';
import { AppStorageService } from '@shared/services';
import { defer, forkJoin, map, Observable, of, switchMap } from 'rxjs';
import { tap } from 'rxjs/operators';

import { ORG_ID_OVERRIDE } from '../../core/interceptors/org-id-override.context';
import { SKIP_FORBIDDEN_RELOAD } from '../../core/interceptors/skip-forbidden-reload.context';
import { ConfigService } from '../config';
import { ActiveOrgService } from './active-org.service';
import { CurrentUserReload } from './current-user-reload.model';
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

    /**
     * Counts the preferences saves the cached user took; `sectionSaves` holds the count each section was last saved
     * at. A profile response remembers the count its request started at, so `setUser` can tell which saved sections
     * it is older than.
     */
    private preferencesSaves = 0;
    private readonly sectionSaves = new Map<PreferenceSection, number>();

    isMeSuperAdmin = computed(() => this.currentUser()?.is_superadmin ?? false);

    readonly shortcutSettings = computed<ShortcutSettings>(
        () => this.currentUser()?.custom_shortcuts ?? EMPTY_SHORTCUT_SETTINGS
    );

    systemRole = computed(() => {
        const user = this.currentUser();
        if (!user) return '—';
        if (user.is_superadmin) return ROLE_LABELS[UserRole.SUPER_ADMIN];

        const currentOrgId = this.activeOrgService.activeOrgId();
        const currentMembership = user.memberships.find((m) => m.organization.id === currentOrgId);

        return currentMembership ? currentMembership.role.name : '—';
    });

    /** Simple single fetch — use for refreshing profile data mid-session. */
    getCurrentUser(): Observable<GetMeResponse> {
        return this.fetchCurrentUser(new HttpContext());
    }

    /** Bootstrap: picks active org, then fetches active permissions + cross-org capabilities.
     *  Reuses cached profile if already fetched; otherwise fetches profile first.
     *  Called once by the route resolver on app load. */
    bootstrapUser(): Observable<GetMeResponse> {
        return defer(() => {
            const savesAtRequest = this.preferencesSaves;
            const cachedUser = this.currentUserSignal();
            const user$ = cachedUser ? of(cachedUser) : this.getCurrentUser();

            return user$.pipe(switchMap((user) => this.selectActiveOrgAndLoadPermissions(user, savesAtRequest)));
        });
    }

    /**
     * Refetches the profile, then does what the bootstrap does with it: keeps the active org while the user still
     * belongs to it, else picks another one, and reloads the active-org and cross-org permissions. For when the
     * memberships may have changed under the session (an organization was deactivated, reactivated or deleted, a 403
     * says the user lost access). Emits what changed for the user. Nothing changes until everything arrived: a failed
     * reload leaves the profile, the active org, the caches and the permissions as they were.
     *
     * Its own requests skip the forbidden interceptor's reload: a 403 among them fails this reload instead of
     * starting (or waiting for) another one. Each subscription runs a new reload; `CurrentUserRefreshService` runs
     * them one at a time and shares each run with every caller.
     */
    reloadCurrentUser(): Observable<CurrentUserReload> {
        return defer(() => {
            const previousUser = this.currentUser();
            const previousActiveOrgId = this.activeOrgService.activeOrgId();
            const savesAtRequest = this.preferencesSaves;
            const skipForbiddenReload = (): HttpContext => new HttpContext().set(SKIP_FORBIDDEN_RELOAD, true);
            return this.http.get<GetMeResponse>(this.baseUrl, { context: skipForbiddenReload() }).pipe(
                switchMap((user) => this.selectActiveOrgAndLoadPermissions(user, savesAtRequest, skipForbiddenReload)),
                map((user) =>
                    describeReload(previousUser, previousActiveOrgId, user, this.activeOrgService.activeOrgId())
                )
            );
        });
    }

    updateCurrentUser(dto: UpdateMeRequest): Observable<GetMeResponse> {
        return this.adoptProfileFrom(this.http.patch<GetMeResponse>(this.baseUrl, dto));
    }

    updateShortcutSettings(settings: ShortcutSettings): Observable<ShortcutSettings> {
        return this.http.patch<GetMeResponse>(this.baseUrl, { custom_shortcuts: settings }).pipe(
            map((user) => user.custom_shortcuts),
            tap((saved) => this.updateUser({ custom_shortcuts: saved }))
        );
    }

    /**
     * Saves `change` into the preferences section `section` and emits the section's effective value. The cached user
     * takes it only while the user who made the change is still signed in, as with `markTourCompleted`.
     */
    updatePreferencesSection<S extends PreferenceSection>(
        section: S,
        change: Partial<UserPreferences[S]>
    ): Observable<UserPreferences[S]> {
        const userId = this.currentUser()?.id ?? null;
        return this.http
            .patch<UserPreferences[S]>(`${this.baseUrl}preferences/${section}/`, change)
            .pipe(tap((saved) => this.setPreferencesSection(userId, section, saved)));
    }

    updateAvatar(avatar: FormData): Observable<GetMeResponse> {
        return this.http
            .post<GetMeResponse>(`${this.baseUrl}avatar/`, avatar)
            .pipe(tap((res) => this.updateUser({ avatar_url: res.avatar_url })));
    }

    deleteAvatar(): Observable<void> {
        return this.http.delete<void>(`${this.baseUrl}avatar/`).pipe(tap(() => this.updateUser({ avatar_url: null })));
    }

    /**
     * Saves the tour `tourKey` as finished or skipped by the signed-in user; saving it again is harmless. Emits the
     * tours that user has completed, `tourKey` included. The cached user takes them only while that user is still
     * signed in: the response may land after sign-out or after another user signed in, and must not bring back or
     * change a profile.
     */
    markTourCompleted(tourKey: string): Observable<readonly string[]> {
        return this.http
            .post<GetMeResponse>(`${this.baseUrl}tours/${encodeURIComponent(tourKey)}/complete/`, null)
            .pipe(
                tap((user) => this.updateUserIfStillSignedIn(user.id, { completed_tours: user.completed_tours })),
                map((user) => user.completed_tours)
            );
    }

    requestPasswordChange(dto: PasswordChangeVerifyRequest): Observable<PasswordChangeVerifyResponse> {
        return this.http.post<PasswordChangeVerifyResponse>(`${this.baseUrl}password-change/request/`, dto);
    }

    confirmPasswordChange(dto: PasswordChangeConfirmRequest): Observable<AccessToken> {
        return this.http.post<AccessToken>(`${this.baseUrl}password-change/confirm/`, dto, { withCredentials: true });
    }

    /** Switches the active organization: clears all caches, sets the new org,
     *  then reloads permissions (single + cross-org) for the new context. Order MATTERS */
    switchOrg(orgId: number): Observable<void> {
        this.appStorageService.clearAll();
        this.activeOrgService.set(orgId);
        return forkJoin({
            user: this.getCurrentUser(),
            active: this.permissionsService.loadActivePermissions(),
            orgs: this.permissionsService.loadOrgPermissions(),
        }).pipe(map(() => undefined));
    }

    clearCurrentUser(): void {
        this.currentUser.set(null);
    }

    createApiKey(dto: CreateApiKeyRequest): Observable<CreateApiKeyResponse> {
        return this.http.post<CreateApiKeyResponse>(`${this.baseUrl}api-keys/`, dto);
    }

    getMyApiKeys(): Observable<GetMyApiKeyResponse[]> {
        return this.http.get<GetMyApiKeyResponse[]>(`${this.baseUrl}api-keys/`);
    }

    revokeApiKey(id: number): Observable<GetMyApiKeyResponse> {
        return this.http.post<GetMyApiKeyResponse>(`${this.baseUrl}api-keys/${id}/revoke/`, {});
    }

    deleteApiKey(id: number): Observable<void> {
        return this.http.delete<void>(`${this.baseUrl}api-keys/${id}/`);
    }

    private fetchCurrentUser(context: HttpContext): Observable<GetMeResponse> {
        return this.adoptProfileFrom(this.http.get<GetMeResponse>(this.baseUrl, { context }));
    }

    /** Sends `request`, which is answered with the profile, and adopts the answer as `setUser` does. Emits it adopted. */
    private adoptProfileFrom(request: Observable<GetMeResponse>): Observable<GetMeResponse> {
        return defer(() => {
            const savesAtRequest = this.preferencesSaves;
            return request.pipe(map((user) => this.setUser(user, savesAtRequest)));
        });
    }

    /**
     * Picks the active org `user` may act in and loads its permissions, then adopts all of it at once. The active-org
     * permissions are fetched for the picked org explicitly (`ORG_ID_OVERRIDE`), so nothing is changed before they
     * arrive: if a request fails, the session keeps its previous, consistent profile, org, caches and permissions.
     */
    private selectActiveOrgAndLoadPermissions(
        user: GetMeResponse,
        savesAtRequest: number,
        requestContext: () => HttpContext = () => new HttpContext()
    ): Observable<GetMeResponse> {
        const previousOrgId = this.activeOrgService.activeOrgId();
        const orgId = selectActiveOrgId(user, previousOrgId);

        return forkJoin({
            active:
                orgId === null
                    ? of(null)
                    : this.permissionsService.fetchActivePermissions(requestContext().set(ORG_ID_OVERRIDE, orgId)),
            // Still loaded with no org left, so downstream gates read `is_superadmin: false, orgs: []`.
            orgs: this.permissionsService.fetchOrgPermissions(requestContext()),
        }).pipe(
            map(({ active, orgs }) => {
                // Leaving an org the app worked in: every org-scoped cache still holds its data. As in `switchOrg()`,
                // clear first, then set the org and its permissions.
                if (previousOrgId !== null && orgId !== previousOrgId) {
                    this.appStorageService.clearAll();
                }
                // No organization left sets `null`: a cached id would keep sending the header of an org the user lost.
                this.activeOrgService.set(orgId);
                const adopted = this.setUser(user, savesAtRequest);
                this.permissionsService.applyOrgPermissions(orgs);
                if (active !== null) {
                    this.permissionsService.applyActivePermissions(active);
                } else if (!user.is_superadmin) {
                    this.permissionsService.setActivePermissions(null);
                }
                return adopted;
            })
        );
    }

    /**
     * Adopts `user`, answered to a request started when `savesAtRequest` preferences saves were taken, and returns it as
     * adopted. A request can be answered after a preferences save it started before (`switchOrg()` reloads the profile
     * right after a change), and then carries the section as it was before that save: the saved section is kept.
     */
    private setUser(user: GetMeResponse, savesAtRequest: number): GetMeResponse {
        const adopted = this.withNewerPreferences(user, savesAtRequest);
        this.currentUser.set(adopted);
        this.permissionsService.setSuperadmin(adopted.is_superadmin);
        return adopted;
    }

    /** `user` with the cached value of each preferences section saved after its request started. */
    private withNewerPreferences(user: GetMeResponse, savesAtRequest: number): GetMeResponse {
        const current = this.currentUser();
        if (current === null || current.id !== user.id) return user;
        let preferences = user.preferences;
        for (const [section, saveNumber] of this.sectionSaves) {
            if (saveNumber > savesAtRequest) {
                preferences = { ...preferences, [section]: current.preferences[section] };
            }
        }
        return preferences === user.preferences ? user : { ...user, preferences };
    }

    private updateUser(partial: Partial<GetMeResponse>): void {
        const current = this.currentUser();
        if (!current) return;
        this.currentUser.set({ ...current, ...partial });
    }

    private setPreferencesSection<S extends PreferenceSection>(
        userId: number | null,
        section: S,
        value: UserPreferences[S]
    ): void {
        const current = this.currentUser();
        if (current === null || current.id !== userId) return;
        this.preferencesSaves += 1;
        this.sectionSaves.set(section, this.preferencesSaves);
        this.updateUser({ preferences: { ...current.preferences, [section]: value } });
    }

    private updateUserIfStillSignedIn(userId: number, partial: Partial<GetMeResponse>): void {
        if (this.currentUser()?.id === userId) {
            this.updateUser(partial);
        }
    }
}

/** The active org the user's memberships allow: the current one while they still belong to it, else the first one. */
function selectActiveOrgId(user: GetMeResponse, currentOrgId: number | null): number | null {
    if (user.memberships.length === 0) return null;
    const stillMember =
        currentOrgId !== null && user.memberships.some((membership) => membership.organization.id === currentOrgId);
    return stillMember ? currentOrgId : user.memberships[0].organization.id;
}

function describeReload(
    previousUser: GetMeResponse | null,
    previousActiveOrgId: number | null,
    user: GetMeResponse,
    activeOrgId: number | null
): CurrentUserReload {
    const organizations = user.memberships.map((membership) => membership.organization);
    const previousOrganizations = previousUser?.memberships.map((membership) => membership.organization) ?? [];
    const activeOrgChanged = activeOrgId !== previousActiveOrgId;
    return {
        user,
        activeOrgChanged,
        switchedTo: activeOrgChanged ? findOrganization(organizations, activeOrgId) : null,
        lostOrganizations: previousOrganizations.filter(
            (previous) => !organizations.some((organization) => organization.id === previous.id)
        ),
    };
}

function findOrganization(organizations: readonly Organization[], orgId: number | null): Organization | null {
    return orgId === null ? null : (organizations.find((organization) => organization.id === orgId) ?? null);
}
