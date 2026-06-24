import { ChangeDetectionStrategy, Component, computed, input, OnInit, signal } from '@angular/core';
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
import { FullMembership, Organization, UserRole } from '@shared/models';

import { USER_ROLES } from '../../../../constants/user-roles-select-items.constant';
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
    organizations = input.required<Organization[]>();
    existingMemberships = input<FullMembership[]>([]);

    organizationsTableData = signal<TableRow[]>([]);
    searchTerm = signal('');
    isOrgsLoading = signal<boolean>(false);
    selectedOrganizations = signal<TableRow[]>([]);
    selectedOrgIds = computed(() => new Set(this.selectedOrganizations().map((r) => r['id'] as number)));

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

    protected readonly USER_ROLES: SelectItem[] = USER_ROLES;
}
