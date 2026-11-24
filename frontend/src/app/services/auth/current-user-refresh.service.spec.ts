// Side-effect import: ProfileService's dependency graph reads the `validationErrors` augmentation of
// HttpErrorResponse, which only type-checks when the module declaring it is compiled with the spec.
import '../../core/interceptors/validation-errors.interceptor';

import { HttpClient, HttpErrorResponse, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Injectable } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { GetMeResponse } from '@shared/models';
import { APP_STORAGE, StorageService } from '@shared/services';
import { firstValueFrom } from 'rxjs';
import type { Mock } from 'vitest';

import { activeOrgInterceptor } from '../../core/interceptors/active-org.interceptor';
import { forbiddenInterceptor } from '../../core/interceptors/forbidden.interceptor';
import { ConfigService } from '../config';
import { ToastMessage, ToastService } from '../notifications';
import { ActiveOrgService } from './active-org.service';
import { CurrentUserRefreshService } from './current-user-refresh.service';
import { PermissionsService } from './permissions.service';
import { ProfileService } from './profile.service';
import {
    ACTIVE_PERMISSIONS_URL,
    answerUserLoad,
    API_URL,
    memberOf,
    ORG_PERMISSIONS_URL,
    ORGANIZATION_A,
    ORGANIZATION_B,
    PROFILE_URL,
} from './testing/current-user-fixtures';

const CURRENT_PAGE = '/agents';
const DEACTIVATED_MESSAGE = 'This organization has been deactivated.';

/** Stands in for any org-scoped store registered with APP_STORAGE (flows, agents, tools…). */
@Injectable({ providedIn: 'root' })
class OrgScopedStoreFake implements StorageService {
    data: string | null = null;

    clear(): void {
        this.data = null;
    }
}

describe('CurrentUserRefreshService', () => {
    let http: HttpTestingController;
    let navigateByUrl: Mock<(url: string) => Promise<boolean>>;

    beforeEach(() => {
        navigateByUrl = vi.fn(() => Promise.resolve(true));
        TestBed.configureTestingModule({
            providers: [
                // The app's order: the org header is set before the forbidden interceptor sees the request.
                provideHttpClient(withInterceptors([activeOrgInterceptor, forbiddenInterceptor])),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: API_URL } as unknown as ConfigService },
                { provide: Router, useValue: { url: CURRENT_PAGE, navigateByUrl } as unknown as Router },
                // Registered as `app.config.ts` registers them, plus one feature store.
                { provide: APP_STORAGE, useExisting: ActiveOrgService, multi: true },
                { provide: APP_STORAGE, useExisting: PermissionsService, multi: true },
                { provide: APP_STORAGE, useExisting: OrgScopedStoreFake, multi: true },
            ],
        });
        http = TestBed.inject(HttpTestingController);

        TestBed.inject(ProfileService).bootstrapUser().subscribe();
        answerUserLoad(http, memberOf(ORGANIZATION_A, ORGANIZATION_B));
        TestBed.inject(OrgScopedStoreFake).data = 'flows of Organization A';
    });

    afterEach(() => {
        localStorage.clear();
        http.verify();
    });

    function refreshService(): CurrentUserRefreshService {
        return TestBed.inject(CurrentUserRefreshService);
    }

    function activeOrgId(): number | null {
        return TestBed.inject(ActiveOrgService).activeOrgId();
    }

    function organizationsInMenu(): string[] {
        return (
            TestBed.inject(ProfileService)
                .currentUserSignal()
                ?.memberships.map((membership) => membership.organization.name) ?? []
        );
    }

    /** Sends a request in the active org (or in `body`'s org); its errors land in the returned list. */
    function send(url: string, body?: object): HttpErrorResponse[] {
        const errors: HttpErrorResponse[] = [];
        const client = TestBed.inject(HttpClient);
        const request$ = body === undefined ? client.get(url) : client.post(url, body);
        request$.subscribe({ error: (error: HttpErrorResponse) => errors.push(error) });
        return errors;
    }

    function refuse(url: string, code: string, message: string): void {
        http.expectOne(url).flush({ status_code: 403, code, message }, { status: 403, statusText: 'Forbidden' });
    }

    async function shownToasts(): Promise<Pick<ToastMessage, 'type' | 'message'>[]> {
        const toasts = await firstValueFrom(TestBed.inject(ToastService).toasts$);
        return toasts.map(({ type, message }) => ({ type, message }));
    }

    /** The addresses the router was sent to, after the navigations a re-entry chains have run. */
    async function navigations(): Promise<string[]> {
        await Promise.resolve();
        return navigateByUrl.mock.calls.map(([url]) => url);
    }

    describe('a 403', () => {
        it('is dropped when it was sent under an organization the app has already left', async () => {
            const errors = send('/api/flows/');
            TestBed.inject(ProfileService).switchOrg(ORGANIZATION_B.id).subscribe();
            answerUserLoad(http, memberOf(ORGANIZATION_A, ORGANIZATION_B));
            navigateByUrl.mockClear();

            refuse('/api/flows/', 'org_membership_required', 'You are not a member of this organization.');

            expect(errors.map((error) => error.status)).toEqual([403]);
            http.expectNone(PROFILE_URL);
            expect(await shownToasts()).toEqual([]);
            expect(await navigations()).toEqual([]);
            expect(activeOrgId()).toBe(ORGANIZATION_B.id);
        });

        it('arriving during a membership-change reload waits for it, then is told and reloaded on its own', async () => {
            refreshService().refreshAfterMembershipChange();
            const errors = send('/api/flows/');

            refuse('/api/flows/', 'permission_denied', 'You do not have access to this resource.');
            // Still waiting: the reload under way did not tell the user about this 403.
            expect(await shownToasts()).toEqual([]);
            expect(errors).toEqual([]);
            answerUserLoad(http, memberOf(ORGANIZATION_A, ORGANIZATION_B));

            expect(await shownToasts()).toEqual([
                { type: 'error', message: 'You do not have access to this resource.' },
            ]);
            expect(errors).toEqual([]);
            answerUserLoad(http, memberOf(ORGANIZATION_A, ORGANIZATION_B));

            expect(errors.map((error) => error.status)).toEqual([403]);
            expect(await navigations()).toEqual(['/profile', CURRENT_PAGE]);
        });

        it('for an organization named in the request body, the header org being fine, shows the server message once', async () => {
            const errors = send('/api/flows/1/copy/', { organization_id: 3 });

            refuse('/api/flows/1/copy/', 'organization_deactivated', DEACTIVATED_MESSAGE);
            answerUserLoad(http, memberOf(ORGANIZATION_A, ORGANIZATION_B));

            expect(await shownToasts()).toEqual([{ type: 'error', message: DEACTIVATED_MESSAGE }]);
            expect(errors.map((error) => error.status)).toEqual([403]);
            expect(activeOrgId()).toBe(ORGANIZATION_A.id);
            expect(TestBed.inject(OrgScopedStoreFake).data).toBe('flows of Organization A');
            expect(await navigations()).toEqual(['/profile', CURRENT_PAGE]);
        });

        it('says no organization is left when the deactivated one was the last', async () => {
            send('/api/flows/');

            refuse('/api/flows/', 'organization_deactivated', DEACTIVATED_MESSAGE);
            answerUserLoad(http, memberOf());

            expect(await shownToasts()).toEqual([
                {
                    type: 'warning',
                    message: 'Organization A has been deactivated. You no longer belong to any organization.',
                },
            ]);
            expect(activeOrgId()).toBeNull();
            expect(TestBed.inject(PermissionsService).active()).toBeNull();
        });
    });

    describe('a failed reload', () => {
        it.each<[string, (http: HttpTestingController, user: GetMeResponse) => void]>([
            [
                'the permissions in the new org fail',
                (backend, user) => {
                    backend.expectOne(PROFILE_URL).flush(user);
                    backend.expectOne(ORG_PERMISSIONS_URL).flush({ is_superadmin: false, orgs: [] });
                    backend
                        .expectOne(ACTIVE_PERMISSIONS_URL)
                        .flush({ detail: 'Server error.' }, { status: 500, statusText: 'Server Error' });
                },
            ],
            [
                'the profile fails',
                (backend) =>
                    backend.expectOne(PROFILE_URL).flush({ detail: 'Unavailable.' }, { status: 503, statusText: '' }),
            ],
        ])('leaves the profile, active org, stores and permissions as they were when %s', async (_case, failReload) => {
            const errors = send('/api/flows/');

            refuse('/api/flows/', 'organization_deactivated', DEACTIVATED_MESSAGE);
            failReload(http, memberOf(ORGANIZATION_B));

            expect(activeOrgId()).toBe(ORGANIZATION_A.id);
            expect(organizationsInMenu()).toEqual(['A', 'B']);
            expect(TestBed.inject(OrgScopedStoreFake).data).toBe('flows of Organization A');
            expect(TestBed.inject(PermissionsService).active()?.org_id).toBe(ORGANIZATION_A.id);
            expect(await shownToasts()).toEqual([{ type: 'error', message: DEACTIVATED_MESSAGE }]);
            expect(errors.map((error) => error.status)).toEqual([403]);
            expect(await navigations()).toEqual([]);
        });

        it('after a membership change says the refresh failed', async () => {
            refreshService().refreshAfterMembershipChange();

            http.expectOne(PROFILE_URL).flush({ detail: 'Unavailable.' }, { status: 503, statusText: '' });

            expect(await shownToasts()).toEqual([
                {
                    type: 'error',
                    message: 'Could not refresh your organizations and permissions. Reload the page to try again.',
                },
            ]);
            expect(activeOrgId()).toBe(ORGANIZATION_A.id);
        });
    });

    describe('refreshAfterMembershipChange', () => {
        it('after the active organization was deactivated clears org-scoped stores, switches to another org and stays on the page', async () => {
            refreshService().refreshAfterMembershipChange();

            answerUserLoad(http, memberOf(ORGANIZATION_B));

            expect(activeOrgId()).toBe(ORGANIZATION_B.id);
            expect(TestBed.inject(OrgScopedStoreFake).data).toBeNull();
            expect(TestBed.inject(PermissionsService).active()?.org_id).toBe(ORGANIZATION_B.id);
            expect(organizationsInMenu()).toEqual(['B']);
            expect(await shownToasts()).toEqual([{ type: 'info', message: 'You have been switched to B.' }]);
            expect(await navigations()).toEqual([]);
        });

        it.each<[string, GetMeResponse, string[]]>([
            ['a member is sent through the guards again', memberOf(), ['/profile', CURRENT_PAGE]],
            ['a superadmin stays on the page', { ...memberOf(), is_superadmin: true }, []],
        ])('after the last organization went, %s', async (_case, user, expectedNavigations) => {
            refreshService().refreshAfterMembershipChange();

            answerUserLoad(http, user);

            expect(activeOrgId()).toBeNull();
            expect(await shownToasts()).toEqual([
                { type: 'info', message: 'You no longer belong to any organization.' },
            ]);
            expect(await navigations()).toEqual(expectedNavigations);
        });

        it.each<[string, (backend: HttpTestingController) => void]>([
            ['succeeded', (backend) => answerUserLoad(backend, memberOf(ORGANIZATION_B))],
            [
                'failed',
                (backend) =>
                    backend.expectOne(PROFILE_URL).flush({ detail: 'Unavailable.' }, { status: 503, statusText: '' }),
            ],
        ])('tells the caller once the reload %s, so the page can reload its own data', (_case, endReload) => {
            let finished = 0;
            refreshService()
                .refreshAfterMembershipChange()
                .subscribe(() => finished++);
            expect(finished).toBe(0);

            endReload(http);

            expect(finished).toBe(1);
        });

        it('after another organization changed updates the menu and leaves the page and stores alone', async () => {
            refreshService().refreshAfterMembershipChange();

            answerUserLoad(http, memberOf(ORGANIZATION_A));

            expect(organizationsInMenu()).toEqual(['A']);
            expect(activeOrgId()).toBe(ORGANIZATION_A.id);
            expect(TestBed.inject(OrgScopedStoreFake).data).toBe('flows of Organization A');
            expect(await shownToasts()).toEqual([]);
            expect(await navigations()).toEqual([]);
        });

        it('requested during a reload starts after it, so it reads a profile that follows the change', () => {
            refreshService().refreshAfterMembershipChange();
            refreshService().refreshAfterMembershipChange();

            // `expectOne` fails while two profile requests are open at once.
            answerUserLoad(http, memberOf(ORGANIZATION_A, ORGANIZATION_B));
            answerUserLoad(http, memberOf(ORGANIZATION_A));

            expect(organizationsInMenu()).toEqual(['A']);
        });
    });
});
