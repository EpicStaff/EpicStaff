import { Dialog } from '@angular/cdk/dialog';
import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
    AppSvgIconComponent,
    ButtonComponent,
    ListComponent,
    ListRowComponent,
    SelectComponent,
    SelectItem,
} from '@shared/components';
import { UserRole } from '@shared/models';
import { EMPTY } from 'rxjs';
import { catchError } from 'rxjs/operators';

import { AuthService } from '../../../../services/auth/auth.service';
import { ProfileService } from '../../../../services/auth/profile.service';
import { HideInlineSubtitleOnOverflowDirective } from '../../../../shared/directives/hide-inline-subtitle-on-overflow.directive';
import { OrgAvatarComponent } from '../../components/org-avatar/org-avatar.component';
import { PasswordChangeDialogComponent } from '../../components/password-change-dialog/password-change-dialog.component';
import { ProfileEditDialogComponent } from '../../components/profile-edit-dialog/profile-edit-dialog.component';
import { UserAvatarComponent } from '../../components/user-avatar/user-avatar.component';
import { ROLE_LABELS } from '../../constants/role-labels.constant';

@Component({
    selector: 'app-profile-page',
    templateUrl: './profile-page.component.html',
    styleUrls: ['./profile-page.component.scss'],
    imports: [
        AppSvgIconComponent,
        ButtonComponent,
        UserAvatarComponent,
        OrgAvatarComponent,
        SelectComponent,
        ListComponent,
        ListRowComponent,
        DatePipe,
        HideInlineSubtitleOnOverflowDirective,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ProfilePageComponent implements OnInit {
    private dialog = inject(Dialog);
    private currentUserService = inject(ProfileService);
    private authService = inject(AuthService);
    private destroyRef = inject(DestroyRef);

    user = this.currentUserService.currentUserSignal;
    systemRole = this.currentUserService.systemRole;
    isLoading = signal(!this.currentUserService.currentUserSignal());

    organizations = computed(() => this.user()?.memberships ?? []);

    readonly SORT_ITEMS: SelectItem[] = [
        { name: 'Name', value: 'name' },
        { name: 'Role', value: 'role' },
        { name: 'Joined Date', value: 'joined' },
    ];

    sortKey = signal<string | null>(null);

    sortedOrganizations = computed(() => {
        const orgs = this.organizations();
        const key = this.sortKey();
        if (!key) return orgs;
        return [...orgs].sort((a, b) => {
            if (key === 'name') return a.organization.name.localeCompare(b.organization.name);
            if (key === 'role') return a.role.name.localeCompare(b.role.name);
            if (key === 'joined') return new Date(a.joined_at).getTime() - new Date(b.joined_at).getTime();
            return 0;
        });
    });

    uniqueRoles = computed(() => {
        const user = this.user();
        if (!user) return [];
        const roleIds = new Set(user.memberships.map((m) => m.role.id));
        if (user.is_superadmin) roleIds.add(UserRole.SUPER_ADMIN);
        return [...roleIds].map((r) => ROLE_LABELS[r as UserRole] ?? String(r));
    });

    ngOnInit(): void {
        if (this.user()) {
            this.isLoading.set(false);
            return;
        }
        this.currentUserService
            .getCurrentUser()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => this.isLoading.set(false),
                error: () => this.isLoading.set(false),
            });
    }

    roleLabel(roleId: number): string {
        return ROLE_LABELS[roleId as UserRole] ?? String(roleId);
    }

    onPasswordChange(): void {
        this.dialog.open(PasswordChangeDialogComponent, {
            width: '560px',
        });
    }

    onSignOut(): void {
        this.authService
            .logout()
            .pipe(
                catchError(() => {
                    this.authService.removeTokenAndNavToLogin();
                    return EMPTY;
                })
            )
            .subscribe();
    }

    onProfileEdit(): void {
        const user = this.user();
        if (!user) return;
        this.dialog.open(ProfileEditDialogComponent, {
            width: '560px',
            data: { name: user.display_name, email: user.email, avatarUrl: user.avatar_url },
        });
    }
}
