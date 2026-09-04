import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, input, model, signal } from '@angular/core';
import { Router } from '@angular/router';
import { AppSvgIconComponent } from '@shared/components';
import { ActionCode, FullMembership, GetMeResponse, ResourceCode } from '@shared/models';
import { EMPTY } from 'rxjs';
import { catchError, finalize, switchMap } from 'rxjs/operators';

import { UnsavedChangesRegistry } from '../../../../core/services/unsaved-changes-registry.service';
import { ActiveOrgService } from '../../../../services/auth/active-org.service';
import { AuthService } from '../../../../services/auth/auth.service';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ProfileService } from '../../../../services/auth/profile.service';
import { ToastService } from '../../../../services/notifications';
import { OrgAvatarComponent } from '../org-avatar/org-avatar.component';
import { UserAvatarComponent } from '../user-avatar/user-avatar.component';

@Component({
    selector: 'app-user-menu',
    imports: [CommonModule, AppSvgIconComponent, UserAvatarComponent, OrgAvatarComponent],
    templateUrl: './user-menu.component.html',
    styleUrls: ['./user-menu.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class UserMenuComponent {
    private authService = inject(AuthService);
    private router = inject(Router);
    private toast = inject(ToastService);
    private unsavedChangesRegistry = inject(UnsavedChangesRegistry);
    protected currentUserService = inject(ProfileService);
    protected permissionService = inject(PermissionsService);
    protected activeOrgService = inject(ActiveOrgService);

    user = input.required<GetMeResponse>();

    switching = signal(false);
    systemRole = this.currentUserService.systemRole;

    isUserMenuOpen = model<boolean>(false);

    organizations = computed<FullMembership[]>(() => this.user().memberships);
    canVisitWorkspace = computed(
        () =>
            this.permissionService.can(ResourceCode.Organizations, ActionCode.Read) ||
            this.permissionService.can(ResourceCode.Users, ActionCode.Read) ||
            this.permissionService.can(ResourceCode.Roles, ActionCode.Read)
    );

    onOrgClick(orgId: number): void {
        if (orgId === this.activeOrgService.activeOrgId() || this.switching()) return;
        this.switching.set(true);

        // Ask the currently-active page about unsaved changes BEFORE switching org.
        // Otherwise, the org switch happens first and "Save & Leave" would run
        // against the new org context — leading to 404 on the previous resource.
        this.unsavedChangesRegistry
            .canLeave()
            .pipe(
                switchMap((allowed) => {
                    if (!allowed) return EMPTY;
                    return this.currentUserService.switchOrg(orgId);
                }),
                finalize(() => this.switching.set(false)),
                catchError((err) => {
                    this.toast.error(err.error.message);
                    return EMPTY;
                })
            )
            .subscribe(() => {
                this.isUserMenuOpen.set(false);
                const targetUrl = this.getUrlForOrgSwitch(this.router.url);
                void this.router.navigateByUrl('/profile', { skipLocationChange: true }).then(() => {
                    void this.router.navigateByUrl(targetUrl);
                });
            });
    }

    /**
     * Detail routes with resource IDs are not safe to keep across an org switch —
     * the resource not exist in the new org. Map them to their list page.
     */
    private getUrlForOrgSwitch(currentUrl: string): string {
        if (/^\/flows\/(?!my|templates)[^/?]+/.test(currentUrl)) return '/flows/my';
        if (/^\/graph\//.test(currentUrl)) return '/sessions';
        return currentUrl;
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
                    this.authService.removeTokenAndNavToLogin();
                    return EMPTY;
                })
            )
            .subscribe();
    }

    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;
}
