import { Dialog } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatTooltipModule } from '@angular/material/tooltip';
import {
    ActivateButtonComponent,
    AppTableCellDirective,
    AppTableColumnDef,
    AppTableComponent,
    ButtonComponent,
    ConfirmationDialogService,
    DeleteButtonComponent,
    EditButtonComponent,
    LoadingSpinnerComponent,
    SearchComponent,
    SelectItem,
    StopButtonComponent,
    TableRow,
} from '@shared/components';
import {
    HasPermissionInAnyOrgDirective,
    OverflowBadgeDirective,
    OverflowItemDirective,
    OverflowItemsDirective,
} from '@shared/directives';
import { ActionCode, FullMembership, ResourceCode } from '@shared/models';
import { getRelativeTime } from '@shared/utils';
import { concat, Observable, of } from 'rxjs';
import { catchError, filter, finalize, map, switchMap, toArray } from 'rxjs/operators';

import { ActiveOrgService } from '../../../../../services/auth/active-org.service';
import { PermissionsService } from '../../../../../services/auth/permissions.service';
import { ProfileService } from '../../../../../services/auth/profile.service';
import { ToastService } from '../../../../../services/notifications';
import {
    CreateMembershipDialogComponent,
    MembershipDialogData,
} from '../../../components/create-membership-dialog/create-membership-dialog.component';
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
import { OrganizationsStorageService } from '../../../services/admin/organizations-storage.service';
import { HardDeleteFlowService } from '../../../services/hard-delete-flow.service';
import {
    adminUsersToAggregated,
    aggregateMembershipsByUser,
    buildUserDeleteMessage,
    rbacErrorMessage,
} from '../../../utils';

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
        StopButtonComponent,
        EditButtonComponent,
        ActivateButtonComponent,
        DeleteButtonComponent,
        OverflowItemsDirective,
        OverflowItemDirective,
        OverflowBadgeDirective,
        MatTooltipModule,
        HasPermissionInAnyOrgDirective,
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
    private activeOrgService = inject(ActiveOrgService);
    private orgStorage = inject(OrganizationsStorageService);
    private toast = inject(ToastService);
    private confirmation = inject(ConfirmationDialogService);
    private hardDeleteFlow = inject(HardDeleteFlowService);

    private aggregatedUsers = signal<AggregatedUser[]>([]);

    usersData = signal<TableRow[]>([]);
    searchTerm = signal('');
    isLoading = signal(true);
    readonly orgFilterIds = signal<number[]>([]);

    /** All orgs whose memberships the current user can list. Populated once on init. */
    readonly readableOrgs = signal<{ id: number; name: string }[]>([]);

    private roleFilterItems = signal<SelectItem[]>([]);

    readonly orgFilterItems = computed<SelectItem[]>(() =>
        this.readableOrgs().map((o) => ({ name: o.name, value: o.id }))
    );

    /** Preselected org filter — follows the currently active org, but only if the caller can
     *  actually read memberships there. Otherwise stays empty so the initial load falls back
     *  to fetching across all readable orgs (see `ngOnInit`). */
    private readonly activeOrgDefault = computed<number[] | undefined>(() => {
        const id = this.activeOrgService.activeOrgId();
        if (id === null) return undefined;
        if (this.permissionsService.isSuperadmin) return [id];
        return this.readableOrgs().some((o) => o.id === id) ? [id] : undefined;
    });

    filteredUsers = computed(() => {
        const term = this.searchTerm().toLowerCase().trim();
        if (!term) return this.usersData();
        return this.usersData().filter((row) => {
            const name = (row['name'] as string)?.toLowerCase();
            const email = (row['email'] as string)?.toLowerCase();

            return name?.includes(term) || email?.includes(term);
        });
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
            width: 'minmax(175px, 1.5fr)',
            filterItems: this.orgFilterItems(),
            filterKind: 'multi',
            filterServerSide: true,
            defaultValues: this.activeOrgDefault(),
        },
        { key: 'lastActive', label: 'LAST ACTIVE', width: 'minmax(140px, 1.5fr)' },
        { key: 'status', label: 'STATUS', width: 'minmax(120px, 1.5fr)', filterItems: STATUS_ITEMS },
        { key: 'actions', label: 'ACTIONS', width: '130px', align: 'end' },
    ]);

    /** Permission-aware; rendered together in the ACTIONS cell (see `actions` ng-template). */
    isEditHidden(row: TableRow): boolean {
        const currentUserId = this.profileService.currentUserSignal()?.id;
        if (currentUserId === row['id']) return true;
        if (this.permissionsService.isSuperadmin) return false;
        return this.membershipsIManage(row['id'] as number, ActionCode.Update).length === 0;
    }

    /** Superadmin-only; hidden for own row (self-deactivation is blocked server-side). */
    showDeactivate(row: TableRow): boolean {
        return (
            this.permissionsService.isSuperadmin &&
            row['isActive'] === true &&
            this.profileService.currentUserSignal()?.id !== row['id']
        );
    }

    /** Superadmin-only; shown for deactivated rows. */
    showReactivate(row: TableRow): boolean {
        return this.permissionsService.isSuperadmin && row['isActive'] === false;
    }

    /** Delegated admin only; requires `users:delete` on at least one of the row's orgs. */
    showRemove(row: TableRow): boolean {
        return (
            !this.permissionsService.isSuperadmin &&
            this.membershipsIManage(row['id'] as number, ActionCode.Delete).length > 0
        );
    }

    showHardDelete(row: TableRow): boolean {
        return this.permissionsService.isSuperadmin && this.profileService.currentUserSignal()?.id !== row['id'];
    }

    ngOnInit(): void {
        this.loadReadableOrgs();
        if (!this.activeOrgDefault()) this.loadUsers();
    }

    private loadReadableOrgs(): void {
        if (this.permissionsService.isSuperadmin) {
            this.orgStorage
                .getOrganizations()
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe((orgs) =>
                    this.readableOrgs.set(orgs.filter((o) => o.is_active).map((o) => ({ id: o.id, name: o.name })))
                );
            return;
        }
        this.readableOrgs.set(this.permissionsService.orgsWith(ResourceCode.Memberships, ActionCode.Read));
    }

    onFilterChange(evt: { key: string; values: unknown[] }): void {
        if (evt.key !== 'organization') return;
        this.orgFilterIds.set(evt.values.map((v) => Number(v)).filter((n) => Number.isFinite(n)));
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
    onDeactivate(row: TableRow): void {
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
    onReactivate(row: TableRow): void {
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

    onHardDeleteUser(row: TableRow): void {
        const userId = row['id'] as number;
        const label = (row['name'] as string) || (row['email'] as string) || 'this account';
        this.hardDeleteFlow
            .run(
                (dryRun) => this.adminUserService.deleteUser(userId, dryRun),
                (report) => buildUserDeleteMessage(label, report),
                {
                    title: 'Permanently delete this account?',
                    caution: 'This action is irreversible.',
                    successMessage: 'Account deleted permanently.',
                    previewErrorFallback: 'Failed to preview account deletion.',
                    deleteErrorFallback: 'Failed to delete account.',
                }
            )
            .pipe(
                filter((deleted) => deleted === true),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe(() => this.loadUsers());
    }

    /** Delegated admin: confirm + DELETE every membership in orgs where I hold `users:delete`. */
    onRemoveFromMyOrgs(row: TableRow): void {
        const userId = row['id'] as number;
        const memberships = this.membershipsIManage(userId, ActionCode.Delete);
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

    /** Memberships of `userId` where the caller holds the given `Users:*` action.
     *  Returns [] for the caller's own row (backend rejects self-membership mutation). */
    private membershipsIManage(userId: number, action: ActionCode): FullMembership[] {
        const user = this.aggregatedUsers().find((u) => u.id === userId);
        if (!user || user.id === this.profileService.currentUserSignal()?.id) return [];
        return user.memberships.filter((m) =>
            this.permissionsService.canInOrg(m.organization.id, ResourceCode.Memberships, action)
        );
    }

    onEditUser(row: TableRow): void {
        const user = this.aggregatedUsers().find((u) => u.id === row['id']);
        if (user) {
            this.openUserDialog(user);
        }
    }

    private openUserDialog(user?: AggregatedUser): void {
        // SA → Create User (email/password/superadmin + memberships).
        // Delegated → Create Membership (link existing account to org).
        const ref = this.permissionsService.isSuperadmin
            ? this.dialog.open(CreateUserDialogComponent, {
                  width: 'calc(100vw - 2rem)',
                  height: 'calc(100vh - 2rem)',
                  disableClose: true,
                  data: { user } as UserDialogData,
              })
            : this.dialog.open(CreateMembershipDialogComponent, {
                  width: 'calc(100vw - 2rem)',
                  height: 'calc(100vh - 2rem)',
                  disableClose: true,
                  data: { user } as MembershipDialogData,
              });

        ref.closed.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((result) => {
            if (result) {
                this.loadUsers();
            }
        });
    }

    /** Superadmin → `/api/admin/users/` (full account list w/ memberships).
     *  Delegated admin → `/api/admin/memberships/` aggregated client-side.
     *  Same shape either way so the table stays permission-agnostic. Server-side org filter
     *  is applied via `orgFilterIds` — memberships returned for other orgs are stripped. */
    private loadUsers(): void {
        this.isLoading.set(true);
        const orgIds = this.orgFilterIds();
        const source$ = this.permissionsService.isSuperadmin
            ? this.loadFromAdminUsers(orgIds)
            : this.loadFromMemberships(orgIds);

        source$
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.isLoading.set(false))
            )
            .subscribe({
                next: (users) => {
                    this.aggregatedUsers.set(users);
                    this.usersData.set(users.map((u) => this.mapToRow(u)));
                    this.roleFilterItems.set(this.extractRoleFilterItems(users));
                },
            });
    }

    private loadFromAdminUsers(orgIds: number[]): Observable<AggregatedUser[]> {
        return this.adminUserService
            .getUsers(orgIds.length ? { orgIds } : {})
            .pipe(map((page) => adminUsersToAggregated(page.results)));
    }

    private loadFromMemberships(orgIds: number[]): Observable<AggregatedUser[]> {
        return this.membershipsService
            .list(orgIds.length ? { org_ids: orgIds } : {})
            .pipe(map((page) => aggregateMembershipsByUser(page.results)));
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
    protected readonly isSuperadmin = this.permissionsService.isSuperadmin;
}
