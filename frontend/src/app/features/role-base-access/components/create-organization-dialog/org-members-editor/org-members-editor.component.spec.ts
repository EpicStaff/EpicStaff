import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { AppTableComponent, TableRow } from '@shared/components';
import { AdminCreateUserResponse, GetRoleResponse, UserRole } from '@shared/models';
import { of } from 'rxjs';

import { PermissionsService } from '../../../../../services/auth/permissions.service';
import { ProfileService } from '../../../../../services/auth/profile.service';
import { ToastService } from '../../../../../services/notifications';
import { AdminUserService } from '../../../services/admin/admin-user.service';
import { MembershipsService } from '../../../services/admin/memberships.service';
import { RolesService } from '../../../services/admin/roles.service';
import { OrgMembersEditorComponent } from './org-members-editor.component';

const ORG_ID = 7;
const SELF_ID = 1;
const CUSTOM_ROLE_ID = 50;

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

/** Membership ids are derived from the user id so assertions can name them. */
function membershipIdOf(userId: number): number {
    return 100 + userId;
}

function user(id: number): AdminCreateUserResponse {
    return {
        id,
        email: `user${id}@example.com`,
        avatar_url: '',
        display_name: `User ${id}`,
        is_superadmin: false,
        is_active: true,
        memberships: [],
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
    };
}

function member(id: number, roleId: number): AdminCreateUserResponse {
    return {
        ...user(id),
        memberships: [
            {
                id: membershipIdOf(id),
                organization: { id: ORG_ID, name: 'Acme' },
                role: { id: roleId, name: `role-${roleId}` },
                joined_at: '2026-01-01T00:00:00Z',
            },
        ],
    };
}

function render(users: AdminCreateUserResponse[], mode: { isEditMode: boolean; organizationId: number | null }) {
    const memberships = {
        list: vi.fn(),
        create: vi.fn(() => of({})),
        updateRole: vi.fn(() => of({})),
        remove: vi.fn(() => of({})),
    };

    TestBed.configureTestingModule({
        providers: [
            { provide: PermissionsService, useValue: { isSuperadmin: true, canInOrg: () => true } },
            { provide: ProfileService, useValue: { currentUserSignal: signal({ id: SELF_ID }) } },
            {
                provide: AdminUserService,
                useValue: { getUsers: () => of({ count: users.length, next: null, previous: null, results: users }) },
            },
            { provide: MembershipsService, useValue: memberships },
            {
                provide: RolesService,
                useValue: {
                    loadAssignableRoles: () =>
                        of({
                            built_in_roles: [
                                role(UserRole.SUPER_ADMIN, 'Super Admin'),
                                role(UserRole.ORG_ADMIN, 'Org Admin'),
                                role(UserRole.MEMBER, 'Member'),
                                role(UserRole.VIEWER, 'Viewer'),
                            ],
                            results: [],
                            count: 0,
                            next: null,
                            previous: null,
                        }),
                },
            },
            { provide: ToastService, useValue: { error: vi.fn() } },
        ],
    });

    const fixture = TestBed.createComponent(OrgMembersEditorComponent);
    fixture.componentRef.setInput('isEditMode', mode.isEditMode);
    fixture.componentRef.setInput('organizationId', mode.organizationId);
    fixture.detectChanges();
    fixture.detectChanges();

    const component = fixture.componentInstance;
    const table = (): AppTableComponent =>
        fixture.debugElement.query(By.directive(AppTableComponent)).componentInstance as AppTableComponent;
    const row = (id: number): TableRow => component.usersTableData().find((r) => r['id'] === id)!;
    // Every user action is followed by change detection, as in the browser, so the table
    // receives fresh row data before the next action.
    const toggle = (id: number): void => {
        table().toggleRow(row(id));
        fixture.detectChanges();
    };
    const toggleAll = (): void => {
        table().toggleAll();
        fixture.detectChanges();
    };
    const pickBulkRole = (roleId: number): void => {
        component.onBulkRoleSelected(roleId);
        fixture.detectChanges();
    };
    const pickRowRole = (id: number, roleId: number): void => {
        component.onRoleSelected(row(id), roleId);
        fixture.detectChanges();
    };
    const commit = (): void => {
        component.commit(ORG_ID).subscribe();
    };
    const selectedRole = (id: number): unknown => component.selectedUsers().find((r) => r['id'] === id)?.['role'];
    const selectedIds = (): number[] =>
        component
            .selectedUsers()
            .map((r) => r['id'] as number)
            .sort((a, b) => a - b);
    const tableSelectedIds = (): unknown[] =>
        table()
            .selectedItems()
            .map((r) => r['id']);

    return {
        fixture,
        component,
        memberships,
        table,
        row,
        toggle,
        toggleAll,
        pickBulkRole,
        pickRowRole,
        commit,
        selectedRole,
        selectedIds,
        tableSelectedIds,
    };
}

const CREATE_MODE = { isEditMode: false, organizationId: null };
const EDIT_MODE = { isEditMode: true, organizationId: ORG_ID };

describe('OrgMembersEditorComponent "Role for selected" bulk dropdown', () => {
    it('renders next to the search with the assignable roles and no default', () => {
        const { fixture, component } = render([user(SELF_ID), user(2)], CREATE_MODE);
        const element = fixture.nativeElement as HTMLElement;

        expect(element.querySelector('.engage-bar app-select.bulk-role-select')?.textContent).toContain(
            'Role for selected'
        );
        expect(component.roleItems().map((item) => item.value)).not.toContain(UserRole.SUPER_ADMIN);
        expect(component.bulkRoleId()).toBeNull();
    });

    it('leaves newly selected rows role-less until a bulk role is picked', () => {
        const { component, toggle, selectedRole } = render([user(SELF_ID), user(2), user(3)], CREATE_MODE);

        toggle(2);
        toggle(3);

        expect(component.bulkRoleId()).toBeNull();
        expect(selectedRole(2)).toBeNull();
        expect(selectedRole(3)).toBeNull();
        expect(component.hasInvalidRow()).toBe(true);
    });

    it('assigns the bulk role to every selected row after "select all"', () => {
        const { component, row, toggleAll, pickBulkRole, selectedIds } = render(
            [user(SELF_ID), user(2), user(3), user(4)],
            CREATE_MODE
        );

        toggleAll();
        pickBulkRole(UserRole.MEMBER);

        expect(selectedIds()).toEqual([2, 3, 4]);
        expect(component.selectedUsers().every((r) => r['role'] === UserRole.MEMBER)).toBe(true);
        expect([2, 3, 4].map((id) => row(id)['role'])).toEqual([UserRole.MEMBER, UserRole.MEMBER, UserRole.MEMBER]);
        expect(component.hasInvalidRow()).toBe(false);
    });

    it('gives the bulk role to a role-less user selected after the pick', () => {
        const { component, toggle, row, pickBulkRole, selectedRole } = render(
            [user(SELF_ID), user(2), user(3)],
            CREATE_MODE
        );

        toggle(2);
        pickBulkRole(UserRole.VIEWER);
        toggle(3);

        expect(selectedRole(3)).toBe(UserRole.VIEWER);
        expect(row(3)['role']).toBe(UserRole.VIEWER);
        expect(component.hasInvalidRow()).toBe(false);
    });

    it('keeps a manual per-row override when the selection changes later', () => {
        const { toggle, pickBulkRole, pickRowRole, selectedRole } = render(
            [user(SELF_ID), user(2), user(3), user(4)],
            CREATE_MODE
        );

        toggle(2);
        pickBulkRole(UserRole.MEMBER);
        pickRowRole(2, UserRole.VIEWER);
        toggle(3);
        toggle(4);

        expect(selectedRole(2)).toBe(UserRole.VIEWER);
        expect(selectedRole(3)).toBe(UserRole.MEMBER);
        expect(selectedRole(4)).toBe(UserRole.MEMBER);
    });

    it('re-applies a re-picked bulk role to all currently selected rows', () => {
        const { toggle, pickBulkRole, pickRowRole, selectedRole } = render(
            [user(SELF_ID), user(2), user(3)],
            CREATE_MODE
        );

        toggle(2);
        toggle(3);
        pickBulkRole(UserRole.MEMBER);
        pickRowRole(2, UserRole.VIEWER);
        pickBulkRole(UserRole.MEMBER);

        expect(selectedRole(2)).toBe(UserRole.MEMBER);
        expect(selectedRole(3)).toBe(UserRole.MEMBER);
    });

    it('stays usable with nothing selected and applies to rows selected afterwards', () => {
        const { component, toggle, pickBulkRole, selectedRole } = render([user(SELF_ID), user(2)], CREATE_MODE);

        pickBulkRole(CUSTOM_ROLE_ID);
        expect(component.bulkRoleId()).toBe(CUSTOM_ROLE_ID);
        expect(component.selectedUsers()).toEqual([]);

        toggle(2);
        expect(selectedRole(2)).toBe(CUSTOM_ROLE_ID);
    });

    it('never changes the current user row, which edit mode preselects', () => {
        const { row, pickBulkRole, selectedIds, selectedRole } = render(
            [member(SELF_ID, UserRole.ORG_ADMIN), member(2, UserRole.VIEWER)],
            EDIT_MODE
        );
        expect(selectedIds()).toEqual([SELF_ID, 2]);

        pickBulkRole(UserRole.MEMBER);

        expect(selectedRole(SELF_ID)).toBe(UserRole.ORG_ADMIN);
        expect(row(SELF_ID)['role']).toBe(UserRole.ORG_ADMIN);
        expect(selectedRole(2)).toBe(UserRole.MEMBER);
    });

    it('keeps the original role of an existing member that was not selected at bulk time', () => {
        const { toggle, row, pickBulkRole, selectedIds, selectedRole } = render(
            [user(SELF_ID), member(2, UserRole.VIEWER), member(3, UserRole.ORG_ADMIN)],
            EDIT_MODE
        );
        expect(selectedIds()).toEqual([2, 3]);

        toggle(2);
        pickBulkRole(UserRole.MEMBER);
        expect(row(2)['role']).toBe(UserRole.VIEWER);
        expect(selectedRole(3)).toBe(UserRole.MEMBER);

        toggle(2);
        expect(selectedRole(2)).toBe(UserRole.VIEWER);
    });
});

describe('OrgMembersEditorComponent commit after a bulk role', () => {
    it('updates only changed existing members, creates only new rows and never touches the own membership', () => {
        const { memberships, toggle, pickBulkRole, commit } = render(
            [
                member(SELF_ID, UserRole.ORG_ADMIN),
                member(2, UserRole.VIEWER),
                member(3, UserRole.MEMBER),
                member(4, UserRole.VIEWER),
                user(5),
                user(6),
            ],
            EDIT_MODE
        );
        toggle(4);
        toggle(5);
        pickBulkRole(UserRole.MEMBER);

        commit();

        expect(memberships.updateRole.mock.calls).toEqual([[membershipIdOf(2), { role_id: UserRole.MEMBER }]]);
        expect(memberships.create.mock.calls).toEqual([[{ org_id: ORG_ID, user_id: 5, role_id: UserRole.MEMBER }]]);
        expect(memberships.remove.mock.calls).toEqual([[membershipIdOf(4)]]);
    });

    it('keeps the own membership through select all with a bulk role', () => {
        const { memberships, toggleAll, pickBulkRole, commit, selectedIds } = render(
            [member(SELF_ID, UserRole.ORG_ADMIN), member(2, UserRole.MEMBER), user(3)],
            EDIT_MODE
        );
        expect(selectedIds()).toEqual([SELF_ID, 2]);

        toggleAll();
        expect(selectedIds()).toEqual([SELF_ID, 2, 3]);
        pickBulkRole(UserRole.VIEWER);

        commit();

        expect(memberships.updateRole.mock.calls).toEqual([[membershipIdOf(2), { role_id: UserRole.VIEWER }]]);
        expect(memberships.create.mock.calls).toEqual([[{ org_id: ORG_ID, user_id: 3, role_id: UserRole.VIEWER }]]);
        expect(memberships.remove).not.toHaveBeenCalled();
    });

    it('keeps the own membership through deselect all', () => {
        const { memberships, toggleAll, commit, selectedIds, tableSelectedIds } = render(
            [member(SELF_ID, UserRole.ORG_ADMIN), member(2, UserRole.MEMBER), member(3, UserRole.VIEWER)],
            EDIT_MODE
        );

        toggleAll();
        expect(selectedIds()).toEqual([SELF_ID]);
        expect(tableSelectedIds()).toEqual([SELF_ID]);

        commit();

        expect(memberships.updateRole).not.toHaveBeenCalled();
        expect(memberships.create).not.toHaveBeenCalled();
        expect(memberships.remove.mock.calls).toEqual([[membershipIdOf(2)], [membershipIdOf(3)]]);
    });
});

describe('OrgMembersEditorComponent selection sync with the table', () => {
    it('adds a role-picked unselected row to the existing selection instead of replacing it', () => {
        const { toggle, pickRowRole, selectedIds, selectedRole, tableSelectedIds } = render(
            [user(SELF_ID), user(2), user(3), user(4), user(5)],
            CREATE_MODE
        );
        toggle(2);
        toggle(3);
        toggle(4);

        pickRowRole(5, UserRole.VIEWER);

        expect(selectedIds()).toEqual([2, 3, 4, 5]);
        expect(tableSelectedIds()).toEqual([2, 3, 4, 5]);
        expect(selectedRole(5)).toBe(UserRole.VIEWER);
    });

    it('keeps the preselected members in edit mode when another row gets a role', () => {
        const { toggle, pickRowRole, selectedIds, tableSelectedIds } = render(
            [user(SELF_ID), member(2, UserRole.VIEWER), user(3), user(4)],
            EDIT_MODE
        );
        toggle(3);

        pickRowRole(4, UserRole.MEMBER);

        expect(selectedIds()).toEqual([2, 3, 4]);
        expect(tableSelectedIds()).toEqual([2, 3, 4]);
    });

    it('selects rows again after deselect all', () => {
        const { toggle, toggleAll, pickRowRole, selectedIds, tableSelectedIds } = render(
            [user(SELF_ID), user(2), user(3), user(4)],
            CREATE_MODE
        );
        toggle(2);
        toggle(3);
        toggleAll();
        toggleAll();
        expect(selectedIds()).toEqual([]);

        toggle(3);
        expect(selectedIds()).toEqual([3]);
        expect(tableSelectedIds()).toEqual([3]);

        pickRowRole(4, UserRole.MEMBER);
        expect(selectedIds()).toEqual([3, 4]);
        expect(tableSelectedIds()).toEqual([3, 4]);
    });
});
