// Side-effect import: ProfileService's dependency graph reads the `validationErrors` augmentation of
// HttpErrorResponse, which only type-checks when the module declaring it is compiled with the spec.
import '../../../../../core/interceptors/validation-errors.interceptor';

import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, TestRequest } from '@angular/common/http/testing';
import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { GetMeResponse, GetOrganizationResponse, Organization } from '@shared/models';
import { APP_STORAGE } from '@shared/services';
import { firstValueFrom } from 'rxjs';

import { activeOrgInterceptor } from '../../../../../core/interceptors/active-org.interceptor';
import { forbiddenInterceptor } from '../../../../../core/interceptors/forbidden.interceptor';
import { ActiveOrgService } from '../../../../../services/auth/active-org.service';
import { PermissionsService } from '../../../../../services/auth/permissions.service';
import { ProfileService } from '../../../../../services/auth/profile.service';
import {
    answerUserLoad,
    API_URL,
    memberOf,
    ORGANIZATION_A,
    ORGANIZATION_B,
} from '../../../../../services/auth/testing/current-user-fixtures';
import { ConfigService } from '../../../../../services/config';
import { ToastMessage, ToastService } from '../../../../../services/notifications';
import { provideRoleBaseAccessStorages } from '../../../role-base-access.providers';
import { OrganizationsTabComponent } from './organizations-tab.component';

const ORGANIZATIONS_URL = '/api/admin/organizations/';
const ORGANIZATIONS_PAGE = '/workspace/organizations';
/** An organization the signed-in user is not a member of; its name matches a search for "a" as A's does. */
const ACME: Organization = { id: 3, name: 'Acme' };
/** The search box waits this long before it asks for the list; taken from the component, not a product limit. */
const SEARCH_DEBOUNCE_MS = 300;

function listed(organization: Organization, isActive: boolean): GetOrganizationResponse {
    return {
        ...organization,
        is_active: isActive,
        member_count: 3,
        admins: [],
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
    };
}

/** A superadmin who is also a member of `organizations` (the workspace actions are superadmin-only). */
function superadminIn(...organizations: Organization[]): GetMeResponse {
    return { ...memberOf(...organizations), is_superadmin: true };
}

// jsdom has no ResizeObserver; the confirmation dialog's buttons only need it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

/** Where a page re-entry passes through on its way back; any other page would do. */
@Component({ template: '' })
class ProfilePageStub {}

describe('OrganizationsTabComponent membership changes', () => {
    let harness: RouterTestingHarness;
    let http: HttpTestingController;

    /** Opens the organizations page and answers the list it asks for. */
    async function render(organizations: GetOrganizationResponse[]): Promise<void> {
        harness = await RouterTestingHarness.create();
        await harness.navigateByUrl(ORGANIZATIONS_PAGE, OrganizationsTabComponent);
        await answerListLoad(organizations);
    }

    /**
     * Lets the debounced filters fire and answers the latest list request they sent with `organizations`, returning
     * it. A request a later filter change replaced is left unanswered.
     */
    async function answerListLoad(organizations: GetOrganizationResponse[]): Promise<TestRequest> {
        harness.detectChanges();
        await vi.advanceTimersByTimeAsync(SEARCH_DEBOUNCE_MS);
        const requests = http.match((candidate) => candidate.url === ORGANIZATIONS_URL);
        expect(requests.length).toBeGreaterThan(0);
        const latest = requests[requests.length - 1];
        answerList(latest, organizations);
        return latest;
    }

    function answerList(request: TestRequest, organizations: GetOrganizationResponse[]): void {
        request.flush({ count: organizations.length, next: null, previous: null, results: organizations });
        harness.detectChanges();
    }

    beforeEach(() => {
        vi.useFakeTimers();
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(withInterceptors([activeOrgInterceptor, forbiddenInterceptor])),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: API_URL } as unknown as ConfigService },
                provideRouter([
                    { path: 'workspace/organizations', component: OrganizationsTabComponent },
                    { path: 'profile', component: ProfilePageStub },
                ]),
                // Registered as `app.config.ts` registers them: an org switch clears this page's list too.
                { provide: APP_STORAGE, useExisting: ActiveOrgService, multi: true },
                { provide: APP_STORAGE, useExisting: PermissionsService, multi: true },
                ...provideRoleBaseAccessStorages(),
            ],
        });
        http = TestBed.inject(HttpTestingController);

        // Signed in to Organization A; its account menu lists A and B.
        TestBed.inject(ProfileService).bootstrapUser().subscribe();
        answerUserLoad(http, superadminIn(ORGANIZATION_A, ORGANIZATION_B));
    });

    afterEach(() => {
        harness.fixture.destroy();
        vi.unstubAllGlobals();
        vi.useRealTimers();
        localStorage.clear();
        http.verify();
    });

    function host(): HTMLElement {
        return harness.routeNativeElement!;
    }

    function rowOf(organizationName: string): Element | undefined {
        return [...host().querySelectorAll('.table-row')].find(
            (candidate) => candidate.querySelector('.org-name')?.textContent?.trim() === organizationName
        );
    }

    function clickRowAction(organizationName: string, label: string): void {
        rowOf(organizationName)!.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`)!.click();
        harness.detectChanges();
    }

    /** The organizations the table lists, with the status each shows. */
    function shownOrganizations(): string[] {
        return [...host().querySelectorAll('.table-row')].map((row) => {
            const name = row.querySelector('.org-name')?.textContent?.trim();
            const status = row.querySelector('app-status-badge')?.textContent?.trim();
            return `${name}: ${status}`;
        });
    }

    function searchBox(): HTMLInputElement {
        return host().querySelector<HTMLInputElement>('app-search input')!;
    }

    function typeSearch(term: string): void {
        searchBox().value = term;
        searchBox().dispatchEvent(new Event('input'));
        harness.detectChanges();
    }

    function filterStatus(statusLabel: string): void {
        const filterButton = [...host().querySelectorAll<HTMLButtonElement>('.col-label--filter')].find((button) =>
            button.textContent?.trim().startsWith('Status')
        )!;
        filterButton.click();
        TestBed.tick();
        const option = [...document.querySelectorAll<HTMLElement>('.multi-select__item')].find(
            (item) => item.querySelector('.multi-select__item-name')?.textContent?.trim() === statusLabel
        )!;
        option.click();
        TestBed.tick();
        const saveButton = [
            ...document.querySelectorAll<HTMLButtonElement>('.multi-select__footer-actions button'),
        ].find((button) => button.textContent?.trim() === 'Save')!;
        saveButton.click();
        harness.detectChanges();
    }

    function confirmDialog(): void {
        // The dialog is rendered by the application, not by the page's fixture.
        TestBed.tick();
        document.querySelector<HTMLButtonElement>('.dialog-container .confirm-button')!.click();
        harness.detectChanges();
    }

    /** The organizations the account menu lists: the signed-in user's memberships. */
    function organizationsInMenu(): string[] {
        return (
            TestBed.inject(ProfileService)
                .currentUserSignal()
                ?.memberships.map((membership) => membership.organization.name) ?? []
        );
    }

    async function shownToasts(): Promise<Pick<ToastMessage, 'type' | 'message'>[]> {
        const toasts = await firstValueFrom(TestBed.inject(ToastService).toasts$);
        return toasts.map(({ type, message }) => ({ type, message }));
    }

    it('reloads the account menu after deactivating the active organization and moves the user to another one', async () => {
        await render([listed(ORGANIZATION_A, true), listed(ORGANIZATION_B, true)]);

        clickRowAction('A', 'Deactivate organization');
        confirmDialog();
        http.expectOne(`${ORGANIZATIONS_URL}${ORGANIZATION_A.id}/deactivate/`).flush(null);
        answerUserLoad(http, superadminIn(ORGANIZATION_B));
        await answerListLoad([listed(ORGANIZATION_A, false), listed(ORGANIZATION_B, true)]);

        expect(organizationsInMenu()).toEqual(['B']);
        expect(TestBed.inject(ActiveOrgService).activeOrgId()).toBe(ORGANIZATION_B.id);
        expect(await shownToasts()).toEqual([
            { type: 'success', message: 'Organization deactivated successfully' },
            { type: 'info', message: 'You have been switched to B.' },
        ]);
    });

    it('keeps the typed search, the status filter and the focus after deactivating the active organization, and lists what the server now holds', async () => {
        await render([listed(ORGANIZATION_A, true), listed(ACME, true), listed(ORGANIZATION_B, true)]);
        typeSearch('a');
        filterStatus('Active');
        await answerListLoad([listed(ORGANIZATION_A, true), listed(ACME, true)]);

        clickRowAction('A', 'Deactivate organization');
        confirmDialog();
        http.expectOne(`${ORGANIZATIONS_URL}${ORGANIZATION_A.id}/deactivate/`).flush(null);
        answerUserLoad(http, superadminIn(ORGANIZATION_B));
        await vi.advanceTimersByTimeAsync(0);
        const refreshedList = await answerListLoad([listed(ACME, true)]);

        expect(refreshedList.request.params.get('search')).toBe('a');
        expect(refreshedList.request.params.getAll('is_active')).toEqual(['true']);
        expect(searchBox().value).toBe('a');
        expect(shownOrganizations()).toEqual(['Acme: Active']);
        expect(document.activeElement?.textContent?.trim()).toBe('Create Organization');
    });

    it('completes a reactivation issued while the refresh after a deactivation is still running', async () => {
        await render([listed(ORGANIZATION_A, true), listed(ORGANIZATION_B, true)]);

        clickRowAction('A', 'Deactivate organization');
        confirmDialog();
        http.expectOne(`${ORGANIZATIONS_URL}${ORGANIZATION_A.id}/deactivate/`).flush(null);
        harness.detectChanges();
        clickRowAction('A', 'Activate organization');
        answerUserLoad(http, superadminIn(ORGANIZATION_B));
        // The list reload after the deactivation goes out; the reactivation's reload replaces it before it is answered.
        TestBed.tick();
        await vi.advanceTimersByTimeAsync(0);
        const listAfterDeactivation = http.expectOne((candidate) => candidate.url === ORGANIZATIONS_URL);
        http.expectOne(`${ORGANIZATIONS_URL}${ORGANIZATION_A.id}/reactivate/`).flush(null);
        answerUserLoad(http, superadminIn(ORGANIZATION_B, ORGANIZATION_A));
        await answerListLoad([listed(ORGANIZATION_A, true), listed(ORGANIZATION_B, true)]);
        // A late answer to the replaced request, read before the reactivation, must not overwrite the newer list.
        if (!listAfterDeactivation.cancelled) {
            answerList(listAfterDeactivation, [listed(ORGANIZATION_A, false), listed(ORGANIZATION_B, true)]);
        }

        expect(organizationsInMenu()).toEqual(['B', 'A']);
        expect(TestBed.inject(ActiveOrgService).activeOrgId()).toBe(ORGANIZATION_B.id);
        expect(shownOrganizations()).toEqual(['A: Active', 'B: Active']);
        expect(await shownToasts()).toEqual([
            { type: 'success', message: 'Organization deactivated successfully' },
            { type: 'info', message: 'You have been switched to B.' },
            { type: 'success', message: 'Organization reactivated successfully' },
        ]);
    });

    it('reloads the account menu after reactivating an organization', async () => {
        TestBed.inject(ProfileService).clearCurrentUser();
        TestBed.inject(ProfileService).bootstrapUser().subscribe();
        answerUserLoad(http, superadminIn(ORGANIZATION_A));
        await render([listed(ORGANIZATION_A, true), listed(ORGANIZATION_B, false)]);

        clickRowAction('B', 'Activate organization');
        http.expectOne(`${ORGANIZATIONS_URL}${ORGANIZATION_B.id}/reactivate/`).flush(null);
        answerUserLoad(http, superadminIn(ORGANIZATION_A, ORGANIZATION_B));
        await answerListLoad([listed(ORGANIZATION_A, true), listed(ORGANIZATION_B, true)]);

        expect(organizationsInMenu()).toEqual(['A', 'B']);
        expect(TestBed.inject(ActiveOrgService).activeOrgId()).toBe(ORGANIZATION_A.id);
        expect(await shownToasts()).toEqual([{ type: 'success', message: 'Organization reactivated successfully' }]);
    });
});
