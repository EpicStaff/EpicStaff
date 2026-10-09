import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { AppTableComponent, ConfirmationDialogService } from '@shared/components';
import { GetRoleResponse, UserRole } from '@shared/models';
import { of } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { AggregatedUser } from '../../models/aggregated-user.model';
import { AdminUserService } from '../../services/admin/admin-user.service';
import { MembershipsService } from '../../services/admin/memberships.service';
import { OrganizationsStorageService } from '../../services/admin/organizations-storage.service';
import { RolesService } from '../../services/admin/roles.service';
import { CreateUserDialogComponent } from './create-user-dialog.component';
import { StepAssignToOrgComponent } from './steps/assign-to-org/step-assign-to-org.component';
import { StepUserDetailsComponent } from './steps/user-details/step-user-details.component';

const ORG_ID = 10;

// jsdom has no ResizeObserver; the overflow directives in the dialog's templates only need it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

function role(id: number, name: string): GetRoleResponse {
    return {
        id,
        name,
        description: null,
        is_built_in: true,
        scope: 'global',
        org_id: null,
        org: null,
        assigned_count: 0,
        permissions: [],
    };
}

const EDITED_USER: AggregatedUser = {
    id: 5,
    email: 'user5@example.com',
    displayName: 'User 5',
    avatarUrl: null,
    isSuperadmin: false,
    isActive: true,
    memberships: [],
};

function render() {
    TestBed.configureTestingModule({
        providers: [
            { provide: DialogRef, useValue: { close: vi.fn() } },
            { provide: DIALOG_DATA, useValue: { user: EDITED_USER } },
            { provide: AdminUserService, useValue: {} },
            { provide: MembershipsService, useValue: {} },
            {
                provide: OrganizationsStorageService,
                useValue: { getOrganizations: () => of([{ id: ORG_ID, name: 'Alpha' }]) },
            },
            { provide: ToastService, useValue: { success: vi.fn(), error: vi.fn() } },
            { provide: ConfirmationDialogService, useValue: {} },
            { provide: PermissionsService, useValue: { canInOrg: () => true } },
            {
                provide: RolesService,
                useValue: {
                    loadAssignableRoles: () =>
                        of({
                            built_in_roles: [role(UserRole.MEMBER, 'Member')],
                            results: [],
                            count: 0,
                            next: null,
                            previous: null,
                        }),
                },
            },
        ],
    });

    const fixture = TestBed.createComponent(CreateUserDialogComponent);
    fixture.detectChanges();
    fixture.detectChanges();

    const step = (): StepAssignToOrgComponent =>
        fixture.debugElement.query(By.directive(StepAssignToOrgComponent))
            .componentInstance as StepAssignToOrgComponent;
    const details = (): StepUserDetailsComponent =>
        fixture.debugElement.query(By.directive(StepUserDetailsComponent))
            .componentInstance as StepUserDetailsComponent;
    const selectOrg = (): void => {
        const table = fixture.debugElement.query(By.directive(AppTableComponent))
            .componentInstance as AppTableComponent;
        table.toggleRow(step().organizationsTableData()[0]);
        fixture.detectChanges();
    };

    return { fixture, component: fixture.componentInstance, step, details, selectOrg };
}

describe('CreateUserDialogComponent organization roles', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    it('blocks Save while a selected organization has no role', () => {
        const { fixture, component, step, selectOrg } = render();
        expect(component.submitDisabled()).toBe(false);

        selectOrg();
        expect(step().hasInvalidRow()).toBe(true);
        expect(component.submitDisabled()).toBe(true);

        step().onBulkRoleSelected(UserRole.MEMBER);
        fixture.detectChanges();
        expect(component.submitDisabled()).toBe(false);
        expect(step().getAssignments()).toEqual([{ orgId: ORG_ID, roleId: UserRole.MEMBER }]);
    });

    it('does not block a superadmin, whose organization assignments are skipped', () => {
        const { fixture, component, details, selectOrg } = render();
        selectOrg();
        expect(component.submitDisabled()).toBe(true);

        details().form.controls.superadmin.setValue(true);
        fixture.detectChanges();

        expect(component.submitDisabled()).toBe(false);
    });
});
