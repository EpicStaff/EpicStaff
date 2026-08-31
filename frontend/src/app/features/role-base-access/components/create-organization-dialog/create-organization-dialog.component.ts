import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    AppTableCellDirective,
    AppTableColumnDef,
    AppTableComponent,
    ButtonComponent,
    CustomInputComponent,
    LoadingSpinnerComponent,
    SearchComponent,
    SelectComponent,
    SelectItem,
    TableRow,
    ValidationErrorsComponent,
} from '@shared/components';
import {
    ActionCode,
    CreateOrganizationRequest,
    FullMembership,
    GetOrganizationResponse,
    GetRoleResponse,
    ResourceCode,
    UserRole,
} from '@shared/models';
import { catchError, concat, EMPTY, finalize, map, Observable, of, switchMap, toArray } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ProfileService } from '../../../../services/auth/profile.service';
import { ToastService } from '../../../../services/notifications';
import { AggregatedUser } from '../../models/aggregated-user.model';
import { AdminUserService } from '../../services/admin/admin-user.service';
import { MembershipsService } from '../../services/admin/memberships.service';
import { OrganizationsStorageService } from '../../services/admin/organizations-storage.service';
import { RolesService } from '../../services/admin/roles.service';
import { adminUsersToAggregated, aggregateMembershipsByUser } from '../../utils/aggregate-users.util';
import { rbacErrorMessage } from '../../utils/rbac-error-messages.util';
import { UserAvatarComponent } from '../user-avatar/user-avatar.component';

@Component({
    selector: 'app-create-organization-dialog',
    templateUrl: './create-organization-dialog.component.html',
    styleUrls: ['./create-organization-dialog.component.scss'],
    imports: [
        ButtonComponent,
        ReactiveFormsModule,
        ValidationErrorsComponent,
        CustomInputComponent,
        AppTableComponent,
        AppTableCellDirective,
        SearchComponent,
        SelectComponent,
        LoadingSpinnerComponent,
        UserAvatarComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CreateOrganizationDialogComponent implements OnInit {
    private destroyRef = inject(DestroyRef);
    private toast = inject(ToastService);
    private dialogRef = inject(DialogRef);
    private organizationStorage = inject(OrganizationsStorageService);
    private adminUserService = inject(AdminUserService);
    private memberships = inject(MembershipsService);
    private profileService = inject(ProfileService);
    private permissionsService = inject(PermissionsService);
    private rolesService = inject(RolesService);
    private dialogData = inject<GetOrganizationResponse>(DIALOG_DATA, { optional: true });

    readonly isEditMode = !!this.dialogData;
    private readonly organizationId = this.dialogData?.id ?? null;

    /** Gate for the member-management table.
     *  - Create-mode: superadmin only (creation itself is superadmin-gated).
     *  - Edit-mode: any caller with `users:read` in this org.*/
    readonly canManageMembers = this.computeCanManageMembers();

    orgNameControl = new FormControl(this.dialogData?.name ?? '', [
        Validators.required,
        Validators.minLength(3),
        Validators.maxLength(50),
    ]);

    usersTableData = signal<TableRow[]>([]);
    searchTerm = signal('');
    isUsersLoading = signal(true);
    isSubmitting = signal(false);
    selectedUsers = signal<TableRow[]>([]);
    selectedUserIds = computed(() => new Set(this.selectedUsers().map((r) => r['id'] as number)));
    selectionIds = signal<number[]>([]);

    /** Snapshot of membership.id per userId already in this org (edit-mode only). Drives DELETE on unselect. */
    private existingMembershipIdByUserId = new Map<number, number>();

    readonly roleItems = signal<SelectItem[]>([]);

    readonly columns: AppTableColumnDef[] = [
        { key: 'user', label: 'User', width: '1fr' },
        { key: 'role', label: 'Role', width: '1fr' },
    ];

    filteredUsers = computed(() => {
        const term = this.searchTerm().toLowerCase().trim();
        if (!term) return this.usersTableData();
        return this.usersTableData().filter(
            (row) =>
                (row['name'] as string)?.toLowerCase().includes(term) ||
                (row['email'] as string)?.toLowerCase().includes(term)
        );
    });

    ngOnInit(): void {
        if (this.isEditMode) {
            const canRename = this.permissionsService.canInOrg(
                this.organizationId!,
                ResourceCode.Organizations,
                ActionCode.Update
            );
            if (!canRename) {
                this.toast.error('You do not have permission to rename this organization.');
                this.dialogRef.close();
                return;
            }
        } else if (!this.permissionsService.isSuperadmin) {
            this.toast.error('Only superadmins can create organizations.');
            this.dialogRef.close();
            return;
        }

        if (this.canManageMembers) {
            this.loadUsers();
            this.loadRoleItems();
        } else {
            this.isUsersLoading.set(false);
        }
    }

    onSelection(items: TableRow[]): void {
        this.selectedUsers.set(items);
    }

    onRoleSelected(row: TableRow, value: unknown): void {
        row['role'] = value;
        const rowId = row['id'] as number;
        const currentIds = this.selectedUsers().map((r) => r['id'] as number);
        if (!currentIds.includes(rowId)) {
            this.selectionIds.set([...currentIds, rowId]);
        }
    }

    onCancel(): void {
        this.dialogRef.close();
    }

    onSubmit(): void {
        if (this.orgNameControl.invalid) {
            this.orgNameControl.markAsTouched();
            return;
        }

        this.isSubmitting.set(true);

        const request: CreateOrganizationRequest = { name: this.orgNameControl.value! };
        const orgAction$: Observable<GetOrganizationResponse> = this.isEditMode
            ? this.organizationStorage.updateOrganization(this.organizationId!, request)
            : this.organizationStorage.createOrganization(request);

        orgAction$
            .pipe(
                switchMap((org) => this.syncMemberships(org).pipe(switchMap(() => of(org)))),
                // Refresh current user's memberships so the org switcher and permissions reflect the change.
                switchMap(() => this.profileService.getCurrentUser()),
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.isSubmitting.set(false))
            )
            .subscribe({
                next: () => {
                    this.toast.success(
                        this.isEditMode ? 'Organization updated successfully.' : 'Organization created successfully.'
                    );
                    this.dialogRef.close(true);
                },
                error: (err: HttpErrorResponse) => this.toast.error(rbacErrorMessage(err, 'Operation failed.')),
            });
    }

    /** Applies (add/remove) memberships against `org` sequentially. Per-op errors are surfaced as toasts but
     *  don't abort the batch — the org itself has already been persisted at this point. */
    private syncMemberships(org: GetOrganizationResponse): Observable<unknown> {
        if (!this.canManageMembers) return of(null);

        const assignments = this.getSelectedAssignments();
        const removedMembershipIds = this.getRemovedMembershipIds();

        const ops: Observable<unknown>[] = [];

        for (const a of assignments) {
            ops.push(
                this.memberships
                    .create({ org_id: org.id, user_id: a.user_id, role_id: a.role_id })
                    .pipe(catchError((err) => this.toastAndContinue(err, 'Failed to add member.')))
            );
        }

        for (const membershipId of removedMembershipIds) {
            ops.push(
                this.memberships
                    .remove(membershipId)
                    .pipe(catchError((err) => this.toastAndContinue(err, 'Failed to remove member.')))
            );
        }

        if (!ops.length) return of(null);
        return concat(...ops).pipe(toArray());
    }

    private toastAndContinue(err: HttpErrorResponse, fallback: string): Observable<null> {
        this.toast.error(rbacErrorMessage(err, fallback));
        return of(null);
    }

    private loadRoleItems(): void {
        // Edit-mode: filter by the target org so we get its custom roles alongside built-ins.
        // Create-mode: the org doesn't exist yet — built-ins only.
        const params = this.isEditMode && this.organizationId ? { orgIds: [this.organizationId] } : {};
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
                    ...(this.isEditMode ? res.results.map(roleToSelectItem) : []),
                ];
                this.roleItems.set(items);
            });
    }

    private computeCanManageMembers(): boolean {
        if (this.permissionsService.isSuperadmin) return true;
        if (!this.isEditMode || this.organizationId === null) return false;
        return this.permissionsService.canInOrg(this.organizationId, ResourceCode.Users, ActionCode.Read);
    }

    /** Superadmin → `/api/admin/users/` (full account list).
     *  Delegated admin → `/api/admin/memberships/` aggregated by user (users visible via any admin org). */
    private loadUsers(): void {
        const source$ = this.permissionsService.isSuperadmin ? this.loadFromAdminUsers() : this.loadFromMemberships();

        source$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
            next: (users) => {
                const currentUserId = this.profileService.currentUserSignal()?.id;
                const filtered = users.filter((u) => u.id !== currentUserId);
                this.usersTableData.set(filtered.map((u) => this.mapToRow(u)));

                if (this.isEditMode && this.organizationId !== null) {
                    this.existingMembershipIdByUserId.clear();
                    const preselected: number[] = [];
                    for (const u of filtered) {
                        const m = this.membershipInThisOrg(u);
                        if (m) {
                            this.existingMembershipIdByUserId.set(u.id, m.id);
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

    private loadFromAdminUsers(): Observable<AggregatedUser[]> {
        return this.adminUserService.getUsers().pipe(map((page) => adminUsersToAggregated(page.results)));
    }

    private loadFromMemberships(): Observable<AggregatedUser[]> {
        return this.memberships.list({ page_size: 1000 }).pipe(map((page) => aggregateMembershipsByUser(page.results)));
    }

    /** The user's membership in the org being edited, or undefined. Null org id → not in edit-mode. */
    private membershipInThisOrg(user: AggregatedUser): FullMembership | undefined {
        if (this.organizationId === null) return;
        return user.memberships.find((m) => m.organization.id === this.organizationId);
    }

    private mapToRow(user: AggregatedUser): TableRow {
        return {
            id: user.id,
            name: user.displayName,
            avatar: user.avatarUrl,
            email: user.email,
            role: this.membershipInThisOrg(user)?.role.id ?? UserRole.MEMBER,
        };
    }

    /** Membership IDs to DELETE — users who were preselected but are no longer in `selectedUsers`. */
    private getRemovedMembershipIds(): number[] {
        if (!this.isEditMode) return [];
        const currentIds = new Set(this.selectedUsers().map((r) => r['id'] as number));
        const removed: number[] = [];
        for (const [userId, membershipId] of this.existingMembershipIdByUserId) {
            if (!currentIds.has(userId)) removed.push(membershipId);
        }
        return removed;
    }

    private getSelectedAssignments(): { user_id: number; role_id: number }[] {
        return this.selectedUsers()
            .filter((row) => row['role'] != null && !this.existingMembershipIdByUserId.has(row['id'] as number))
            .map((row) => ({
                user_id: row['id'] as number,
                role_id: row['role'] as number,
            }));
    }
}

function roleToSelectItem(role: GetRoleResponse): SelectItem<number> {
    return { name: role.name, value: role.id };
}
