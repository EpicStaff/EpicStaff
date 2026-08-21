import { Dialog } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatTooltipModule } from '@angular/material/tooltip';
import {
    AppTableCellDirective,
    AppTableColumnDef,
    AppTableComponent,
    AppTableRowAction,
    ButtonComponent,
    ConfirmationDialogService,
    LoadingSpinnerComponent,
    SearchComponent,
    SelectItem,
    TableRow,
} from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, FullMembership, ResourceCode } from '@shared/models';
import { getRelativeTime } from '@shared/utils';
import { concat, Observable, of } from 'rxjs';
import { catchError, filter, finalize, map, switchMap, toArray } from 'rxjs/operators';

import { PermissionsService } from '../../../../../services/auth/permissions.service';
import { ProfileService } from '../../../../../services/auth/profile.service';
import { ToastService } from '../../../../../services/notifications';
import {
    OverflowBadgeDirective,
    OverflowItemDirective,
    OverflowItemsDirective,
} from '../../../../../shared/directives/overflow-items.directive';
import {
    CreateUserDialogComponent,
    UserDialogData,
} from '../../../components/create-user-dialog/create-user-dialog.component';
import { OrgAvatarComponent } from '../../../components/org-avatar/org-avatar.component';
import { StatusBadgeComponent } from '../../../components/status-badge/status-badge.component';
import { UserAvatarComponent } from '../../../components/user-avatar/user-avatar.component';
import { AggregatedUser } from '../../../models/aggregated-user.model';
import { AdminUserService } from '../../../services/admin/admin-user.service';
import { MembershipsService } from '../../../services/admin/memberships.service';
import { adminUsersToAggregated, aggregateMembershipsByUser } from '../../../utils/aggregate-users.util';
import { rbacErrorMessage } from '../../../utils/rbac-error-messages.util';

const STATUS_ITEMS: SelectItem[] = [
    { name: 'Online', value: 'online' },
    { name: 'Invited', value: 'invited' },
    { name: 'Offline', value: 'offline' },
];

@Component({
    selector: 'app-users-tab',
    templateUrl: './users-tab.component.html',
    styleUrls: ['./users-tab.component.scss'],
    imports: [
        AppTableComponent,
        AppTableCellDirective,
        ButtonComponent,
        SearchComponent,
        LoadingSpinnerComponent,
        StatusBadgeComponent,
        UserAvatarComponent,
        OrgAvatarComponent,
        OverflowItemsDirective,
        OverflowItemDirective,
        OverflowBadgeDirective,
        MatTooltipModule,
        HasPermissionDirective,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class UsersTabComponent implements OnInit {
    private dialog = inject(Dialog);
    private destroyRef = inject(DestroyRef);
    private adminUserService = inject(AdminUserService);
    private membershipsService = inject(MembershipsService);
    private profileService = inject(ProfileService);
    private permissionsService = inject(PermissionsService);
    private toast = inject(ToastService);
    private confirmation = inject(ConfirmationDialogService);

    private aggregatedUsers = signal<AggregatedUser[]>([]);

    usersData = signal<TableRow[]>([]);
    searchTerm = signal('');
    isLoading = signal(true);

    private orgFilterItems = signal<SelectItem[]>([]);
    private roleFilterItems = signal<SelectItem[]>([]);

    filteredUsers = computed(() => {
        const term = this.searchTerm().toLowerCase().trim();
        if (!term) return this.usersData();
        return this.usersData().filter((row) => {
            const name = (row['name'] as string)?.toLowerCase();
            const email = (row['email'] as string)?.toLowerCase();

            return name?.includes(term) || email?.includes(term);
        });
    });

    /** Actions are permission-aware:
     *  - Superadmin: Deactivate (`POST /admin/users/{id}/deactivate/`) on active rows; Reactivate on inactive rows.
     *  - Delegated admin: Remove membership(s) from every row-org where the caller holds `users:delete`.
     *    Hidden when the caller has no such membership overlap. */
    private readonly rowActions = computed<AppTableRowAction[]>(() => {
        const isSA = this.permissionsService.isSuperadmin;
        const editAction: AppTableRowAction = {
            icon: 'edit',
            tooltip: 'Edit user',
            onClick: (row) => this.onEditUser(row['id'] as number),
        };
        if (isSA) {
            const deactivateAction: AppTableRowAction = {
                icon: 'trash',
                tooltip: 'Deactivate account',
                variant: 'danger',
                hidden: (row) => row['isActive'] !== true,
                onClick: (row) => this.onDeactivate(row),
            };
            const reactivateAction: AppTableRowAction = {
                icon: 'refresh',
                tooltip: 'Reactivate account',
                hidden: (row) => row['isActive'] !== false,
                onClick: (row) => this.onReactivate(row),
            };
            return [editAction, deactivateAction, reactivateAction];
        }
        const removeAction: AppTableRowAction = {
            icon: 'trash',
            tooltip: 'Remove from your organizations',
            variant: 'danger',
            hidden: (row) => this.removableMembershipsFor(row['id'] as number).length === 0,
            onClick: (row) => this.onRemoveFromMyOrgs(row),
        };
        return [editAction, removeAction];
    });

    columns = computed<AppTableColumnDef[]>(() => [
        { key: 'user', label: 'USER', width: 'minmax(200px, 2fr)' },
        {
            key: 'roles',
            label: 'ROLE',
            width: 'minmax(150px, 1.5fr)',
            filterItems: this.roleFilterItems(),
        },
        {
            key: 'organization',
            label: 'ORGANIZATION',
            width: 'minmax(140px, 1.5fr)',
            filterItems: this.orgFilterItems(),
        },
        { key: 'lastActive', label: 'LAST ACTIVE', width: 'minmax(140px, 1.5fr)' },
        { key: 'status', label: 'STATUS', width: 'minmax(120px, 1.5fr)', filterItems: STATUS_ITEMS },
        { key: 'actions', label: 'ACTIONS', width: '130px', align: 'center', actions: this.rowActions() },
    ]);

    ngOnInit(): void {
        this.loadUsers();
    }

    formatDate(date: unknown): string {
        if (!(date instanceof Date)) return '';
        return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    }

    statusLabel(status: string): string {
        const labels: Record<string, string> = { online: 'Online', invited: 'Invited', offline: 'Offline' };
        return labels[status] ?? status;
    }

    onCreateUser(): void {
        this.openUserDialog();
    }

    /** Superadmin: confirm + deactivate account (global). */
    private onDeactivate(row: TableRow): void {
        const userId = row['id'] as number;
        const label = (row['name'] as string) || (row['email'] as string) || 'this account';
        this.confirmation
            .confirm({
                title: 'Deactivate account?',
                message: `<strong>${label}</strong> will no longer be able to sign in. You can reactivate them later.`,
                confirmText: 'Deactivate',
                cancelText: 'Cancel',
                type: 'danger',
            })
            .pipe(
                filter((result) => result === true),
                switchMap(() =>
                    this.adminUserService.deactivateUser(userId).pipe(
                        catchError((err: HttpErrorResponse) => {
                            this.toast.error(rbacErrorMessage(err, 'Failed to deactivate account.'));
                            return of(null);
                        })
                    )
                ),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((result) => {
                if (result === null) return;
                this.toast.success('Account deactivated.');
                this.loadUsers();
            });
    }

    /** Superadmin: confirm + reactivate previously-deactivated account. */
    private onReactivate(row: TableRow): void {
        const userId = row['id'] as number;
        const label = (row['name'] as string) || (row['email'] as string) || 'this account';
        this.confirmation
            .confirm({
                title: 'Reactivate account?',
                message: `<strong>${label}</strong> will regain the ability to sign in.`,
                confirmText: 'Reactivate',
                cancelText: 'Cancel',
            })
            .pipe(
                filter((result) => result === true),
                switchMap(() =>
                    this.adminUserService.reactivateUser(userId).pipe(
                        catchError((err: HttpErrorResponse) => {
                            this.toast.error(rbacErrorMessage(err, 'Failed to reactivate account.'));
                            return of(null);
                        })
                    )
                ),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((result) => {
                if (result === null) return;
                this.toast.success('Account reactivated.');
                this.loadUsers();
            });
    }

    /** Delegated admin: confirm + DELETE every membership in orgs where I hold `users:delete`. */
    private onRemoveFromMyOrgs(row: TableRow): void {
        const userId = row['id'] as number;
        const memberships = this.removableMembershipsFor(userId);
        if (memberships.length === 0) return;

        const label = (row['name'] as string) || (row['email'] as string) || 'this user';
        const orgNames = memberships.map((m) => m.organization.name).join(', ');
        this.confirmation
            .confirm({
                title: 'Remove from your organizations?',
                message: `<strong>${label}</strong> will lose access to: ${orgNames}.`,
                confirmText: 'Remove',
                cancelText: 'Cancel',
                type: 'danger',
            })
            .pipe(
                filter((result) => result === true),
                switchMap(() => {
                    const ops = memberships.map((m) =>
                        this.membershipsService.remove(m.id).pipe(
                            map(() => ({ ok: true as const, org: m.organization.name })),
                            catchError((err: HttpErrorResponse) =>
                                of({ ok: false as const, org: m.organization.name, err })
                            )
                        )
                    );
                    return concat(...ops).pipe(toArray());
                }),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((results) => {
                const failures = results.filter((r) => !r.ok);
                if (failures.length === 0) {
                    this.toast.success('User removed from your organizations.');
                } else if (failures.length === results.length) {
                    this.toast.error(rbacErrorMessage(failures[0].err, 'Failed to remove user.'));
                } else {
                    const failedOrgs = failures.map((f) => f.org).join(', ');
                    this.toast.error(`Removed from some orgs; failed on: ${failedOrgs}.`);
                }
                this.loadUsers();
            });
    }

    /** Memberships the caller can remove: rows where `users:delete` is granted in that org.
     *  Returns [] for the caller's own row (backend rejects with `cannot_modify_self_membership`). */
    private removableMembershipsFor(userId: number): FullMembership[] {
        const user = this.aggregatedUsers().find((u) => u.id === userId);
        if (!user) return [];
        const selfId = this.profileService.currentUserSignal()?.id;
        if (user.id === selfId) return [];
        return user.memberships.filter((m) =>
            this.permissionsService.canIn(m.organization.id, ResourceCode.Users, ActionCode.Delete)
        );
    }

    onEditUser(userId: number): void {
        const user = this.aggregatedUsers().find((u) => u.id === userId);
        if (user) {
            this.openUserDialog(user);
        }
    }

    private openUserDialog(user?: AggregatedUser): void {
        const data: UserDialogData = { user };
        const ref = this.dialog.open(CreateUserDialogComponent, {
            width: 'calc(100vw - 2rem)',
            height: 'calc(100vh - 2rem)',
            disableClose: true,
            data,
        });

        ref.closed.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((result) => {
            if (result) {
                this.loadUsers();
            }
        });
    }

    /** Superadmin → `/api/admin/users/` (full account list w/ memberships).
     *  Delegated admin → `/api/admin/memberships/` aggregated client-side.
     *  Same shape either way so the table stays permission-agnostic. */
    private loadUsers(): void {
        this.isLoading.set(true);
        const source$ = this.permissionsService.isSuperadmin ? this.loadFromAdminUsers() : this.loadFromMemberships();

        source$
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.isLoading.set(false))
            )
            .subscribe({
                next: (users) => {
                    const currentUserId = this.profileService.currentUserSignal()?.id;
                    const filtered = users.filter((u) => u.id !== currentUserId);
                    this.aggregatedUsers.set(filtered);
                    this.usersData.set(filtered.map((u) => this.mapToRow(u)));
                    this.orgFilterItems.set(this.extractOrgFilterItems(filtered));
                    this.roleFilterItems.set(this.extractRoleFilterItems(filtered));
                },
            });
    }

    private loadFromAdminUsers(): Observable<AggregatedUser[]> {
        return this.adminUserService.getUsers().pipe(map((page) => adminUsersToAggregated(page.results)));
    }

    private loadFromMemberships(): Observable<AggregatedUser[]> {
        return this.membershipsService.list().pipe(map((page) => aggregateMembershipsByUser(page.results)));
    }

    private extractOrgFilterItems(users: AggregatedUser[]): SelectItem[] {
        const orgMap = new Map<number, string>();
        for (const user of users) {
            for (const m of user.memberships) {
                orgMap.set(m.organization.id, m.organization.name);
            }
        }
        return Array.from(orgMap, ([value, name]) => ({ name, value }));
    }

    private extractRoleFilterItems(users: AggregatedUser[]): SelectItem[] {
        const roleNames = new Set<string>();
        for (const user of users) {
            for (const m of user.memberships) {
                roleNames.add(m.role.name);
            }
        }
        return Array.from(roleNames, (name) => ({ name, value: name }));
    }

    private mapToRow(user: AggregatedUser): TableRow {
        const orgs = user.memberships.map((m) => m.organization);
        const roles = [...new Set(user.memberships.map((m) => m.role.name))];

        return {
            id: user.id,
            name: user.displayName,
            email: user.email,
            avatar: user.avatarUrl,
            isSuperadmin: user.isSuperadmin,
            isActive: user.isActive,
            roles,
            organization: orgs?.map((o) => o.id),
            organizationDetails: orgs,
            lastActive: null,
            status: user.isActive ? 'online' : 'offline',
        };
    }

    protected readonly getRelativeTime = getRelativeTime;
    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;
}
