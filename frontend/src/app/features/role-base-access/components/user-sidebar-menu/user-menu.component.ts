import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, inject, input, model, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router } from '@angular/router';
import { AppSvgIconComponent, UserAvatarComponent } from '@shared/components';
import { FullMembership, GetMeResponse } from '@shared/models';
import { ORG_SWITCH_URL_RULES } from '@shared/services';
import { EMPTY } from 'rxjs';
import { catchError, filter, finalize, map, switchMap } from 'rxjs/operators';

import { UnsavedChangesRegistry } from '../../../../core/services/unsaved-changes-registry.service';
import { ActiveOrgService } from '../../../../services/auth/active-org.service';
import { AuthService } from '../../../../services/auth/auth.service';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ProfileService } from '../../../../services/auth/profile.service';
import { ToastService } from '../../../../services/notifications';
import { QuickStartTourService } from '../../../quick-start-tour/quick-start-tour.service';
import { OrgAvatarComponent } from '../org-avatar/org-avatar.component';

const ORG_SWITCH_FAILED_MESSAGE = 'Could not switch organization. Please try again.';

/** The sidebar's account menu: the signed-in user, their organizations, navigation and sign out. */
@Component({
    selector: 'app-user-menu',
    imports: [AppSvgIconComponent, UserAvatarComponent, OrgAvatarComponent],
    templateUrl: './user-menu.component.html',
    styleUrls: ['./user-menu.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class UserMenuComponent {
    user = input.required<GetMeResponse>();

    isUserMenuOpen = model<boolean>(false);

    switching = signal(false);

    organizations = computed<FullMembership[]>(() => this.user().memberships);

    canVisitWorkspace = computed(() => this.permissionService.canAccessWorkspace());

    isWorkspaceRoute = computed(() => this.currentUrl().startsWith('/workspace'));

    isProfileRoute = computed(() => this.currentUrl().startsWith('/profile'));

    protected activeOrgService = inject(ActiveOrgService);

    private authService = inject(AuthService);
    private router = inject(Router);
    private toast = inject(ToastService);
    private unsavedChangesRegistry = inject(UnsavedChangesRegistry);
    private currentUserService = inject(ProfileService);
    private permissionService = inject(PermissionsService);
    private readonly quickStartTourService = inject(QuickStartTourService);
    /** Features' own rules for their addresses (a plugin page keeps the plugin, not its path). */
    private readonly orgSwitchUrlRules = inject(ORG_SWITCH_URL_RULES, { optional: true }) ?? [];

    protected readonly canStartQuickStartTour = this.quickStartTourService.isAvailable;

    // Declared after the router it reads: field initializers run in order.
    private currentUrl = toSignal(
        this.router.events.pipe(
            filter((event): event is NavigationEnd => event instanceof NavigationEnd),
            map(() => this.router.url)
        ),
        { initialValue: this.router.url }
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
                catchError((error: unknown) => {
                    // 403 error message is handled in interceptor
                    if (!(error instanceof HttpErrorResponse) || error.status !== 403) {
                        this.toast.error(this.errorMessage(error));
                    }
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

    onWorkspaceClick(): void {
        this.isUserMenuOpen.set(false);
        void this.router.navigate(['/workspace']);
    }

    onProfileClick(): void {
        this.isUserMenuOpen.set(false);
        void this.router.navigate(['/profile']);
    }

    onQuickStartTourClick(): void {
        this.isUserMenuOpen.set(false);
        void this.quickStartTourService.start();
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

    /**
     * Detail routes with resource IDs are not safe to keep across an org switch —
     * the resource not exist in the new org. Map them to their list page.
     * Other features map their own addresses through `ORG_SWITCH_URL_RULES` (a plugin page keeps the plugin but drops
     * its own path; the plugin page guard sends the user to the default route when the new org can't open it).
     */
    private getUrlForOrgSwitch(currentUrl: string): string {
        if (/^\/flows\/(?!my|templates)[^/?]+/.test(currentUrl)) return '/flows/my';
        if (/^\/graph\//.test(currentUrl)) return '/sessions';
        for (const rule of this.orgSwitchUrlRules) {
            const mapped = rule(currentUrl);
            if (mapped !== null) return mapped;
        }
        return currentUrl;
    }

    /** The server's message when the response carries one (a network error or a non-JSON 5xx does not). */
    private errorMessage(error: unknown): string {
        if (error instanceof HttpErrorResponse && typeof error.error?.message === 'string') {
            return error.error.message;
        }
        return ORG_SWITCH_FAILED_MESSAGE;
    }
}
