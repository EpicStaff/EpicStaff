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
import { ActionCode, FullMembership, Organization, ResourceCode, UserRole } from '@shared/models';
import { catchError, forkJoin, of } from 'rxjs';

import { PermissionsService } from '../../../../../../services/auth/permissions.service';
import { RolesService } from '../../../../services/admin/roles.service';
import { haveSameIds, newRoleLessRows, roleToSelectItem, withRole } from '../../../../utils';
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
    disabled = input<boolean>(false);

    organizationsTableData = signal<TableRow[]>([]);
    searchTerm = signal('');
    isOrgsLoading = signal<boolean>(false);
    selectedOrganizations = signal<TableRow[]>([]);
    private roleItemsByOrg = signal<Map<number, SelectItem[]>>(new Map());
    /** Built-in roles only: custom roles belong to one org, so they stay a per-row choice. */
    readonly bulkRoleItems = signal<SelectItem[]>([]);
    bulkRoleId = signal<number | null>(null);

    selectedOrgIds = computed(() => new Set(this.selectedOrganizations().map((r) => r['id'] as number)));
    /**
     * Fed to the table's `initialSelectedIds`, which re-applies the ids and emits `selectionChange`
     * on every new value. Changing only when the id set changes lets that round trip settle.
     */
    selectionIds = computed(() => [...this.selectedOrgIds()], { equal: haveSameIds });
    readonly hasInvalidRow = computed(() => this.selectedOrganizations().some((r) => r['role'] == null));

    /**
     * Search as the table's display-only `rowVisible` filter: hidden rows keep their selection.
     * A new function per search term is what tells the table to re-filter; `null` shows all rows.
     */
    matchesSearch = computed<((row: TableRow) => boolean) | null>(() => {
        const term = this.searchTerm().toLowerCase().trim();
        if (!term) return null;
        return (row) => (row['name'] as string)?.toLowerCase().includes(term);
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
                ResourceCode.Memberships,
                this.isEditMode() ? ActionCode.Update : ActionCode.Create
            )
        );

        const rows: TableRow[] = assignableOrgs.map((org) => ({
            id: org.id,
            name: org.name,
            role: membershipMap.get(org.id) ?? null,
        }));

        this.organizationsTableData.set(rows);
        this.selectedOrganizations.set(rows.filter((row) => membershipMap.has(row['id'] as number)));

        const roleReadableOrgIds = assignableOrgs
            .map((o) => o.id)
            .filter((id) => this.permissionsService.canInOrg(id, ResourceCode.Roles, ActionCode.Read));
        this.loadRolesForOrgs(roleReadableOrgIds);
    }

    /** Fetches built-ins and custom roles for orgs where the actor can read roles,
     *  then materializes `built-ins ∪ custom(orgId)` per allowed org. */
    private loadRolesForOrgs(allowedOrgIds: number[]): void {
        if (!allowedOrgIds.length) return;

        const perOrg$ = allowedOrgIds.map((orgId) =>
            this.rolesService
                .loadAssignableRoles(orgId)
                .pipe(catchError(() => of({ built_in_roles: [], results: [], count: 0, next: null, previous: null })))
        );

        forkJoin(perOrg$)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((responses) => {
                const byOrg = new Map<number, SelectItem[]>();
                const bulkItemsById = new Map<number, SelectItem>();
                responses.forEach((res, i) => {
                    const orgId = allowedOrgIds[i];
                    const builtIns = res.built_in_roles
                        .filter((r) => r.id !== UserRole.SUPER_ADMIN)
                        .map(roleToSelectItem);
                    builtIns.forEach((item) => bulkItemsById.set(item.value, item));
                    byOrg.set(orgId, [
                        ...builtIns,
                        ...res.results.filter((r) => r.org_id === orgId).map(roleToSelectItem),
                    ]);
                });
                this.roleItemsByOrg.set(byOrg);

                // The backend filters built-ins per org down to the ones the actor may assign there,
                // so the bulk list is their union. Sorted by name, the backend's order for built-ins.
                this.bulkRoleItems.set([...bulkItemsById.values()].sort((a, b) => a.name.localeCompare(b.name)));
            });
    }

    /** Role options for a specific org row. Empty if actor cannot read roles in that org. */
    rolesForOrg(orgId: number): SelectItem[] {
        return this.roleItemsByOrg().get(orgId) ?? [];
    }

    readonly isRowSelectable = (): boolean => !this.disabled();

    onSelection(items: TableRow[]): void {
        const previouslySelectedIds = this.selectedOrgIds();
        const bulkRoleId = this.bulkRoleId();
        let selection = items;

        if (bulkRoleId !== null) {
            // Only role-less rows that just joined the selection follow the bulk role,
            // so manual overrides and existing memberships keep the role they already have.
            const idsToAssign = new Set(
                newRoleLessRows(items, previouslySelectedIds)
                    .filter((r) => this.isRoleValidForOrg(r['id'] as number, bulkRoleId))
                    .map((r) => r['id'] as number)
            );
            if (idsToAssign.size) {
                this.setRoleInTableData(idsToAssign, bulkRoleId);
                selection = withRole(items, idsToAssign, bulkRoleId);
            }
        }

        this.selectedOrganizations.set(selection);
    }

    onRoleSelected(row: TableRow, value: unknown): void {
        const rowId = row['id'] as number;
        const patch = (r: TableRow): TableRow => (r['id'] === rowId ? { ...r, role: value } : r);
        this.organizationsTableData.update((rows) => rows.map(patch));

        if (this.selectedOrgIds().has(rowId)) {
            this.selectedOrganizations.update((rows) => rows.map(patch));
        } else {
            this.selectedOrganizations.update((rows) => [...rows, patch(row)]);
        }
    }

    onBulkRoleSelected(value: unknown): void {
        if (typeof value !== 'number') return;
        this.bulkRoleId.set(value);

        const idsToAssign = new Set(
            this.selectedOrganizations()
                .map((r) => r['id'] as number)
                .filter((orgId) => this.isRoleValidForOrg(orgId, value))
        );
        if (!idsToAssign.size) return;
        this.setRoleInTableData(idsToAssign, value);
        this.selectedOrganizations.update((rows) => withRole(rows, idsToAssign, value));
    }

    getAssignments(): OrgAssignment[] {
        return this.selectedOrganizations()
            .filter((row) => row['role'] != null)
            .map((row) => ({
                orgId: row['id'] as number,
                roleId: row['role'] as number,
            }));
    }

    /** Empty role list (no Roles read permission in that org) means no role is valid there. */
    private isRoleValidForOrg(orgId: number, roleId: number): boolean {
        return this.rolesForOrg(orgId).some((item) => item.value === roleId);
    }

    /**
     * Updates the table data only. Callers patch the selection too: the table emits selected rows
     * as snapshots and does not re-emit when its data changes.
     */
    private setRoleInTableData(orgIds: Set<number>, roleId: number): void {
        this.organizationsTableData.update((rows) => withRole(rows, orgIds, roleId));
    }
}
