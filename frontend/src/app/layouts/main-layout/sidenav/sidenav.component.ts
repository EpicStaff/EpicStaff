import { OverlayModule } from '@angular/cdk/overlay';
import { PortalModule } from '@angular/cdk/portal';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, input, output, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterLink } from '@angular/router';
import { AppSvgIconComponent, SidebarToggleButtonComponent, UserAvatarComponent } from '@shared/components';
import { ClickOutsideDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import { filter, map } from 'rxjs/operators';

import { visibleRecycleBinTabs } from '../../../features/recycle-bin/utils/visible-recycle-bin-tabs.util';
import { OrgAvatarComponent } from '../../../features/role-base-access/components/org-avatar/org-avatar.component';
import { OrganizationsMenuComponent } from '../../../features/role-base-access/components/organizations-sidebar-menu/organizations-menu.component';
import { UserMenuComponent } from '../../../features/role-base-access/components/user-sidebar-menu/user-menu.component';
import { ActiveOrgService } from '../../../services/auth/active-org.service';
import { PermissionsService } from '../../../services/auth/permissions.service';
import { ProfileService } from '../../../services/auth/profile.service';
import { ConfigService } from '../../../services/config';
import { EasterEggTriggerService } from '../../../services/easter-egg-trigger.service';
import { isMainSidenavExpanded } from '../main-sidenav-width';
import { TooltipComponent } from './tooltip/tooltip.component';

interface NavItem {
    id: string;
    routeLink?: string;
    /** URL path prefixes that highlight this item: its own section plus pages that belong to it
     *  but live outside its route tree (e.g. flow sessions under Flows). */
    activePaths?: string[];
    icon?: string;
    label: string;
    showTooltip: boolean;
    /** Function (not boolean) so signal reads inside happen at template-eval time.
     *  Ensures the sidebar refreshes when active-org permissions reload after an org switch. */
    isPermitted: () => boolean;
    action?: () => void;
    customClass?: string;
}

@Component({
    selector: 'app-left-sidebar',
    imports: [
        TooltipComponent,
        RouterLink,
        OverlayModule,
        PortalModule,
        UserMenuComponent,
        OrganizationsMenuComponent,
        AppSvgIconComponent,
        UserAvatarComponent,
        OrgAvatarComponent,
        ClickOutsideDirective,
        SidebarToggleButtonComponent,
    ],
    templateUrl: './sidenav.component.html',
    styleUrls: ['./sidenav.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LeftSidebarComponent {
    /** Current sidebar width in px, owned by the main layout; collapsed vs expanded is derived from it. */
    public readonly width = input.required<number>();
    /** The open/close control was used; the owner of the width decides the new one. */
    public readonly expandedToggle = output<void>();

    /** Expanded rows show their labels, so the hover tooltips (which repeat the label) are suppressed. */
    protected readonly isExpanded = computed(() => isMainSidenavExpanded(this.width()));
    protected readonly sidebarToggleLabel = computed(() => (this.isExpanded() ? 'Close sidebar' : 'Open sidebar'));

    private currentUserService = inject(ProfileService);
    private destroyRef = inject(DestroyRef);
    private readonly easterEggTrigger = inject(EasterEggTriggerService);

    public topNavItems: NavItem[];
    public bottomNavItems: NavItem[];
    public recycleBinNavItem: NavItem;
    /** Shown next to the logo when expanded; names the logo image when collapsed. */
    protected readonly productName = 'EpicStaff';
    public showProfileTooltip = false;

    public user = this.currentUserService.currentUserSignal;
    public isUserMenuOpen = signal<boolean>(false);
    public isOrgMenuOpen = signal<boolean>(false);
    public showAccountTooltip = false;
    public showOrgTooltip = false;

    private router = inject(Router);
    private currentPath = toSignal(
        this.router.events.pipe(
            filter((e): e is NavigationEnd => e instanceof NavigationEnd),
            map(() => this.readCurrentPath())
        ),
        { initialValue: this.readCurrentPath() }
    );
    public isWorkspaceRoute = computed(() => this.currentPath().startsWith('/workspace'));

    public activeMembership = computed(() => {
        const user = this.user();
        if (!user) return null;
        const orgId = this.activeOrgService.activeOrgId();
        return user.memberships.find((m) => m.organization.id === orgId) ?? null;
    });

    /** Mirrors the org switcher icon: the workspace icon on workspace pages, the org avatar elsewhere. */
    protected readonly orgSwitcherLabel = computed(() =>
        this.isWorkspaceRoute() ? 'Workspace' : (this.activeMembership()?.organization.name ?? '')
    );

    /** Same fallback as the user menu header: the display name, or the email when there is none. */
    protected readonly accountLabel = computed(() => {
        const user = this.user();
        return user ? user.display_name || user.email : '';
    });

    private readonly activeOrgService = inject(ActiveOrgService);
    private readonly configService = inject(ConfigService);
    private readonly permissionService = inject(PermissionsService);

    constructor() {
        this.topNavItems = [
            {
                id: 'agents',
                routeLink: 'agents',
                activePaths: ['/agents'],
                icon: 'agents',
                label: 'Agents',
                isPermitted: () => this.permissionService.can(ResourceCode.Agents, ActionCode.Read),
                showTooltip: false,
            },
            {
                id: 'tools',
                routeLink: 'tools',
                activePaths: ['/tools'],
                icon: 'tools',
                label: 'Tools',
                isPermitted: () => this.permissionService.can(ResourceCode.Tools, ActionCode.Read),
                showTooltip: false,
            },
            {
                id: 'files',
                routeLink: 'storage',
                activePaths: ['/storage'],
                icon: 'sources',
                label: 'Storage',
                isPermitted: () => this.permissionService.resolveStorageTab() !== null,
                showTooltip: false,
            },
            {
                id: 'flows',
                routeLink: 'flows',
                activePaths: ['/flows', '/sessions', '/graph'],
                icon: 'flows',
                label: 'Flows',
                isPermitted: () => this.permissionService.can(ResourceCode.Flows, ActionCode.Read),
                showTooltip: false,
            },
            {
                id: 'chats',
                routeLink: 'chats',
                activePaths: ['/chats'],
                icon: 'chats',
                isPermitted: () => true,
                label: 'Chats',
                showTooltip: false,
            },
            {
                id: 'audit',
                routeLink: 'audit',
                activePaths: ['/audit'],
                icon: 'audit',
                label: 'Audit',
                isPermitted: () =>
                    this.configService.isAuditTrailEnabled &&
                    this.permissionService.can(ResourceCode.Audit, ActionCode.Read),
                showTooltip: false,
            },
        ];

        this.bottomNavItems = [];
        this.bottomNavItems.push({
            id: 'settings',
            routeLink: 'settings',
            icon: 'settings',
            label: 'Settings',
            isPermitted: () => this.permissionService.canOpenConfigureModelsDialog(),
            showTooltip: false,
            customClass: 'settings-tooltip',
        });

        // Hidden when no bin tab is readable, the same rule as Files. It has no active (purple) state
        // by design: it stays gray on /recycle-bin/*. No `icon`: that names a sprite icon, and the
        // template draws Tabler's outline trash instead (the sprite's trash is solid).
        this.recycleBinNavItem = {
            id: 'recycle-bin',
            routeLink: 'recycle-bin',
            label: 'Recycle Bin',
            isPermitted: () =>
                visibleRecycleBinTabs((resource, action) => this.permissionService.can(resource, action)).length > 0,
            showTooltip: false,
        };
    }

    public onLogoClick(): void {
        this.easterEggTrigger.registerLogoClick();
    }

    public closeUserMenu(): void {
        this.isUserMenuOpen.set(false);
    }

    public toggleUserMenu(event: MouseEvent): void {
        event.stopPropagation();
        this.isUserMenuOpen.update((prev) => !prev);
    }

    public closeOrgMenu(): void {
        this.isOrgMenuOpen.set(false);
    }

    public toggleOrgMenu(event: MouseEvent): void {
        event.stopPropagation();
        this.isOrgMenuOpen.update((prev) => !prev);
    }

    public handleItemClick(item: NavItem, event: MouseEvent): void {
        if (item.action) {
            event.preventDefault();
            item.action();
        }
    }

    public isItemActive(item: NavItem): boolean {
        const path = this.currentPath();
        return (item.activePaths ?? []).some((prefix) => path === prefix || path.startsWith(`${prefix}/`));
    }

    public resolveRouteLink(item: NavItem): string | null {
        return item.routeLink ?? null;
    }

    private readCurrentPath(): string {
        return this.router.url.split(/[?#;]/)[0];
    }
}
