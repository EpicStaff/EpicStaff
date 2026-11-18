import { Overlay, OverlayModule, OverlayPositionBuilder, OverlayRef } from '@angular/cdk/overlay';
import { TemplatePortal } from '@angular/cdk/portal';
import { HttpErrorResponse } from '@angular/common/http';
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
    UserAvatarComponent,
} from '@shared/components';
import { OverflowBadgeDirective, OverflowItemDirective, OverflowItemsDirective } from '@shared/directives';
import { ActionCode, FullMembership, ResourceCode, UserRole } from '@shared/models';
import { catchError, concat, EMPTY, map, Observable, of, toArray } from 'rxjs';

import { PermissionsService } from '../../../../../services/auth/permissions.service';
import { ProfileService } from '../../../../../services/auth/profile.service';
import { ToastService } from '../../../../../services/notifications';
import { AggregatedUser } from '../../../models/aggregated-user.model';
import { AdminUserService } from '../../../services/admin/admin-user.service';
import { MembershipsService } from '../../../services/admin/memberships.service';
import { RolesService } from '../../../services/admin/roles.service';
import {
    adminUsersToAggregated,
    aggregateMembershipsByUser,
    haveSameIds,
    newRoleLessRows,
    rbacErrorMessage,
    roleToSelectItem,
    withRole,
} from '../../../utils';

interface MembershipSnapshot {
    membershipId: number;
    roleId: number;
}

interface RoleChip {
    roleId: number;
    roleName: string;
    userCount: number;
}

@Component({
    selector: 'app-org-members-editor',
    templateUrl: './org-members-editor.component.html',
    styleUrls: ['./org-members-editor.component.scss'],
    imports: [
        AppSvgIconComponent,
        AppTableCellDirective,
        AppTableComponent,
        LoadingSpinnerComponent,
        MatTooltipModule,
        OverflowBadgeDirective,
        OverflowItemDirective,
        OverflowItemsDirective,
        OverlayModule,
        SearchComponent,
        SelectComponent,
        UserAvatarComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class OrgMembersEditorComponent implements OnInit, OnDestroy {
    organizationId = input.required<number | null>();
    isEditMode = input.required<boolean>();

    private readonly overflowDir = viewChild(OverflowItemsDirective);
    private readonly overflowDropdown = viewChild.required<TemplateRef<unknown>>('overflowDropdown');

    usersTableData = signal<TableRow[]>([]);
    searchTerm = signal('');
    isUsersLoading = signal(true);
    selectedUsers = signal<TableRow[]>([]);
    bulkRoleId = signal<number | null>(null);
    readonly roleItems = signal<SelectItem[]>([]);
    private readonly originalMembershipByUserId = signal<Map<number, MembershipSnapshot>>(new Map());

    /**
     * Fed to the table's `initialSelectedIds`, which re-applies the ids and emits `selectionChange`
     * on every new value. Changing only when the id set changes lets that round trip settle.
     */
    selectionIds = computed(() => [...this.selectedUserIds()], { equal: haveSameIds });
    selectedUserIds = computed(() => new Set(this.selectedUsers().map((r) => r['id'] as number)));

    readonly canManageMembers = computed(() => {
        if (this.permissionsService.isSuperadmin) return true;
        const orgId = this.organizationId();
        if (!this.isEditMode() || orgId === null) return false;
        return this.permissionsService.canInOrg(orgId, ResourceCode.Memberships, ActionCode.Read);
    });
    readonly hasInvalidRow = computed(() => this.selectedUsers().some((row) => row['role'] == null));

    /**
     * Search as the table's display-only `rowVisible` filter: hidden rows keep their selection.
     * A new function per search term is what tells the table to re-filter; `null` shows all rows.
     */
    matchesSearch = computed<((row: TableRow) => boolean) | null>(() => {
        const term = this.searchTerm().toLowerCase().trim();
        if (!term) return null;
        return (row) =>
            (row['name'] as string)?.toLowerCase().includes(term) ||
            (row['email'] as string)?.toLowerCase().includes(term);
    });

    /** Chips grouped by role: one chip per distinct role across all selected users. */
    readonly roleChips = computed<RoleChip[]>(() => {
        const countByRole = new Map<number, RoleChip>();
        for (const row of this.selectedUsers()) {
            const roleId = row['role'] as number | null;
            if (roleId == null) continue;
            const existing = countByRole.get(roleId);
            if (existing) {
                existing.userCount++;
            } else {
                const roleName = this.roleItems().find((item) => item.value === roleId)?.name ?? String(roleId);
                countByRole.set(roleId, { roleId, roleName, userCount: 1 });
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

    /** Tooltip text per chip: comma-joined user names currently assigned to that role. */
    readonly chipTooltips = computed<Map<number, string>>(() => {
        const tooltips = new Map<number, string>();
        for (const row of this.selectedUsers()) {
            const roleId = row['role'] as number | null;
            if (roleId == null) continue;
            const existing = tooltips.get(roleId);
            const userName = (row['name'] as string) || (row['email'] as string);
            tooltips.set(roleId, existing ? `${existing}, ${userName}` : userName);
        }
        return tooltips;
    });

    readonly columns: AppTableColumnDef[] = [
        { key: 'user', label: 'User', width: '1fr' },
        { key: 'role', label: 'Role', width: '1fr' },
    ];

    private destroyRef = inject(DestroyRef);
    private toast = inject(ToastService);
    private adminUserService = inject(AdminUserService);
    private memberships = inject(MembershipsService);
    private profileService = inject(ProfileService);
    private permissionsService = inject(PermissionsService);
    private rolesService = inject(RolesService);
    private overlay = inject(Overlay);
    private overlayPositionBuilder = inject(OverlayPositionBuilder);
    private vcr = inject(ViewContainerRef);
    private overflowOverlayRef: OverlayRef | null = null;
    private recentlyRemovedUserIds = new Set<number>();

    ngOnInit(): void {
        if (!this.canManageMembers()) {
            this.isUsersLoading.set(false);
            return;
        }
        this.loadUsers();
        this.loadRoleItems();
    }

    commit(orgId: number): Observable<number> {
        if (!this.canManageMembers()) return of(0);

        const ops: Observable<boolean>[] = [
            ...this.getSelectedAssignments().map((a) =>
                this.memberships.create({ org_id: orgId, user_id: a.user_id, role_id: a.role_id }).pipe(
                    map(() => true),
                    catchError((err) => this.toastAndContinue(err, 'Failed to add member.'))
                )
            ),
            ...this.getRoleUpdates().map((u) =>
                this.memberships.updateRole(u.membershipId, { role_id: u.role_id }).pipe(
                    map(() => true),
                    catchError((err) => this.toastAndContinue(err, 'Failed to update member role.'))
                )
            ),
            ...this.getRemovedMembershipIds().map((id) =>
                this.memberships.remove(id).pipe(
                    map(() => true),
                    catchError((err) => this.toastAndContinue(err, 'Failed to remove member.'))
                )
            ),
        ];

        if (!ops.length) return of(0);
        return concat(...ops).pipe(
            toArray(),
            map((results) => results.filter((ok) => !ok).length)
        );
    }

    onSelection(items: TableRow[]): void {
        const removedIds = this.recentlyRemovedUserIds;
        this.recentlyRemovedUserIds = new Set();
        const effectiveItems = items.filter((r) => !removedIds.has(r['id'] as number));
        const previouslySelectedIds = new Set([...this.selectedUserIds(), ...removedIds]);
        const bulkRoleId = this.bulkRoleId();
        let selection = effectiveItems;

        if (bulkRoleId !== null) {
            // Only role-less rows that just joined the selection follow the bulk role,
            // so manual overrides and existing members keep the role they already have.
            const idsToAssign = new Set(
                newRoleLessRows(effectiveItems, previouslySelectedIds)
                    .filter((r) => this.isRowEditable(r))
                    .map((r) => r['id'] as number)
            );
            if (idsToAssign.size) {
                this.setRoleInTableData(idsToAssign, bulkRoleId);
                selection = withRole(effectiveItems, idsToAssign, bulkRoleId);
            }
        }

        this.selectedUsers.set(selection);
    }

    onRoleSelected(row: TableRow, value: unknown): void {
        const rowId = row['id'] as number;
        const patch = (r: TableRow): TableRow => (r['id'] === rowId ? { ...r, role: value } : r);
        this.usersTableData.update((rows) => rows.map(patch));

        if (this.selectedUserIds().has(rowId)) {
            this.selectedUsers.update((rows) => rows.map(patch));
        } else {
            this.selectedUsers.update((rows) => [...rows, patch(row)]);
        }
    }

    onBulkRoleSelected(value: unknown): void {
        if (typeof value !== 'number') return;
        this.bulkRoleId.set(value);

        const idsToAssign = new Set(
            this.selectedUsers()
                .filter((r) => r['role'] == null && this.isRowEditable(r))
                .map((r) => r['id'] as number)
        );
        if (!idsToAssign.size) return;
        this.setRoleInTableData(idsToAssign, value);
        this.selectedUsers.update((rows) => withRole(rows, idsToAssign, value));
    }

    ngOnDestroy(): void {
        this.closeOverflowMenu();
    }

    removeChip(roleId: number): void {
        const userIdsToRemove = new Set(
            this.selectedUsers()
                .filter((r) => r['role'] === roleId)
                .map((r) => r['id'] as number)
        );
        this.recentlyRemovedUserIds = userIdsToRemove;
        this.selectedUsers.update((rows) => rows.filter((r) => !userIdsToRemove.has(r['id'] as number)));
    }

    openOverflowMenu(origin: HTMLElement): void {
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

    closeOverflowMenu(): void {
        this.overflowOverlayRef?.detach();
        this.overflowOverlayRef?.dispose();
        this.overflowOverlayRef = null;
    }

    /**
     * Updates the table data only. Callers patch the selection too: the table emits selected rows
     * as snapshots and does not re-emit when its data changes.
     */
    private setRoleInTableData(userIds: Set<number>, roleId: number): void {
        this.usersTableData.update((rows) => withRole(rows, userIds, roleId));
    }

    private toastAndContinue(err: HttpErrorResponse, fallback: string): Observable<boolean> {
        this.toast.error(rbacErrorMessage(err, fallback));
        return of(false);
    }

    private loadRoleItems(): void {
        const isSuperadmin = this.permissionsService.isSuperadmin;
        const orgId = this.organizationId();
        const canReadRoles =
            this.isEditMode() &&
            orgId !== null &&
            this.permissionsService.canInOrg(orgId, ResourceCode.Roles, ActionCode.Read);

        if (!isSuperadmin && !canReadRoles) return;

        const load$ = canReadRoles
            ? this.rolesService.loadAssignableRoles(orgId!)
            : this.rolesService.loadAssignableRoles();

        load$
            .pipe(
                catchError(() => EMPTY),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((res) => {
                const builtIns = res.built_in_roles.filter((r) => r.id !== UserRole.SUPER_ADMIN);
                const items: SelectItem[] = [
                    ...builtIns.map(roleToSelectItem),
                    ...(canReadRoles ? res.results.map(roleToSelectItem) : []),
                ];
                this.roleItems.set(items);
            });
    }

    private loadUsers(): void {
        const source$ = this.permissionsService.isSuperadmin
            ? this.adminUserService.getUsers().pipe(map((page) => adminUsersToAggregated(page.results)))
            : this.memberships.list({ page_size: 1000 }).pipe(map((page) => aggregateMembershipsByUser(page.results)));

        source$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
            next: (allUsers) => {
                const users = allUsers.filter((u) => !u.isSuperadmin);
                const currentUserId = this.profileService.currentUserSignal()?.id;
                this.usersTableData.set(users.map((u) => this.mapToRow(u, u.id === currentUserId)));

                if (this.isEditMode() && this.organizationId() !== null) {
                    const original = new Map<number, MembershipSnapshot>();
                    for (const u of users) {
                        const m = this.membershipInThisOrg(u);
                        if (m) {
                            original.set(u.id, { membershipId: m.id, roleId: m.role.id });
                        }
                    }
                    this.originalMembershipByUserId.set(original);
                    this.selectedUsers.set(this.usersTableData().filter((row) => original.has(row['id'] as number)));
                }

                this.isUsersLoading.set(false);
            },
            error: () => this.isUsersLoading.set(false),
        });
    }

    private membershipInThisOrg(user: AggregatedUser): FullMembership | undefined {
        const orgId = this.organizationId();
        if (orgId === null) return;
        return user.memberships.find((m) => m.organization.id === orgId);
    }

    private mapToRow(user: AggregatedUser, isSelf = false): TableRow {
        const membership = this.membershipInThisOrg(user);
        return {
            id: user.id,
            name: user.displayName,
            avatar: user.avatarUrl,
            email: user.email,
            role: membership?.role.id ?? null,
            roleName: membership?.role.name ?? null,
            isSelf,
        };
    }

    readonly isRowEditable = (row: TableRow) => !row['isSelf'];

    private getRemovedMembershipIds(): number[] {
        if (!this.isEditMode()) return [];
        const currentIds = new Set(this.selectedUsers().map((r) => r['id'] as number));
        const removed: number[] = [];
        for (const [userId, { membershipId }] of this.originalMembershipByUserId()) {
            if (!currentIds.has(userId)) removed.push(membershipId);
        }
        return removed;
    }

    private getSelectedAssignments(): { user_id: number; role_id: number }[] {
        const original = this.originalMembershipByUserId();
        return this.selectedUsers()
            .filter((row) => row['role'] != null && !original.has(row['id'] as number))
            .map((row) => ({ user_id: row['id'] as number, role_id: row['role'] as number }));
    }

    private getRoleUpdates(): { membershipId: number; role_id: number }[] {
        if (!this.isEditMode()) return [];
        const original = this.originalMembershipByUserId();
        const updates: { membershipId: number; role_id: number }[] = [];
        for (const row of this.selectedUsers()) {
            const userId = row['id'] as number;
            const snapshot = original.get(userId);
            const roleId = row['role'] as number | null;
            if (snapshot == null || roleId == null) continue;
            if (roleId !== snapshot.roleId) {
                updates.push({ membershipId: snapshot.membershipId, role_id: roleId });
            }
        }
        return updates;
    }
}
