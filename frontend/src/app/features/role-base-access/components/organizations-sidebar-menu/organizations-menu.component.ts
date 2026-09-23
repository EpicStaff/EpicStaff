import { ChangeDetectionStrategy, Component, computed, inject, input, model, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router } from '@angular/router';
import { AppSvgIconComponent } from '@shared/components';
import { FullMembership, GetMeResponse } from '@shared/models';
import { EMPTY } from 'rxjs';
import { catchError, filter, finalize, map, switchMap } from 'rxjs/operators';

import { UnsavedChangesRegistry } from '../../../../core/services/unsaved-changes-registry.service';
import { ActiveOrgService } from '../../../../services/auth/active-org.service';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ProfileService } from '../../../../services/auth/profile.service';
import { ToastService } from '../../../../services/notifications';
import { OrgAvatarComponent } from '../org-avatar/org-avatar.component';

@Component({
    selector: 'app-organizations-menu',
    imports: [AppSvgIconComponent, OrgAvatarComponent],
    templateUrl: './organizations-menu.component.html',
    styleUrls: ['./organizations-menu.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class OrganizationsMenuComponent {
    private router = inject(Router);
    private toast = inject(ToastService);
    private unsavedChangesRegistry = inject(UnsavedChangesRegistry);
    private currentUserService = inject(ProfileService);
    private permissionService = inject(PermissionsService);
    protected activeOrgService = inject(ActiveOrgService);

    user = input.required<GetMeResponse>();
    isMenuOpen = model<boolean>(false);

    switching = signal(false);

    organizations = computed<FullMembership[]>(() => this.user().memberships);

    canVisitWorkspace = computed(() => this.permissionService.canAccessWorkspace());

    isWorkspaceRoute = toSignal(
        this.router.events.pipe(
            filter((e): e is NavigationEnd => e instanceof NavigationEnd),
            map(() => this.router.url.startsWith('/workspace'))
        ),
        { initialValue: this.router.url.startsWith('/workspace') }
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
                    // 403 error message is handled in interceptor
                    if (err.status !== 403) {
                        this.toast.error(err.error.message);
                    }
                    return EMPTY;
                })
            )
            .subscribe(() => {
                this.isMenuOpen.set(false);
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
        this.isMenuOpen.set(false);
        void this.router.navigate(['/workspace']);
    }
}
