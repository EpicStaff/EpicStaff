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
import { CreateOrganizationRequest, GetOrganizationResponse, GetRoleResponse, UserRole } from '@shared/models';
import { catchError, EMPTY, finalize, forkJoin, Observable, of, switchMap } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ProfileService } from '../../../../services/auth/profile.service';
import { ToastService } from '../../../../services/notifications';
import { AdminUserService } from '../../services/admin/admin-user.service';
import { OrganizationsStorageService } from '../../services/admin/organizations-storage.service';
import { RolesService } from '../../services/admin/roles.service';
import { UserService } from '../../services/users/user.service';
import { NormalizedUser } from '../../strategies/users/user-fetch.strategy';
import { createUserFetchStrategy } from '../../strategies/users/user-fetch-strategy.factory';
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
    private userService = inject(UserService);
    private adminUserService = inject(AdminUserService);
    private currentUserService = inject(ProfileService);
    private permissionsService = inject(PermissionsService);
    private rolesService = inject(RolesService);
    private dialogData = inject<GetOrganizationResponse>(DIALOG_DATA, { optional: true });

    readonly isEditMode = !!this.dialogData;
    private readonly organizationId = this.dialogData?.id ?? null;

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
    initialSelectedUserIds = signal<number[]>([]);
    selectionIds = signal<number[]>([]);

    /** Roles available for assignment in this org: built-ins in create-mode;
     *  built-ins + this org's custom roles in edit-mode. */
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
        this.loadUsers();
        this.loadRoleItems();
    }

    private loadRoleItems(): void {
        // Edit-mode: filter by the target org so we get its custom roles alongside built-ins.
        // Create-mode: the org doesn't exist yet, so use only the (org-agnostic) built-ins from an unfiltered call.
        const params = this.isEditMode && this.organizationId ? { orgIds: [this.organizationId] } : {};
        this.rolesService
            .loadRoles(params)
            .pipe(
                catchError(() => EMPTY),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((res) => {
                const items: SelectItem[] = [
                    ...res.built_in_roles.map(roleToSelectItem),
                    ...(this.isEditMode ? res.results.map(roleToSelectItem) : []),
                ];
                this.roleItems.set(items);
            });
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

        const request: CreateOrganizationRequest = {
            name: this.orgNameControl.value!,
        };

        const orgAction$ = this.isEditMode
            ? this.organizationStorage.updateOrganization(this.organizationId!, request)
            : this.organizationStorage.createOrganization(request);

        orgAction$
            .pipe(
                switchMap((org) => {
                    const assignments = this.getSelectedAssignments();
                    const removedUserIds = this.getRemovedUserIds();

                    const ops: Observable<unknown>[] = [];

                    if (assignments.length) {
                        ops.push(
                            this.userService.assignUsersToOrg(org.id, { assignments }).pipe(
                                catchError((err: HttpErrorResponse) => {
                                    this.toast.error(err.error?.message ?? 'Failed to assign users');
                                    return of(null);
                                })
                            )
                        );
                    }

                    for (const userId of removedUserIds) {
                        ops.push(
                            this.userService.removeUserFromOrg(org.id, userId).pipe(
                                catchError((err: HttpErrorResponse) => {
                                    this.toast.error(err.error?.message ?? 'Failed to remove user');
                                    return of(null);
                                })
                            )
                        );
                    }

                    if (!ops.length) return of(org);
                    return forkJoin(ops);
                }),
                // Update current user memberships
                switchMap(() => this.currentUserService.getCurrentUser()),
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
                error: (err: HttpErrorResponse) => {
                    this.toast.error(err.error?.message ?? 'Operation failed');
                },
            });
    }

    private loadUsers(): void {
        const strategy = createUserFetchStrategy(
            this.currentUserService,
            this.adminUserService,
            this.userService,
            this.permissionsService
        );

        strategy
            .fetchUsers()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (users) => {
                    const currentUserId = this.currentUserService.currentUserSignal()?.id;
                    const filtered = users.filter((u) => u.id !== currentUserId);
                    this.usersTableData.set(filtered.map((u) => this.mapToRow(u)));

                    if (this.isEditMode) {
                        const preselected = filtered
                            .filter((u) => u.memberships.some((m) => m.organization.id === this.organizationId))
                            .map((u) => u.id);
                        this.initialSelectedUserIds.set(preselected);
                        this.selectionIds.set(preselected);
                    }

                    this.isUsersLoading.set(false);
                },
                error: () => this.isUsersLoading.set(false),
            });
    }

    private mapToRow(user: NormalizedUser): TableRow {
        const membership = this.isEditMode
            ? user.memberships.find((m) => m.organization.id === this.organizationId)
            : undefined;

        return {
            id: user.id,
            name: user.displayName,
            avatar: user.avatarUrl,
            email: user.email,
            role: membership?.role.id ?? UserRole.MEMBER,
        };
    }

    private getRemovedUserIds(): number[] {
        if (!this.isEditMode) return [];
        const currentIds = new Set(this.selectedUsers().map((r) => r['id'] as number));
        return this.initialSelectedUserIds().filter((id) => !currentIds.has(id));
    }

    private getSelectedAssignments(): { user_id: number; role_id: number }[] {
        return this.selectedUsers()
            .filter((row) => row['role'] != null)
            .map((row) => ({
                user_id: row['id'] as number,
                role_id: row['role'] as number,
            }));
    }
}

function roleToSelectItem(role: GetRoleResponse): SelectItem<number> {
    return { name: role.name, value: role.id };
}
