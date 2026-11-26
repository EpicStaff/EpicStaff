import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { GetMeResponse } from '@shared/models';
import { APP_STORAGE, AppStorageService } from '@shared/services';
import { of } from 'rxjs';

import { ActiveOrgService } from '../../services/auth/active-org.service';
import { AuthService } from '../../services/auth/auth.service';
import { PermissionsService } from '../../services/auth/permissions.service';
import { ProfileService } from '../../services/auth/profile.service';
import { ConfigService } from '../../services/config';
import { AuditSessionsBrowserComponent } from './audit-sessions-browser.component';
import { EMPTY_AUDIT_FILTER } from './models/audit-filter.models';
import { AuditFilterStorageService } from './services/audit-filter-storage.service';
import { AuditTokenService } from './services/audit-token.service';
import { auditFilterStorageKey, writeStoredAuditFilter } from './utils/audit-filter-storage.util';

const ORG_ID = 1;
const ALICE_ID = 7;
const BOB_ID = 8;
const SEARCH_URL = '/auditor/api/audit/sessions/search';
// the page applies typed text after this pause
const SEARCH_DEBOUNCE_MS = 400;

// The filter controls measure themselves with ResizeObserver, which jsdom lacks.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

function signIn(userId: number): void {
    TestBed.inject(ProfileService).getCurrentUser().subscribe();
    TestBed.inject(HttpTestingController)
        .expectOne('/api/profile/')
        .flush({ id: userId, is_superadmin: false, memberships: [] } as unknown as GetMeResponse);
}

function openPage(): { fixture: ComponentFixture<AuditSessionsBrowserComponent>; http: HttpTestingController } {
    const fixture = TestBed.createComponent(AuditSessionsBrowserComponent);
    fixture.detectChanges();
    return { fixture, http: TestBed.inject(HttpTestingController) };
}

function searchedText(http: HttpTestingController): unknown {
    const request = http.expectOne(SEARCH_URL);
    request.flush({ items: [], next_cursor: null, partial: false });
    return request.request.body.filters;
}

function textFilter(value: string): unknown {
    return { field: '__text__', op: 'contains', value };
}

function storedAuditFilterKeys(): string[] {
    return Object.keys(localStorage).filter((key) => key.startsWith('epicstaff.audit.filter.'));
}

describe('AuditSessionsBrowserComponent saved filter', () => {
    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        localStorage.clear();
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                provideRouter([]),
                { provide: ConfigService, useValue: { apiUrl: '/api/', auditorUrl: '/auditor/' } },
                { provide: AuditTokenService, useValue: { getToken: () => of('audit-token') } },
                { provide: ActiveOrgService, useValue: { activeOrgId: () => ORG_ID } },
                { provide: PermissionsService, useValue: { can: () => true, setSuperadmin: () => undefined } },
                { provide: APP_STORAGE, useExisting: AuditFilterStorageService, multi: true },
            ],
        });
    });

    afterEach(() => {
        vi.useRealTimers();
        vi.unstubAllGlobals();
        localStorage.clear();
    });

    it.each([
        [ALICE_ID, 'alice text'],
        [BOB_ID, 'bob text'],
    ])('opens with the search the signed-in user %s saved in this organization', (userId, expectedText) => {
        writeStoredAuditFilter(auditFilterStorageKey(ORG_ID, ALICE_ID, 'applied'), {
            ...EMPTY_AUDIT_FILTER,
            searchText: 'alice text',
        });
        writeStoredAuditFilter(auditFilterStorageKey(ORG_ID, BOB_ID, 'applied'), {
            ...EMPTY_AUDIT_FILTER,
            searchText: 'bob text',
        });
        signIn(userId);

        const { http } = openPage();

        expect(searchedText(http)).toEqual(textFilter(expectedText));
    });

    it('saves a search typed just before sign-out nowhere, though the page still runs it', () => {
        vi.useFakeTimers();
        signIn(ALICE_ID);
        const { fixture, http } = openPage();
        searchedText(http);

        const search = (fixture.nativeElement as HTMLElement).querySelector<HTMLInputElement>(
            'input[aria-label="Search every field"]'
        )!;
        search.value = 'secret';
        search.dispatchEvent(new Event('input'));
        TestBed.inject(AuthService).logout().subscribe();
        vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS);
        fixture.detectChanges();

        expect(searchedText(http)).toEqual(textFilter('secret'));
        expect(storedAuditFilterKeys()).toEqual([]);
    });

    // An org switch clears every storage, then reloads the signed-in user while this page is still open.
    it('does not save the filter again when an org switch reloads the user', () => {
        writeStoredAuditFilter(auditFilterStorageKey(ORG_ID, ALICE_ID, 'applied'), {
            ...EMPTY_AUDIT_FILTER,
            searchText: 'alice text',
        });
        signIn(ALICE_ID);
        const { fixture, http } = openPage();
        searchedText(http);

        TestBed.inject(AppStorageService).clearAll();
        signIn(ALICE_ID);
        fixture.detectChanges();

        expect(storedAuditFilterKeys()).toEqual([]);
    });
});
