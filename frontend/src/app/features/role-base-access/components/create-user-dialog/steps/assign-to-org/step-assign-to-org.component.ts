import { Overlay, OverlayModule, OverlayPositionBuilder, OverlayRef } from '@angular/cdk/overlay';
import { TemplatePortal } from '@angular/cdk/portal';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    inject,
    input,
    OnDestroy,
    OnInit,
    signal,
    TemplateRef,
    viewChild,
    ViewContainerRef,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatTooltipModule } from '@angular/material/tooltip';
import {
    AppSvgIconComponent,
    AppTableCellDirective,
    AppTableColumnDef,
    AppTableComponent,
    LoadingSpinnerComponent,
    SearchComponent,
    SelectComponent,
    SelectItem,
    TableRow,
} from '@shared/components';
import { OverflowBadgeDirective, OverflowItemDirective, OverflowItemsDirective } from '@shared/directives';
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

interface RoleChip {
    roleId: number;
    roleName: string;
    orgCount: number;
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
        OverflowItemsDirective,
        OverflowItemDirective,
        OverflowBadgeDirective,
        MatTooltipModule,
        AppSvgIconComponent,
        OverlayModule,
    ],
})
export class StepAssignToOrgComponent implements OnInit, OnDestroy {
    organizations = input.required<Organization[]>();
    existingMemberships = input<FullMembership[]>([]);
    isEditMode = input.required<boolean>();
    disabled = input<boolean>(false);

    private readonly overflowDir = viewChild(OverflowItemsDirective);
    private readonly overflowDropdown = viewChild.required<TemplateRef<unknown>>('overflowDropdown');

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

    /** Chips grouped by role: one chip per distinct role across all selected orgs. */
    readonly roleChips = computed<RoleChip[]>(() => {
        const countByRole = new Map<number, RoleChip>();

        for (const row of this.selectedOrganizations()) {
            const roleId = row['role'] as number | null;
            if (roleId == null) continue;

            const existing = countByRole.get(roleId);
            if (existing) {
                existing.orgCount++;
            } else {
                countByRole.set(roleId, { roleId, roleName: this.roleNameById(roleId), orgCount: 1 });
            }
        }

        return [...countByRole.values()];
    });

    /** The subset of roleChips hidden by the overflow container — shown in the overflow dropdown. */
    readonly hiddenChips = computed<RoleChip[]>(() => {
        const count = this.overflowDir()?.overflowCount() ?? 0;
        const chips = this.roleChips();
        return chips.slice(chips.length - count);
    });

    /**
     * Search as the table's display-only `rowVisible` filter: hidden rows keep their selection.
     * A new function per search term is what tells the table to re-filter; `null` shows all rows.
     */
    matchesSearch = computed<((row: TableRow) => boolean) | null>(() => {
        const term = this.searchTerm().toLowerCase().trim();
        if (!term) return null;
        return (row) => (row['name'] as string)?.toLowerCase().includes(term);
    });

    /** Tooltip text per chip: comma-joined org names currently assigned to that role. */
    readonly chipTooltips = computed<Map<number, string>>(() => {
        const tooltips = new Map<number, string>();
        for (const row of this.selectedOrganizations()) {
            const roleId = row['role'] as number | null;
            if (roleId == null) continue;
            const existing = tooltips.get(roleId);
            const orgName = row['name'] as string;
            tooltips.set(roleId, existing ? `${existing}, ${orgName}` : orgName);
        }
        return tooltips;
    });

    readonly columns: AppTableColumnDef[] = [
        { key: 'organization', label: 'Organization', width: '1fr' },
        { key: 'role', label: 'Role', width: '1fr' },
    ];

    private rolesService = inject(RolesService);
    private permissionsService = inject(PermissionsService);
    private destroyRef = inject(DestroyRef);
    private overlay = inject(Overlay);
    private overlayPositionBuilder = inject(OverlayPositionBuilder);
    private vcr = inject(ViewContainerRef);
    private overflowOverlayRef: OverlayRef | null = null;
    private recentlyRemovedOrgIds = new Set<number>();
    /** Role names seeded from existingMemberships so chips display correctly before roles API responds. */
    private roleNames = new Map<number, string>();

    ngOnInit(): void {
        const memberships = this.existingMemberships();
        memberships.forEach((m) => this.roleNames.set(m.role.id, m.role.name));
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
        const removedIds = this.recentlyRemovedOrgIds;
        this.recentlyRemovedOrgIds = new Set();
        const effectiveItems = items.filter((r) => !removedIds.has(r['id'] as number));
        const previouslySelectedIds = new Set([...this.selectedOrgIds(), ...removedIds]);
        const bulkRoleId = this.bulkRoleId();
        let selection = effectiveItems;

        if (bulkRoleId !== null) {
            // Only role-less rows that just joined the selection follow the bulk role,
            // so manual overrides and existing memberships keep the role they already have.
            const idsToAssign = new Set(
                newRoleLessRows(effectiveItems, previouslySelectedIds)
                    .filter((r) => this.isRoleValidForOrg(r['id'] as number, bulkRoleId))
                    .map((r) => r['id'] as number)
            );
            if (idsToAssign.size) {
                this.setRoleInTableData(idsToAssign, bulkRoleId);
                selection = withRole(effectiveItems, idsToAssign, bulkRoleId);
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
                .filter((r) => r['role'] == null)
                .map((r) => r['id'] as number)
                .filter((orgId) => this.isRoleValidForOrg(orgId, value))
        );
        if (!idsToAssign.size) return;
        this.setRoleInTableData(idsToAssign, value);
        this.selectedOrganizations.update((rows) => withRole(rows, idsToAssign, value));
    }

    ngOnDestroy(): void {
        this.closeOverflowMenu();
    }

    protected removeChip(roleId: number): void {
        const orgIdsToRemove = new Set(
            this.selectedOrganizations()
                .filter((r) => r['role'] === roleId)
                .map((r) => r['id'] as number)
        );
        this.recentlyRemovedOrgIds = orgIdsToRemove;
        this.selectedOrganizations.update((rows) => rows.filter((r) => !orgIdsToRemove.has(r['id'] as number)));
    }

    protected openOverflowMenu(origin: HTMLElement): void {
        if (this.overflowOverlayRef) {
            this.closeOverflowMenu();
            return;
        }
        const positionStrategy = this.overlayPositionBuilder
            .flexibleConnectedTo(origin)
            .withPositions([
                { originX: 'start', originY: 'bottom', overlayX: 'start', overlayY: 'top', offsetY: 4 },
                { originX: 'start', originY: 'top', overlayX: 'start', overlayY: 'bottom', offsetY: -4 },
            ])
            .withPush(false);

        this.overflowOverlayRef = this.overlay.create({
            positionStrategy,
            scrollStrategy: this.overlay.scrollStrategies.reposition(),
            hasBackdrop: true,
            backdropClass: 'transparent-backdrop',
            minWidth: 200,
        });

        this.overflowOverlayRef
            .backdropClick()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.closeOverflowMenu());

        this.overflowOverlayRef.attach(new TemplatePortal(this.overflowDropdown(), this.vcr));
    }

    protected closeOverflowMenu(): void {
        this.overflowOverlayRef?.detach();
        this.overflowOverlayRef?.dispose();
        this.overflowOverlayRef = null;
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

    private roleNameById(roleId: number): string {
        const bulkItem = this.bulkRoleItems().find((item) => item.value === roleId);
        if (bulkItem) return bulkItem.name;

        for (const items of this.roleItemsByOrg().values()) {
            const found = items.find((item) => item.value === roleId);
            if (found) return found.name;
        }
        return this.roleNames.get(roleId) ?? String(roleId);
    }
}
