import { HttpErrorResponse } from '@angular/common/http';
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
import { ActionCode, FullMembership, GetRoleResponse, ResourceCode, UserRole } from '@shared/models';
import { catchError, concat, EMPTY, map, Observable, of, toArray } from 'rxjs';

import { PermissionsService } from '../../../../../services/auth/permissions.service';
import { ProfileService } from '../../../../../services/auth/profile.service';
import { ToastService } from '../../../../../services/notifications';
import { AggregatedUser } from '../../../models/aggregated-user.model';
import { AdminUserService } from '../../../services/admin/admin-user.service';
import { MembershipsService } from '../../../services/admin/memberships.service';
import { RolesService } from '../../../services/admin/roles.service';
import { adminUsersToAggregated, aggregateMembershipsByUser } from '../../../utils/aggregate-users.util';
import { rbacErrorMessage } from '../../../utils/rbac-error-messages.util';
import { UserAvatarComponent } from '../../user-avatar/user-avatar.component';

interface MembershipSnapshot {
    membershipId: number;
    roleId: number;
}

@Component({
    selector: 'app-org-members-editor',
    templateUrl: './org-members-editor.component.html',
    styleUrls: ['./org-members-editor.component.scss'],
    imports: [
        AppTableCellDirective,
        AppTableComponent,
        LoadingSpinnerComponent,
        SearchComponent,
        SelectComponent,
        UserAvatarComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class OrgMembersEditorComponent implements OnInit {
    organizationId = input.required<number | null>();
    isEditMode = input.required<boolean>();

    private destroyRef = inject(DestroyRef);
    private toast = inject(ToastService);
    private adminUserService = inject(AdminUserService);
    private memberships = inject(MembershipsService);
    private profileService = inject(ProfileService);
    private permissionsService = inject(PermissionsService);
    private rolesService = inject(RolesService);

    usersTableData = signal<TableRow[]>([]);
    searchTerm = signal('');
    isUsersLoading = signal(true);
    selectedUsers = signal<TableRow[]>([]);
    selectionIds = signal<number[]>([]);
    selectedUserIds = computed(() => new Set(this.selectedUsers().map((r) => r['id'] as number)));
    readonly roleItems = signal<SelectItem[]>([]);

    private originalMembershipByUserId = new Map<number, MembershipSnapshot>();

    readonly canManageMembers = computed(() => {
        if (this.permissionsService.isSuperadmin) return true;
        const orgId = this.organizationId();
        if (!this.isEditMode() || orgId === null) return false;
        return this.permissionsService.canInOrg(orgId, ResourceCode.Memberships, ActionCode.Read);
    });
    readonly hasInvalidRow = computed(() => this.selectedUsers().some((row) => row['role'] == null));

    filteredUsers = computed(() => {
        const term = this.searchTerm().toLowerCase().trim();
        if (!term) return this.usersTableData();
        return this.usersTableData().filter(
            (row) =>
                (row['name'] as string)?.toLowerCase().includes(term) ||
                (row['email'] as string)?.toLowerCase().includes(term)
        );
    });

    readonly columns: AppTableColumnDef[] = [
        { key: 'user', label: 'User', width: '1fr' },
        { key: 'role', label: 'Role', width: '1fr' },
    ];

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
        this.selectedUsers.set(items);
    }

    onRoleSelected(row: TableRow, value: unknown): void {
        const rowId = row['id'] as number;
        const patch = (r: TableRow): TableRow => (r['id'] === rowId ? { ...r, role: value } : r);
        this.usersTableData.update((rows) => rows.map(patch));

        if (this.selectedUserIds().has(rowId)) {
            this.selectedUsers.update((rows) => rows.map(patch));
        } else {
            this.selectionIds.set([...this.selectionIds(), rowId]);
        }
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

        const params = canReadRoles ? { orgIds: [orgId!] } : {};
        this.rolesService
            .loadRoles(params)
            .pipe(
                catchError(() => EMPTY),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((res) => {
                const assignableBuiltIns = res.built_in_roles.filter((r) => r.id !== UserRole.SUPER_ADMIN);
                const items: SelectItem[] = [
                    ...assignableBuiltIns.map(roleToSelectItem),
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
            next: (users) => {
                const currentUserId = this.profileService.currentUserSignal()?.id;
                const filtered = users.filter((u) => u.id !== currentUserId);
                this.usersTableData.set(filtered.map((u) => this.mapToRow(u)));

                if (this.isEditMode() && this.organizationId() !== null) {
                    this.originalMembershipByUserId.clear();
                    const preselected: number[] = [];
                    for (const u of filtered) {
                        const m = this.membershipInThisOrg(u);
                        if (m) {
                            this.originalMembershipByUserId.set(u.id, { membershipId: m.id, roleId: m.role.id });
                            preselected.push(u.id);
                        }
                    }
                    this.selectionIds.set(preselected);
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

    private mapToRow(user: AggregatedUser): TableRow {
        return {
            id: user.id,
            name: user.displayName,
            avatar: user.avatarUrl,
            email: user.email,
            role: this.membershipInThisOrg(user)?.role.id ?? null,
        };
    }

    private getRemovedMembershipIds(): number[] {
        if (!this.isEditMode()) return [];
        const currentIds = new Set(this.selectedUsers().map((r) => r['id'] as number));
        const removed: number[] = [];
        for (const [userId, { membershipId }] of this.originalMembershipByUserId) {
            if (!currentIds.has(userId)) removed.push(membershipId);
        }
        return removed;
    }

    private getSelectedAssignments(): { user_id: number; role_id: number }[] {
        return this.selectedUsers()
            .filter((row) => row['role'] != null && !this.originalMembershipByUserId.has(row['id'] as number))
            .map((row) => ({ user_id: row['id'] as number, role_id: row['role'] as number }));
    }

    private getRoleUpdates(): { membershipId: number; role_id: number }[] {
        if (!this.isEditMode()) return [];
        const updates: { membershipId: number; role_id: number }[] = [];
        for (const row of this.selectedUsers()) {
            const userId = row['id'] as number;
            const original = this.originalMembershipByUserId.get(userId);
            const roleId = row['role'] as number | null;
            if (original == null || roleId == null) continue;
            if (roleId !== original.roleId) {
                updates.push({ membershipId: original.membershipId, role_id: roleId });
            }
        }
        return updates;
    }
}

function roleToSelectItem(role: GetRoleResponse): SelectItem<number> {
    return { name: role.name, value: role.id };
}
