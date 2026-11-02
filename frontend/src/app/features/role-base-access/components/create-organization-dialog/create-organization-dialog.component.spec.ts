import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ConfirmationDialogService, ConfirmationResult } from '@shared/components';
import { AdminCreateUserResponse, GetOrganizationResponse, OrganizationRetention } from '@shared/models';
import { EMPTY, of, Subject } from 'rxjs';
import type { Mock } from 'vitest';

import { validationErrorsInterceptor } from '../../../../core/interceptors/validation-errors.interceptor';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ProfileService } from '../../../../services/auth/profile.service';
import { ConfigService } from '../../../../services/config';
import { ToastService } from '../../../../services/notifications';
import { AdminUserService } from '../../services/admin/admin-user.service';
import { RolesService } from '../../services/admin/roles.service';
import { CreateOrganizationDialogComponent } from './create-organization-dialog.component';

// jsdom has no ResizeObserver; app-button's overflow directive only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

const API_URL = '/api/';
const ORG_ID = 7;
const SELF_ID = 1;
const MEMBER_ID = 2;
const MEMBER_ROLE_ID = 3;
const MEMBERSHIP_ID = 100;
const ORGANIZATION_URL = `${API_URL}admin/organizations/${ORG_ID}/`;
const RETENTION_URL = `${ORGANIZATION_URL}retention/`;
const MEMBERSHIPS_URL = `${API_URL}admin/memberships/`;

const ORGANIZATION: GetOrganizationResponse = {
    id: ORG_ID,
    name: 'Acme',
    is_active: true,
    member_count: 1,
    admins: [],
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    config: { audit_retention_days: 0 },
};

// Every type is on its 90-day instance default, so 365 days raises a retention and 30 days lowers it.
const RETENTION: OrganizationRetention = {
    org_id: ORG_ID,
    sessions_days: null,
    sessions_effective_days: 90,
    conversations_days: null,
    conversations_effective_days: 90,
    audit_days: null,
    audit_effective_days: 90,
    updated_at: null,
    updated_by: null,
    retention_policy: {
        sessions: { default_days: 90, max_days: null, min_days: null, allowed: [30, 90, 365] },
        conversations: { default_days: 90, max_days: null, min_days: null, allowed: [30, 90, 365] },
        audit: { default_days: 90, max_days: null, min_days: null, allowed: [30, 90, 365] },
    },
};

const MEMBER: AdminCreateUserResponse = {
    id: MEMBER_ID,
    email: 'member@example.com',
    avatar_url: '',
    display_name: 'Member',
    is_superadmin: false,
    is_active: true,
    memberships: [
        {
            id: MEMBERSHIP_ID,
            organization: { id: ORG_ID, name: ORGANIZATION.name },
            role: { id: MEMBER_ROLE_ID, name: 'Member' },
            joined_at: '2026-01-01T00:00:00Z',
        },
    ],
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
};

describe('CreateOrganizationDialogComponent saving an organization', () => {
    let fixture: ComponentFixture<CreateOrganizationDialogComponent>;
    let element: HTMLElement;
    let http: HttpTestingController;
    let dialogRef: { close: Mock; keydownEvents: typeof EMPTY };
    let toast: { success: Mock; error: Mock };
    let confirmation: Subject<ConfirmationResult>;

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        dialogRef = { close: vi.fn(), keydownEvents: EMPTY };
        toast = { success: vi.fn(), error: vi.fn() };
        confirmation = new Subject<ConfirmationResult>();

        TestBed.configureTestingModule({
            imports: [CreateOrganizationDialogComponent],
            providers: [
                provideHttpClient(withInterceptors([validationErrorsInterceptor])),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: API_URL } },
                { provide: DialogRef, useValue: dialogRef },
                { provide: DIALOG_DATA, useValue: ORGANIZATION },
                { provide: ToastService, useValue: toast },
                { provide: ConfirmationDialogService, useValue: { confirm: () => confirmation } },
                { provide: PermissionsService, useValue: { isSuperadmin: true, canInOrg: () => true } },
                {
                    provide: ProfileService,
                    useValue: { currentUserSignal: signal({ id: SELF_ID }), getCurrentUser: () => of({}) },
                },
                {
                    provide: AdminUserService,
                    useValue: { getUsers: () => of({ count: 1, next: null, previous: null, results: [MEMBER] }) },
                },
                {
                    provide: RolesService,
                    useValue: {
                        loadAssignableRoles: () =>
                            of({ built_in_roles: [], results: [], count: 0, next: null, previous: null }),
                    },
                },
            ],
        });
        http = TestBed.inject(HttpTestingController);
        fixture = TestBed.createComponent(CreateOrganizationDialogComponent);
        element = fixture.nativeElement as HTMLElement;
        settle();
        http.expectOne({ method: 'GET', url: RETENTION_URL }).flush(RETENTION);
        settle();
    });

    afterEach(() => vi.unstubAllGlobals());

    function settle(): void {
        fixture.detectChanges();
        TestBed.tick();
        fixture.detectChanges();
    }

    function saveButton(): HTMLButtonElement {
        return element.querySelector<HTMLButtonElement>('.header app-button[type="primary"] button')!;
    }

    function clickSave(): void {
        saveButton().click();
        settle();
    }

    function retentionColumn(label: string): HTMLElement {
        return Array.from(element.querySelectorAll<HTMLElement>('.data-retention__column')).find(
            (column) => column.querySelector('.data-retention__column-label')?.textContent?.trim() === label
        )!;
    }

    function chooseRetention(label: string, optionName: string): void {
        retentionColumn(label).querySelector<HTMLButtonElement>('.selector__btn')!.click();
        settle();
        const option = Array.from(document.querySelectorAll<HTMLElement>('.selector__option')).find(
            (candidate) => candidate.querySelector('.selector__text')?.textContent?.trim() === optionName
        )!;
        option.click();
        settle();
    }

    /** Unticks the existing member, so saving has a membership removal to commit. */
    function removeMember(): void {
        const memberRow = Array.from(element.querySelectorAll<HTMLElement>('.table-row')).find(
            (row) => row.querySelector('.user-email')?.textContent?.trim() === MEMBER.email
        )!;
        memberRow.querySelector<HTMLInputElement>('.table-cell.checkbox input[type="checkbox"]')!.click();
        settle();
    }

    function expectNoMembersRequest(): void {
        http.expectNone((request) => request.url.startsWith(MEMBERSHIPS_URL));
        http.verify();
    }

    function flushOrganizationUpdate(): void {
        http.expectOne({ method: 'PATCH', url: ORGANIZATION_URL }).flush(ORGANIZATION);
        settle();
    }

    it('saves the organization, then the retention, then commits the members, and closes', () => {
        chooseRetention('Sessions', '1 year');
        removeMember();

        clickSave();
        flushOrganizationUpdate();
        http.expectNone((request) => request.url.startsWith(MEMBERSHIPS_URL));
        http.expectOne({ method: 'PATCH', url: RETENTION_URL }).flush({
            ...RETENTION,
            sessions_days: 365,
            sessions_effective_days: 365,
        });
        settle();
        http.expectOne({ method: 'DELETE', url: `${MEMBERSHIPS_URL}${MEMBERSHIP_ID}/` }).flush(null);
        settle();

        http.verify();
        expect(dialogRef.close).toHaveBeenCalledWith(true);
        expect(toast.error).not.toHaveBeenCalled();
    });

    it('stops before the members commit and keeps the dialog open when the retention save fails', () => {
        chooseRetention('Sessions', '1 year');
        removeMember();

        clickSave();
        flushOrganizationUpdate();
        http.expectOne({ method: 'PATCH', url: RETENTION_URL }).flush(
            { message: 'Server error' },
            { status: 500, statusText: 'Internal Server Error' }
        );
        settle();

        expectNoMembersRequest();
        expect(dialogRef.close).not.toHaveBeenCalled();
        expect(toast.error).toHaveBeenCalledTimes(1);
        expect(saveButton().disabled).toBe(false);
    });

    it('shows retention field errors inline under their select, without a toast', () => {
        chooseRetention('Sessions', '1 year');
        removeMember();

        clickSave();
        flushOrganizationUpdate();
        http.expectOne({ method: 'PATCH', url: RETENTION_URL }).flush(
            { errors: [{ field: 'sessions_days', value: 365, reason: 'Exceeds the instance maximum.' }] },
            { status: 400, statusText: 'Bad Request' }
        );
        settle();

        expect(retentionColumn('Sessions').querySelector('app-validation-errors')?.textContent).toContain(
            'Exceeds the instance maximum.'
        );
        expect(toast.error).not.toHaveBeenCalled();
        expectNoMembersRequest();
        expect(dialogRef.close).not.toHaveBeenCalled();
        expect(saveButton().disabled).toBe(false);
    });

    it('re-enables Save and sends nothing when the retention lowering is cancelled', () => {
        chooseRetention('Sessions', '30 days');

        clickSave();
        expect(saveButton().disabled).toBe(true);

        confirmation.next(false);
        confirmation.complete();
        settle();

        expect(saveButton().disabled).toBe(false);
        expect(dialogRef.close).not.toHaveBeenCalled();
        http.verify();
    });

    it('saves the organization without a retention request when the retention is unchanged', () => {
        clickSave();
        flushOrganizationUpdate();

        http.expectNone({ method: 'PATCH', url: RETENTION_URL });
        http.verify();
        expect(dialogRef.close).toHaveBeenCalledWith(true);
        expect(toast.success).toHaveBeenCalledWith('Organization updated successfully.');
    });
});
