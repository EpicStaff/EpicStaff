import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, input, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
    AppTableCellDirective,
    AppTableColumnDef,
    AppTableComponent,
    LoadingSpinnerComponent,
    SearchComponent,
    SelectComponent,
    SelectItem,
    TableRow,
} from '@shared/components';
import { ActionCode, FullMembership, GetRoleResponse, Organization, ResourceCode, UserRole } from '@shared/models';
import { catchError, EMPTY } from 'rxjs';

import { PermissionsService } from '../../../../../../services/auth/permissions.service';
import { RolesService } from '../../../../services/admin/roles.service';
import { OrgAvatarComponent } from '../../../org-avatar/org-avatar.component';

export interface OrgAssignment {
    orgId: number;
    roleId: number;
}

@Component({
    selector: 'app-step-assign-to-org',
    templateUrl: './step-assign-to-org.component.html',
    styleUrls: ['./step-assign-to-org.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [
        AppTableCellDirective,
        AppTableComponent,
        SelectComponent,
        SearchComponent,
        OrgAvatarComponent,
        LoadingSpinnerComponent,
    ],
})
export class StepAssignToOrgComponent implements OnInit {
    private rolesService = inject(RolesService);
    private permissionsService = inject(PermissionsService);
    private destroyRef = inject(DestroyRef);

    organizations = input.required<Organization[]>();
    existingMemberships = input<FullMembership[]>([]);
    isEditMode = input.required<boolean>();

    organizationsTableData = signal<TableRow[]>([]);
    searchTerm = signal('');
    isOrgsLoading = signal<boolean>(false);
    selectedOrganizations = signal<TableRow[]>([]);
    selectionIds = signal<number[]>([]);
    private roleItemsByOrg = signal<Map<number, SelectItem[]>>(new Map());

    selectedOrgIds = computed(() => new Set(this.selectedOrganizations().map((r) => r['id'] as number)));
    readonly hasInvalidRow = computed(() => this.selectedOrganizations().some((r) => r['role'] == null));

    filteredOrganizations = computed(() => {
        const term = this.searchTerm().toLowerCase().trim();
        if (!term) return this.organizationsTableData();
        return this.organizationsTableData().filter((row) => (row['name'] as string)?.toLowerCase().includes(term));
    });

    readonly columns: AppTableColumnDef[] = [
        { key: 'organization', label: 'Organization', width: '1fr' },
        { key: 'role', label: 'Role', width: '1fr' },
    ];

    ngOnInit(): void {
        const memberships = this.existingMemberships();
        const membershipMap = new Map(memberships.map((m) => [m.organization.id, m.role.id]));

        const assignableOrgs = this.organizations().filter((org) =>
            this.permissionsService.canInOrg(
                org.id,
                ResourceCode.Users,
                this.isEditMode() ? ActionCode.Update : ActionCode.Create
            )
        );

        const defaultOrgRole = (orgId: number) =>
            this.permissionsService.canInOrg(orgId, ResourceCode.Roles, ActionCode.Read) ? UserRole.MEMBER : null;

        const rows: TableRow[] = assignableOrgs.map((org) => ({
            id: org.id,
            name: org.name,
            role: membershipMap.get(org.id) || defaultOrgRole(org.id),
        }));

        const assignableOrgIds = new Set(assignableOrgs.map((o) => o.id));
        this.organizationsTableData.set(rows);
        this.selectionIds.set(
            memberships.filter((m) => assignableOrgIds.has(m.organization.id)).map((m) => m.organization.id)
        );

        const roleReadableOrgIds = assignableOrgs
            .map((o) => o.id)
            .filter((id) => this.permissionsService.canInOrg(id, ResourceCode.Roles, ActionCode.Read));
        this.loadRolesForOrgs(roleReadableOrgIds);
    }

    /** Fetches built-ins and custom roles for orgs where the actor can read roles,
     *  then materializes `built-ins ∪ custom(orgId)` per allowed org. */
    private loadRolesForOrgs(allowedOrgIds: number[]): void {
        if (!allowedOrgIds.length) return;

        this.rolesService
            .loadRoles({ orgIds: allowedOrgIds })
            .pipe(
                catchError(() => EMPTY),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((res) => {
                // Superadmin is a platform-level grant, not an assignable membership role
                const builtIns = res.built_in_roles.filter((r) => r.id !== UserRole.SUPER_ADMIN).map(roleToSelectItem);
                const byOrg = new Map<number, SelectItem[]>(allowedOrgIds.map((id) => [id, [...builtIns]]));
                for (const role of res.results) {
                    if (role.org_id === null) continue;
                    byOrg.get(role.org_id)?.push(roleToSelectItem(role));
                }
                this.roleItemsByOrg.set(byOrg);
            });
    }

    /** Role options for a specific org row. Empty if actor cannot read roles in that org. */
    rolesForOrg(orgId: number): SelectItem[] {
        return this.roleItemsByOrg().get(orgId) ?? [];
    }

    onSelection(items: TableRow[]): void {
        this.selectedOrganizations.set(items);
    }

    onRoleSelected(row: TableRow, value: unknown): void {
        const rowId = row['id'] as number;
        const patch = (r: TableRow): TableRow => (r['id'] === rowId ? { ...r, role: value } : r);
        this.organizationsTableData.update((rows) => rows.map(patch));

        if (this.selectedOrgIds().has(rowId)) {
            this.selectedOrganizations.update((rows) => rows.map(patch));
        } else {
            this.selectionIds.set([...this.selectionIds(), rowId]);
        }
    }

    getAssignments(): OrgAssignment[] {
        return this.selectedOrganizations()
            .filter((row) => row['role'] != null)
            .map((row) => ({
                orgId: row['id'] as number,
                roleId: row['role'] as number,
            }));
    }
}

function roleToSelectItem(role: GetRoleResponse): SelectItem<number> {
    return { name: role.name, value: role.id };
}
