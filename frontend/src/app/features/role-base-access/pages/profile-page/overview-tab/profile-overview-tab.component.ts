import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { AppSvgIconComponent, ListComponent, ListRowComponent, SelectComponent, SelectItem } from '@shared/components';
import { Role, UserRole } from '@shared/models';

import { ProfileService } from '../../../../../services/auth/profile.service';
import { OrgAvatarComponent } from '../../../components/org-avatar/org-avatar.component';
import { ROLE_LABELS } from '../../../constants/role-labels.constant';

@Component({
    selector: 'app-profile-overview-tab',
    templateUrl: './profile-overview-tab.component.html',
    styleUrls: ['./profile-overview-tab.component.scss'],
    imports: [AppSvgIconComponent, OrgAvatarComponent, SelectComponent, ListComponent, ListRowComponent, DatePipe],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ProfileOverviewTabComponent {
    private currentUserService = inject(ProfileService);

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

    protected uniqueRoles = computed(() => {
        const user = this.user();
        if (!user) return [];
        const roleIds = new Set(user.memberships.map((m) => m.role.id));
        if (user.is_superadmin) roleIds.add(UserRole.SUPER_ADMIN);
        return [...roleIds].map((r) => ROLE_LABELS[r as UserRole] ?? String(r));
    });

    protected roleLabel(role: Role): string {
        return ROLE_LABELS[role.id as UserRole] ?? String(role.name);
    }
}
