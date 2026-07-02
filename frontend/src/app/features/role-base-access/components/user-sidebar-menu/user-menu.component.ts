import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, input, model, signal } from '@angular/core';
import { Router } from '@angular/router';
import { AppSvgIconComponent } from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, FullMembership, GetMeResponse, ResourceCode } from '@shared/models';
import { EMPTY } from 'rxjs';
import { catchError, finalize } from 'rxjs/operators';

import { ActiveOrgService } from '../../../../services/auth/active-org.service';
import { AuthService } from '../../../../services/auth/auth.service';
import { ProfileService } from '../../../../services/auth/profile.service';
import { ToastService } from '../../../../services/notifications';
import { OrgAvatarComponent } from '../org-avatar/org-avatar.component';
import { UserAvatarComponent } from '../user-avatar/user-avatar.component';

@Component({
    selector: 'app-user-menu',
    imports: [CommonModule, AppSvgIconComponent, UserAvatarComponent, OrgAvatarComponent, HasPermissionDirective],
    templateUrl: './user-menu.component.html',
    styleUrls: ['./user-menu.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class UserMenuComponent {
    private authService = inject(AuthService);
    private router = inject(Router);
    private toast = inject(ToastService);
    protected currentUserService = inject(ProfileService);
    protected activeOrgService = inject(ActiveOrgService);

    user = input.required<GetMeResponse>();
    systemRole = this.currentUserService.systemRole;
    organizations = computed<FullMembership[]>(() => this.user().memberships);

    isUserMenuOpen = model<boolean>(false);
    switching = signal(false);

    onOrgClick(orgId: number): void {
        if (orgId === this.activeOrgService.activeOrgId() || this.switching()) return;
        this.switching.set(true);
        this.currentUserService
            .switchOrg(orgId)
            .pipe(
                finalize(() => this.switching.set(false)),
                catchError((err) => {
                    this.toast.error(err.error.message);
                    return EMPTY;
                })
            )
            .subscribe(() => {
                this.isUserMenuOpen.set(false);
                const currentUrl = this.router.url;
                // Navigate to an intermediate route without touching the browser URL,
                // then back to the original URL. This destroys and re-creates the
                // current page component, triggering ngOnInit with the new org context.
                // Using '/profile' as the intermediate because '/' has a redirect guard
                // that bounces back to the current page, preventing component teardown.
                void this.router.navigateByUrl('/profile', { skipLocationChange: true }).then(() => {
                    void this.router.navigateByUrl(currentUrl);
                });
            });
    }

    onWorkspaceClick(): void {
        this.isUserMenuOpen.set(false);
        this.router.navigate(['/workspace']);
    }

    onProfileClick(): void {
        this.isUserMenuOpen.set(false);
        this.router.navigate(['/profile']);
    }

    onSignOutClick(): void {
        this.isUserMenuOpen.set(false);
        this.authService
            .logout()
            .pipe(
                catchError(() => {
                    this.authService.removeTokensAndNavToLogin();
                    return EMPTY;
                })
            )
            .subscribe();
    }

    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;
}
