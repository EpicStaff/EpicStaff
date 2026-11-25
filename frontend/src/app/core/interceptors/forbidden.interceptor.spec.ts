// Side-effect import: this module's `declare module '@angular/common/http'` augmentation
// (adding `validationErrors` to HttpErrorResponse) only applies to files TypeScript actually
// compiles together. ProfileService's dependency graph pulls in shared/utils/http-error.util.ts,
// which reads that property, so without this import the whole spec program fails to type-check.
import './validation-errors.interceptor';

import { HttpClient, HttpErrorResponse, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import type { Mock } from 'vitest';

import { ActiveOrgService } from '../../services/auth/active-org.service';
import { PermissionsService } from '../../services/auth/permissions.service';
import { ProfileService } from '../../services/auth/profile.service';
import {
    answerUserLoad,
    API_URL,
    memberOf,
    ORGANIZATION_A,
    ORGANIZATION_B,
    PROFILE_URL,
} from '../../services/auth/testing/current-user-fixtures';
import { ConfigService } from '../../services/config';
import { ToastMessage, ToastService } from '../../services/notifications';
import { activeOrgInterceptor } from './active-org.interceptor';
import { forbiddenInterceptor } from './forbidden.interceptor';

const CURRENT_PAGE = '/agents';

/** A 403 as the backend sends it. */
function forbidden(code: string, message?: string): object {
    return message === undefined ? { status_code: 403, code } : { status_code: 403, code, message };
}

describe('forbiddenInterceptor', () => {
    let http: HttpTestingController;
    let navigateByUrl: Mock<(url: string) => Promise<boolean>>;

    beforeEach(() => {
        navigateByUrl = vi.fn(() => Promise.resolve(true));
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(withInterceptors([activeOrgInterceptor, forbiddenInterceptor])),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: API_URL } as unknown as ConfigService },
                { provide: Router, useValue: { url: CURRENT_PAGE, navigateByUrl } as unknown as Router },
            ],
        });
        http = TestBed.inject(HttpTestingController);

        // Signed in to Organization A, as the app's bootstrap leaves the session.
        TestBed.inject(ProfileService).bootstrapUser().subscribe();
        answerUserLoad(http, memberOf(ORGANIZATION_A, ORGANIZATION_B));
    });

    afterEach(() => {
        localStorage.clear();
        http.verify();
    });

    /** Sends a request whose errors land in the returned list. */
    function send(url: string): HttpErrorResponse[] {
        const errors: HttpErrorResponse[] = [];
        TestBed.inject(HttpClient)
            .get(url)
            .subscribe({ error: (error: HttpErrorResponse) => errors.push(error) });
        return errors;
    }

    function refuse(url: string, body: object): void {
        http.expectOne(url).flush(body, { status: 403, statusText: 'Forbidden' });
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

    it.each([
        'built_in_model_immutable',
        'storage_grant_denied',
        'in_use_restricted',
        'key_value_mode_denied',
        'flow_with_trigger_nodes_requires_use_permission',
        'code_with_secrets_requires_secrets_use_permission',
        'agent_with_owned_surfaces_requires_surfaces_create_permission',
    ])('passes a %s 403 to the caller with no toast, reload or navigation', async (code) => {
        const errors = send('/api/flows/1/');

        refuse('/api/flows/1/', forbidden(code, 'Refused by a rule on this row.'));

        expect(errors.map((error) => error.error.code)).toEqual([code]);
        http.expectNone(PROFILE_URL);
        expect(await shownToasts()).toEqual([]);
        expect(await navigations()).toEqual([]);
    });

    it.each<[string, string, string | undefined]>([
        // Flows Use may just have been revoked.
        ['a trigger_nodes_require_use_permission', 'trigger_nodes_require_use_permission', 'Needs Flows Use.'],
        ['a stale-permissions', 'permission_denied', 'You do not have access to this resource.'],
        ['a message-less', 'permission_denied', undefined],
    ])(
        'shows %s 403 once, reloads the user, re-enters the page, then fails the caller',
        async (_case, code, message) => {
            const errors = send('/api/flows/1/');

            refuse('/api/flows/1/', forbidden(code, message));

            expect(await shownToasts()).toEqual([{ type: 'error', message: message ?? 'Forbidden' }]);
            expect(errors).toEqual([]);

            answerUserLoad(http, memberOf(ORGANIZATION_A, ORGANIZATION_B));

            expect(errors.map((error) => error.status)).toEqual([403]);
            expect(TestBed.inject(ActiveOrgService).activeOrgId()).toBe(ORGANIZATION_A.id);
            expect(await navigations()).toEqual(['/profile', CURRENT_PAGE]);
            expect(await shownToasts()).toHaveLength(1);
        }
    );

    it('tells about a deactivated active organization once and reloads once for three refused requests', async () => {
        const errorLists = [send('/api/flows/'), send('/api/agents/'), send('/api/tools/')];

        for (const url of ['/api/flows/', '/api/agents/', '/api/tools/']) {
            refuse(url, forbidden('organization_deactivated', 'This organization has been deactivated.'));
        }
        // One reload for all three: a second profile request here would fail `expectOne`.
        answerUserLoad(http, memberOf(ORGANIZATION_B));

        expect(await shownToasts()).toEqual([
            { type: 'warning', message: 'Organization A has been deactivated. You have been switched to B.' },
        ]);
        expect(errorLists.map((list) => list.map((error) => error.status))).toEqual([[403], [403], [403]]);
        expect(TestBed.inject(ActiveOrgService).activeOrgId()).toBe(ORGANIZATION_B.id);
        expect(TestBed.inject(PermissionsService).active()?.org_id).toBe(ORGANIZATION_B.id);
        expect(await navigations()).toEqual(['/profile', CURRENT_PAGE]);
    });
});
