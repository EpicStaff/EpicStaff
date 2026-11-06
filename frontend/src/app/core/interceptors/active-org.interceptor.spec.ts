import { HttpClient, HttpContext, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ActiveOrgService } from '../../services/auth/active-org.service';
import { PermissionsService } from '../../services/auth/permissions.service';
import { activeOrgInterceptor } from './active-org.interceptor';
import { ORG_ID_OVERRIDE } from './org-id-override.context';

const ACTIVE_ORG = 7;

describe('activeOrgInterceptor', () => {
    afterEach(() => {
        TestBed.inject(HttpTestingController).verify();
        TestBed.inject(ActiveOrgService).clear();
    });

    /** Sends a request as this user, with the given override, and returns the X-Organization-Id it went out with. */
    function sentOrgHeader(isSuperadmin: boolean, override: number | null | undefined): string | null {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(withInterceptors([activeOrgInterceptor])),
                provideHttpClientTesting(),
                { provide: PermissionsService, useValue: { isSuperadmin } },
            ],
        });
        TestBed.inject(ActiveOrgService).set(ACTIVE_ORG);
        const context = override === undefined ? new HttpContext() : new HttpContext().set(ORG_ID_OVERRIDE, override);

        TestBed.inject(HttpClient).get('/api/flows/', { context }).subscribe();

        const request = TestBed.inject(HttpTestingController).expectOne('/api/flows/');
        request.flush([]);
        return request.request.headers.get('X-Organization-Id');
    }

    it.each<[string, boolean, number | null | undefined, string | null]>([
        ['a member, no override: the active org', false, undefined, '7'],
        ['a member, an org id: that org', false, 9, '9'],
        ['a member, null: still the active org', false, null, '7'],
        ['a superadmin, an org id: that org', true, 9, '9'],
        ['a superadmin, null: no org at all', true, null, null],
    ])('sends, for %s', (_case, isSuperadmin, override, expected) => {
        expect(sentOrgHeader(isSuperadmin, override)).toBe(expected);
    });
});
