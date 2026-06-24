import { Dialog } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatTooltipModule } from '@angular/material/tooltip';
import {
    AppSvgIconComponent,
    AppTableCellDirective,
    AppTableColumnDef,
    AppTableComponent,
    ButtonComponent,
    LoadingSpinnerComponent,
    SearchComponent,
    SelectItem,
    TableRow,
} from '@shared/components';
import { getRelativeTime } from '@shared/utils';
import { finalize } from 'rxjs/operators';

import { ProfileService } from '../../../../../services/auth/profile.service';
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
import { AdminUserService } from '../../../services/admin/admin-user.service';
import { UserService } from '../../../services/users/user.service';
import { NormalizedUser } from '../../../strategies/users/user-fetch.strategy';
import { createUserFetchStrategy } from '../../../strategies/users/user-fetch-strategy.factory';

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
        AppSvgIconComponent,
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
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class UsersTabComponent implements OnInit {
    private dialog = inject(Dialog);
    private destroyRef = inject(DestroyRef);
    private userService = inject(UserService);
    private adminUserService = inject(AdminUserService);
    private currentUserService = inject(ProfileService);

    private normalizedUsers = signal<NormalizedUser[]>([]);

    usersData = signal<TableRow[]>([]);
    searchTerm = signal('');
    isLoading = signal(true);

    private orgFilterItems = signal<SelectItem[]>([]);

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
        { key: 'user', label: 'USER', width: '2fr' },
        { key: 'roles', label: 'ROLE', width: '1.5fr' },
        { key: 'organization', label: 'ORGANIZATION', width: '1.5fr', filterItems: this.orgFilterItems() },
        { key: 'lastActive', label: 'LAST ACTIVE', width: '1.5fr' },
        { key: 'status', label: 'STATUS', width: '1.5fr', filterItems: STATUS_ITEMS },
        { key: 'actions', label: 'ACTIONS', width: '130px', align: 'center' },
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

    onEditUser(userId: number): void {
        const user = this.normalizedUsers().find((u) => u.id === userId);
        if (user) {
            this.openUserDialog(user);
        }
    }

    private openUserDialog(user?: NormalizedUser): void {
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

    private loadUsers(): void {
        this.isLoading.set(true);
        const strategy = createUserFetchStrategy(this.currentUserService, this.adminUserService, this.userService);

        strategy
            .fetchUsers()
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.isLoading.set(false))
            )
            .subscribe({
                next: (users) => {
                    const currentUserId = this.currentUserService.currentUserSignal()?.id;
                    const filtered = users.filter((u) => u.id !== currentUserId);
                    this.normalizedUsers.set(filtered);
                    this.usersData.set(filtered.map((u) => this.mapToRow(u)));
                    this.orgFilterItems.set(this.extractOrgFilterItems(filtered));
                },
            });
    }

    private extractOrgFilterItems(users: NormalizedUser[]): SelectItem[] {
        const orgMap = new Map<number, string>();
        for (const user of users) {
            for (const m of user.memberships) {
                orgMap.set(m.organization.id, m.organization.name);
            }
        }
        return Array.from(orgMap, ([value, name]) => ({ name, value }));
    }

    private mapToRow(user: NormalizedUser): TableRow {
        const orgs = user.memberships.map((m) => m.organization);
        const roles = [...new Set(user.memberships.map((m) => m.role.name))];

        return {
            id: user.id,
            name: user.displayName,
            email: user.email,
            avatar: user.avatarUrl,
            isSuperadmin: user.isSuperadmin,
            roles,
            organization: orgs?.map((o) => o.id),
            organizationDetails: orgs,
            lastActive: null,
            status: user.isActive ? 'online' : 'offline',
        };
    }

    protected readonly getRelativeTime = getRelativeTime;
}
