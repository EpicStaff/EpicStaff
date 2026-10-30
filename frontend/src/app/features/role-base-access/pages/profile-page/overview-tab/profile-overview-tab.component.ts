import { Dialog } from '@angular/cdk/dialog';
import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';
import { AppSvgIconComponent, ListComponent, ListRowComponent, SelectComponent, SelectItem } from '@shared/components';
import { ROLE_LABELS } from '@shared/constants';
import { FullMembership, Role, UserRole } from '@shared/models';

import { ProfileService } from '../../../../../services/auth/profile.service';
import { OrgAvatarComponent } from '../../../components/org-avatar/org-avatar.component';
import {
    ROLE_PERMISSIONS_DIALOG_TITLE_ID,
    RolePermissionsDialogComponent,
    RolePermissionsDialogData,
} from '../../../components/role-permissions-dialog/role-permissions-dialog.component';

@Component({
    selector: 'app-profile-overview-tab',
    templateUrl: './profile-overview-tab.component.html',
    styleUrls: ['./profile-overview-tab.component.scss'],
    imports: [
        AppSvgIconComponent,
        OrgAvatarComponent,
        SelectComponent,
        ListComponent,
        ListRowComponent,
        DatePipe,
        MatTooltip,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ProfileOverviewTabComponent {
    private currentUserService = inject(ProfileService);
    private dialog = inject(Dialog);

    protected user = this.currentUserService.currentUserSignal;

    protected memberships = computed(() => this.user()?.memberships ?? []);

    protected readonly SORT_ITEMS: SelectItem[] = [
        { name: 'Name', value: 'name' },
        { name: 'Role', value: 'role' },
    ];

    protected sortKey = signal<string | null>(null);

    protected sortedOrganizations = computed(() => {
        const orgs = this.memberships();
        const key = this.sortKey();
        if (!key) return orgs;
        return [...orgs].sort((a, b) => {
            if (key === 'name') return a.organization.name.localeCompare(b.organization.name);
            if (key === 'role') return a.role.name.localeCompare(b.role.name);
            return 0;
        });
    });

    /** One label per distinct role across the user's memberships, or a single Super Admin label. */
    protected uniqueRoles = computed<{ id: number; label: string }[]>(() => {
        const user = this.user();
        if (!user) return [];
        // A superadmin's memberships all carry the built-in Superadmin role; one chip covers them.
        if (user.is_superadmin) return [{ id: UserRole.SUPER_ADMIN, label: ROLE_LABELS[UserRole.SUPER_ADMIN] }];
        const labelsById = new Map<number, string>();
        for (const membership of user.memberships) {
            if (!labelsById.has(membership.role.id))
                labelsById.set(membership.role.id, this.roleLabel(membership.role));
        }
        return [...labelsById].map(([id, label]) => ({ id, label }));
    });

    protected openRolePermissions(membership: FullMembership): void {
        this.dialog.open<void, RolePermissionsDialogData>(RolePermissionsDialogComponent, {
            width: '560px',
            ariaLabelledBy: ROLE_PERMISSIONS_DIALOG_TITLE_ID,
            data: {
                organization: membership.organization,
                roleId: membership.role.id,
                roleName: this.roleLabel(membership.role),
                isSuperadmin: this.user()?.is_superadmin ?? false,
            },
        });
    }

    protected rolePermissionsLabel(membership: FullMembership): string {
        return `View permissions for ${this.roleLabel(membership.role)} in ${membership.organization.name}`;
    }

    protected roleLabel(role: Role): string {
        return ROLE_LABELS[role.id as UserRole] ?? String(role.name);
    }
}
