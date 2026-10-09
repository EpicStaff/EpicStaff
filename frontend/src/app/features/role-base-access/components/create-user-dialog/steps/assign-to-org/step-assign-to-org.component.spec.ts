import { TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { AppTableComponent, SelectComponent, TableRow } from '@shared/components';
import { FullMembership, GetRoleResponse, Organization, ResourceCode, UserRole } from '@shared/models';
import { of } from 'rxjs';

import { PermissionsService } from '../../../../../../services/auth/permissions.service';
import { RolesService } from '../../../../services/admin/roles.service';
import { StepAssignToOrgComponent } from './step-assign-to-org.component';

const ALPHA_ID = 10;
const BETA_ID = 20;
/** The actor may add members here but cannot read its roles, so its rows have no role options. */
const NO_ROLES_ID = 30;
/** The actor may not add members here, so the org is not listed. */
const LOCKED_ID = 40;
const ALPHA_CUSTOM_ROLE_ID = 60;
const BETA_CUSTOM_ROLE_ID = 70;

const ORGANIZATIONS: Organization[] = [
    { id: ALPHA_ID, name: 'Alpha' },
    { id: BETA_ID, name: 'Beta' },
    { id: NO_ROLES_ID, name: 'No roles' },
    { id: LOCKED_ID, name: 'Locked' },
];

function role(id: number, name: string, orgId: number | null = null): GetRoleResponse {
    return {
        id,
        name,
        description: null,
        is_built_in: orgId === null,
        scope: orgId === null ? 'global' : 'org',
        org_id: orgId,
        org: orgId === null ? null : { id: orgId, name: `org-${orgId}` },
        assigned_count: 0,
        permissions: [],
    };
}

function membership(orgId: number, roleId: number): FullMembership {
    return {
        id: 100 + orgId,
        organization: { id: orgId, name: `org-${orgId}` },
        role: { id: roleId, name: `role-${roleId}` },
        joined_at: '2026-01-01T00:00:00Z',
    };
}

function canInOrg(orgId: number, resource: ResourceCode): boolean {
    if (orgId === LOCKED_ID) return false;
    if (orgId === NO_ROLES_ID) return resource !== ResourceCode.Roles;
    return true;
}

/** Built-ins as the backend lists them: ordered by name. */
const ALL_BUILT_INS: GetRoleResponse[] = [
    role(UserRole.MEMBER, 'Member'),
    role(UserRole.ORG_ADMIN, 'Org Admin'),
    role(UserRole.SUPER_ADMIN, 'Super Admin'),
    role(UserRole.VIEWER, 'Viewer'),
];

function render(
    options: {
        isEditMode?: boolean;
        memberships?: FullMembership[];
        disabled?: boolean;
        /** Per-org built-ins, for an actor whose assignable roles differ between orgs. */
        builtInsByOrg?: Map<number, GetRoleResponse[]>;
    } = {}
) {
    const loadAssignableRoles = vi.fn((orgId: number) =>
        of({
            built_in_roles: options.builtInsByOrg?.get(orgId) ?? ALL_BUILT_INS,
            results: [
                role(ALPHA_CUSTOM_ROLE_ID, 'Alpha reviewer', ALPHA_ID),
                role(BETA_CUSTOM_ROLE_ID, 'Beta reviewer', BETA_ID),
            ],
            count: 2,
            next: null,
            previous: null,
        })
    );

    TestBed.configureTestingModule({
        providers: [
            { provide: PermissionsService, useValue: { canInOrg } },
            { provide: RolesService, useValue: { loadAssignableRoles } },
        ],
    });

    const fixture = TestBed.createComponent(StepAssignToOrgComponent);
    fixture.componentRef.setInput('organizations', ORGANIZATIONS);
    fixture.componentRef.setInput('existingMemberships', options.memberships ?? []);
    fixture.componentRef.setInput('isEditMode', options.isEditMode ?? false);
    fixture.componentRef.setInput('disabled', options.disabled ?? false);
    fixture.detectChanges();
    fixture.detectChanges();

    const component = fixture.componentInstance;
    const table = (): AppTableComponent =>
        fixture.debugElement.query(By.directive(AppTableComponent)).componentInstance as AppTableComponent;
    const row = (id: number): TableRow => component.organizationsTableData().find((r) => r['id'] === id)!;
    // Every user action is followed by change detection, as in the browser, so the table
    // receives fresh row data before the next action.
    const toggle = (id: number): void => {
        table().toggleRow(row(id));
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
    const search = (term: string): void => {
        component.searchTerm.set(term);
        fixture.detectChanges();
    };
    const selectedRole = (id: number): unknown =>
        component.selectedOrganizations().find((r) => r['id'] === id)?.['role'];
    const selectedIds = (): number[] =>
        component
            .selectedOrganizations()
            .map((r) => r['id'] as number)
            .sort((a, b) => a - b);
    const tableSelectedIds = (): unknown[] =>
        table()
            .selectedItems()
            .map((r) => r['id']);
    const assignments = () => [...component.getAssignments()].sort((a, b) => a.orgId - b.orgId);

    return {
        fixture,
        component,
        loadAssignableRoles,
        table,
        row,
        toggle,
        pickBulkRole,
        pickRowRole,
        search,
        selectedRole,
        selectedIds,
        tableSelectedIds,
        assignments,
    };
}

describe('StepAssignToOrgComponent "Role for selected" bulk dropdown', () => {
    it('offers only built-in roles, without Super Admin and without custom roles', () => {
        const { fixture, component, loadAssignableRoles } = render();
        const element = fixture.nativeElement as HTMLElement;

        expect(element.querySelector('.engage-bar app-select.bulk-role-select')?.textContent).toContain(
            'Role for selected'
        );
        expect(component.bulkRoleItems().map((item) => item.value)).toEqual([
            UserRole.MEMBER,
            UserRole.ORG_ADMIN,
            UserRole.VIEWER,
        ]);
        expect(component.rolesForOrg(ALPHA_ID).map((item) => item.value)).toContain(ALPHA_CUSTOM_ROLE_ID);
        expect(loadAssignableRoles.mock.calls).toEqual([[ALPHA_ID], [BETA_ID]]);
    });

    it('offers the union of per-org built-ins and applies a role only where the actor may assign it', () => {
        // The actor is capped at Member/Viewer in Alpha (listed first) but may assign Org Admin in Beta.
        const { component, toggle, pickBulkRole, selectedRole, assignments } = render({
            isEditMode: true,
            memberships: [membership(ALPHA_ID, UserRole.VIEWER)],
            builtInsByOrg: new Map([
                [ALPHA_ID, [role(UserRole.MEMBER, 'Member'), role(UserRole.VIEWER, 'Viewer')]],
                [BETA_ID, ALL_BUILT_INS],
            ]),
        });
        expect(component.bulkRoleItems().map((item) => item.value)).toEqual([
            UserRole.MEMBER,
            UserRole.ORG_ADMIN,
            UserRole.VIEWER,
        ]);

        toggle(BETA_ID);
        pickBulkRole(UserRole.ORG_ADMIN);

        expect(selectedRole(ALPHA_ID)).toBe(UserRole.VIEWER);
        expect(selectedRole(BETA_ID)).toBe(UserRole.ORG_ADMIN);
        expect(assignments()).toEqual([
            { orgId: ALPHA_ID, roleId: UserRole.VIEWER },
            { orgId: BETA_ID, roleId: UserRole.ORG_ADMIN },
        ]);
    });

    it('gives new rows no default role', () => {
        const { component, toggle, selectedRole, assignments } = render();

        toggle(ALPHA_ID);

        expect(component.bulkRoleId()).toBeNull();
        expect(selectedRole(ALPHA_ID)).toBeNull();
        expect(component.hasInvalidRow()).toBe(true);
        expect(assignments()).toEqual([]);
    });

    it('applies the bulk role only to selected orgs where it is a valid choice', () => {
        const { component, toggle, row, pickBulkRole, selectedRole, assignments } = render();
        toggle(ALPHA_ID);
        toggle(BETA_ID);
        toggle(NO_ROLES_ID);

        pickBulkRole(UserRole.MEMBER);

        expect(selectedRole(ALPHA_ID)).toBe(UserRole.MEMBER);
        expect(selectedRole(BETA_ID)).toBe(UserRole.MEMBER);
        expect(selectedRole(NO_ROLES_ID)).toBeNull();
        expect(row(NO_ROLES_ID)['role']).toBeNull();
        expect(component.hasInvalidRow()).toBe(true);
        expect(assignments()).toEqual([
            { orgId: ALPHA_ID, roleId: UserRole.MEMBER },
            { orgId: BETA_ID, roleId: UserRole.MEMBER },
        ]);
    });

    it('gives the bulk role to role-less orgs selected later, where it is valid', () => {
        const { component, toggle, pickBulkRole, selectedRole, assignments } = render();

        pickBulkRole(UserRole.VIEWER);
        expect(component.selectedOrganizations()).toEqual([]);

        toggle(BETA_ID);
        toggle(NO_ROLES_ID);

        expect(selectedRole(BETA_ID)).toBe(UserRole.VIEWER);
        expect(selectedRole(NO_ROLES_ID)).toBeNull();
        expect(assignments()).toEqual([{ orgId: BETA_ID, roleId: UserRole.VIEWER }]);
    });

    it('keeps a manual per-row override and re-applies on every bulk pick', () => {
        const { toggle, pickBulkRole, pickRowRole, selectedRole } = render();
        toggle(ALPHA_ID);
        pickBulkRole(UserRole.MEMBER);
        pickRowRole(ALPHA_ID, ALPHA_CUSTOM_ROLE_ID);

        toggle(BETA_ID);
        expect(selectedRole(ALPHA_ID)).toBe(ALPHA_CUSTOM_ROLE_ID);
        expect(selectedRole(BETA_ID)).toBe(UserRole.MEMBER);

        pickBulkRole(UserRole.MEMBER);
        expect(selectedRole(ALPHA_ID)).toBe(UserRole.MEMBER);
    });

    it('changes an existing membership only when it is selected at apply time', () => {
        const { toggle, row, pickBulkRole, selectedIds, selectedRole, assignments } = render({
            isEditMode: true,
            memberships: [membership(ALPHA_ID, UserRole.VIEWER), membership(BETA_ID, UserRole.ORG_ADMIN)],
        });
        expect(selectedIds()).toEqual([ALPHA_ID, BETA_ID]);

        toggle(BETA_ID);
        pickBulkRole(UserRole.MEMBER);
        expect(selectedRole(ALPHA_ID)).toBe(UserRole.MEMBER);
        expect(row(BETA_ID)['role']).toBe(UserRole.ORG_ADMIN);

        toggle(BETA_ID);
        expect(selectedRole(BETA_ID)).toBe(UserRole.ORG_ADMIN);
        expect(assignments()).toEqual([
            { orgId: ALPHA_ID, roleId: UserRole.MEMBER },
            { orgId: BETA_ID, roleId: UserRole.ORG_ADMIN },
        ]);
    });

    it('is disabled, and leaves existing memberships alone, when the step is disabled', () => {
        const { fixture, table, selectedIds, tableSelectedIds } = render({
            isEditMode: true,
            memberships: [membership(ALPHA_ID, UserRole.VIEWER)],
            disabled: true,
        });
        const bulkSelect = fixture.debugElement.query(By.css('app-select.bulk-role-select'))
            .componentInstance as SelectComponent;

        expect(bulkSelect.isDisabled()).toBe(true);

        table().toggleAll();
        fixture.detectChanges();
        expect(selectedIds()).toEqual([ALPHA_ID]);
        expect(tableSelectedIds()).toEqual([ALPHA_ID]);
    });
});

describe('StepAssignToOrgComponent role pick on an unselected row', () => {
    it('adds the org to the existing selection instead of replacing it', () => {
        const { toggle, pickRowRole, selectedIds, selectedRole, tableSelectedIds } = render();
        toggle(ALPHA_ID);
        toggle(NO_ROLES_ID);

        pickRowRole(BETA_ID, BETA_CUSTOM_ROLE_ID);

        expect(selectedIds()).toEqual([ALPHA_ID, BETA_ID, NO_ROLES_ID]);
        expect(tableSelectedIds()).toEqual([ALPHA_ID, BETA_ID, NO_ROLES_ID]);
        expect(selectedRole(BETA_ID)).toBe(BETA_CUSTOM_ROLE_ID);
    });

    it('keeps the preselected memberships in edit mode', () => {
        const { pickRowRole, selectedIds, tableSelectedIds } = render({
            isEditMode: true,
            memberships: [membership(ALPHA_ID, UserRole.VIEWER)],
        });

        pickRowRole(BETA_ID, UserRole.MEMBER);

        expect(selectedIds()).toEqual([ALPHA_ID, BETA_ID]);
        expect(tableSelectedIds()).toEqual([ALPHA_ID, BETA_ID]);
    });
});

describe('StepAssignToOrgComponent search', () => {
    it('keeps orgs hidden by the search selected, with their roles in the assignments', () => {
        const { table, fixture, toggle, search, selectedIds, tableSelectedIds, assignments } = render({
            isEditMode: true,
            memberships: [membership(ALPHA_ID, UserRole.VIEWER), membership(BETA_ID, UserRole.ORG_ADMIN)],
        });

        search('beta');
        expect(selectedIds()).toEqual([ALPHA_ID, BETA_ID]);
        expect(tableSelectedIds()).toEqual([ALPHA_ID, BETA_ID]);

        table().toggleAll();
        fixture.detectChanges();
        expect(selectedIds()).toEqual([ALPHA_ID]);
        toggle(BETA_ID);

        search('');
        expect(selectedIds()).toEqual([ALPHA_ID, BETA_ID]);
        expect(tableSelectedIds()).toEqual([ALPHA_ID, BETA_ID]);
        expect(assignments()).toEqual([
            { orgId: ALPHA_ID, roleId: UserRole.VIEWER },
            { orgId: BETA_ID, roleId: UserRole.ORG_ADMIN },
        ]);
    });
});
