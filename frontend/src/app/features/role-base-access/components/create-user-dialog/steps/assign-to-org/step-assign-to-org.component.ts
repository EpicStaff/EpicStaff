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
import { FullMembership, GetRoleResponse, Organization, UserRole } from '@shared/models';
import { catchError, EMPTY } from 'rxjs';

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
    private destroyRef = inject(DestroyRef);

    organizations = input.required<Organization[]>();
    existingMemberships = input<FullMembership[]>([]);

    organizationsTableData = signal<TableRow[]>([]);
    searchTerm = signal('');
    isOrgsLoading = signal<boolean>(false);
    selectedOrganizations = signal<TableRow[]>([]);
    selectedOrgIds = computed(() => new Set(this.selectedOrganizations().map((r) => r['id'] as number)));

    /** Built-in role items — always applicable in every org. */
    private builtInRoleItems = signal<SelectItem[]>([]);
    /** Per-org custom role items (results grouped by `org_id`). */
    private customRoleItemsByOrg = signal<Map<number, SelectItem[]>>(new Map());

    filteredOrganizations = computed(() => {
        const term = this.searchTerm().toLowerCase().trim();
        if (!term) return this.organizationsTableData();
        return this.organizationsTableData().filter((row) => (row['name'] as string)?.toLowerCase().includes(term));
    });

    readonly columns: AppTableColumnDef[] = [
        { key: 'organization', label: 'Organization', width: '1fr' },
        { key: 'role', label: 'Role', width: '1fr' },
    ];

    selectionIds = signal<number[]>([]);

    ngOnInit(): void {
        const memberships = this.existingMemberships();
        const membershipMap = new Map(memberships.map((m) => [m.organization.id, m.role.id]));

        const rows: TableRow[] = this.organizations().map((org) => ({
            id: org.id,
            name: org.name,
            role: membershipMap.get(org.id) ?? UserRole.MEMBER,
        }));

        this.organizationsTableData.set(rows);
        this.selectionIds.set(memberships.map((m) => m.organization.id));

        this.loadRolesForOrgs();
    }

    /** Fetches built-ins and custom roles for all orgs presented on this step in a single request.
     *  Groups custom roles by `org_id` so each row can show `built-ins ∪ custom(row.orgId)`. */
    private loadRolesForOrgs(): void {
        const orgIds = this.organizations().map((o) => o.id);
        this.rolesService
            .loadRoles(orgIds.length ? { orgIds } : {})
            .pipe(
                catchError(() => EMPTY),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((res) => {
                // Superadmin is a platform-level grant, not an assignable membership role
                const assignableBuiltIns = res.built_in_roles.filter((r) => r.id !== UserRole.SUPER_ADMIN);
                this.builtInRoleItems.set(assignableBuiltIns.map(roleToSelectItem));
                const grouped = new Map<number, SelectItem[]>();
                for (const role of res.results) {
                    if (role.org_id === null) continue;
                    const list = grouped.get(role.org_id) ?? [];
                    list.push(roleToSelectItem(role));
                    grouped.set(role.org_id, list);
                }
                this.customRoleItemsByOrg.set(grouped);
            });
    }

    /** Role options for a specific org row: built-ins + that org's custom roles. */
    rolesForOrg(orgId: number): SelectItem[] {
        const custom = this.customRoleItemsByOrg().get(orgId) ?? [];
        return [...this.builtInRoleItems(), ...custom];
    }

    onSelection(items: TableRow[]): void {
        this.selectedOrganizations.set(items);
    }

    onRoleSelected(row: TableRow, value: unknown): void {
        row['role'] = value;
        const rowId = row['id'] as number;
        const currentIds = this.selectedOrganizations().map((r) => r['id'] as number);
        if (!currentIds.includes(rowId)) {
            this.selectionIds.set([...currentIds, rowId]);
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
