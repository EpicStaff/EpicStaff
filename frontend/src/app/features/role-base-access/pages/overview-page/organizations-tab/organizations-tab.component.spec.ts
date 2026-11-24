// Side-effect import: ProfileService's dependency graph reads the `validationErrors` augmentation of
// HttpErrorResponse, which only type-checks when the module declaring it is compiled with the spec.
import '../../../../../core/interceptors/validation-errors.interceptor';

import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { GetMeResponse, GetOrganizationResponse, Organization } from '@shared/models';
import { firstValueFrom } from 'rxjs';

import { activeOrgInterceptor } from '../../../../../core/interceptors/active-org.interceptor';
import { forbiddenInterceptor } from '../../../../../core/interceptors/forbidden.interceptor';
import { ActiveOrgService } from '../../../../../services/auth/active-org.service';
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
import { OrganizationsTabComponent } from './organizations-tab.component';

const ORGANIZATIONS_URL = '/api/admin/organizations/';
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

describe('OrganizationsTabComponent membership changes', () => {
    let fixture: ComponentFixture<OrganizationsTabComponent>;
    let http: HttpTestingController;

    async function render(organizations: GetOrganizationResponse[]): Promise<void> {
        fixture = TestBed.createComponent(OrganizationsTabComponent);
        fixture.detectChanges();
        await vi.advanceTimersByTimeAsync(SEARCH_DEBOUNCE_MS);
        http.expectOne((request) => request.url === ORGANIZATIONS_URL).flush({
            count: organizations.length,
            next: null,
            previous: null,
            results: organizations,
        });
        fixture.detectChanges();
    }

    beforeEach(() => {
        vi.useFakeTimers();
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(withInterceptors([activeOrgInterceptor, forbiddenInterceptor])),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: API_URL } as unknown as ConfigService },
                {
                    provide: Router,
                    useValue: { url: '/workspace/organizations', navigateByUrl: () => Promise.resolve(true) },
                },
            ],
        });
        http = TestBed.inject(HttpTestingController);

        // Signed in to Organization A; its account menu lists A and B.
        TestBed.inject(ProfileService).bootstrapUser().subscribe();
        answerUserLoad(http, superadminIn(ORGANIZATION_A, ORGANIZATION_B));
    });

    afterEach(() => {
        fixture.destroy();
        vi.unstubAllGlobals();
        vi.useRealTimers();
        localStorage.clear();
        http.verify();
    });

    function host(): HTMLElement {
        return fixture.nativeElement as HTMLElement;
    }

    function clickRowAction(organizationName: string, label: string): void {
        const row = [...host().querySelectorAll('.table-row')].find(
            (candidate) => candidate.querySelector('.org-name')?.textContent?.trim() === organizationName
        )!;
        row.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`)!.click();
        fixture.detectChanges();
    }

    function confirmDialog(): void {
        document.querySelector<HTMLButtonElement>('.dialog-container .confirm-button')!.click();
        fixture.detectChanges();
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

        expect(organizationsInMenu()).toEqual(['B']);
        expect(TestBed.inject(ActiveOrgService).activeOrgId()).toBe(ORGANIZATION_B.id);
        expect(await shownToasts()).toEqual([
            { type: 'success', message: 'Organization deactivated successfully' },
            { type: 'info', message: 'You have been switched to B.' },
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

        expect(organizationsInMenu()).toEqual(['A', 'B']);
        expect(TestBed.inject(ActiveOrgService).activeOrgId()).toBe(ORGANIZATION_A.id);
        expect(await shownToasts()).toEqual([{ type: 'success', message: 'Organization reactivated successfully' }]);
    });
});
