import { Dialog } from '@angular/cdk/dialog';
import { OverlayModule } from '@angular/cdk/overlay';
import { PortalModule } from '@angular/cdk/portal';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    effect,
    inject,
    input,
    output,
    signal,
    untracked,
} from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, NavigationEnd, Router, RouterLink } from '@angular/router';
import { AppSvgIconComponent, SidebarToggleButtonComponent, UserAvatarComponent } from '@shared/components';
import { ClickOutsideDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import { filter, map } from 'rxjs/operators';

import { ChatInboxStreamService } from '../../../features/chat/services/chat-inbox-stream.service';
import { QUICK_START_TOUR_ANCHORS } from '../../../features/quick-start-tour/quick-start-tour-anchors';
import { visibleRecycleBinTabs } from '../../../features/recycle-bin/utils/visible-recycle-bin-tabs.util';
import { OrgAvatarComponent } from '../../../features/role-base-access/components/org-avatar/org-avatar.component';
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
    /** Live counter rendered as a pill on the icon; read at template-eval time like `isPermitted`. */
    badge?: () => number;
    /** Where the badge itself leads, as its own link next to the item's; without it the badge is only a label. */
    badgeLink?: string;
    /** The badge link's accessible name for a count. */
    badgeLabel?: (count: number) => string;
    action?: () => void;
    customClass?: string;
    /** Draws a divider above the item, separating it from the group before it. */
    separatedAbove?: boolean;
}

const PAGE_STEP_BY_CODE: Partial<Record<'ArrowUp' | 'ArrowDown', 1 | -1>> = { ArrowUp: -1, ArrowDown: 1 };

function isPlainAltChord(event: KeyboardEvent): boolean {
    return event.altKey && !event.ctrlKey && !event.shiftKey && !event.metaKey && !event.repeat;
}

function isEditableTarget(element: Element): boolean {
    return !!element.closest(
        'input, textarea, select, [contenteditable]:not([contenteditable="false"]), .monaco-editor, .native-edit-context'
    );
}

@Component({
    selector: 'app-left-sidebar',
    imports: [
        TooltipComponent,
        RouterLink,
        OverlayModule,
        PortalModule,
        UserMenuComponent,
        AppSvgIconComponent,
        UserAvatarComponent,
        OrgAvatarComponent,
        ClickOutsideDirective,
        SidebarToggleButtonComponent,
    ],
    templateUrl: './sidenav.component.html',
    styleUrls: ['./sidenav.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    host: { '(document:keydown)': 'onDocumentKeydown($event)' },
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
    public showAccountTooltip = false;
    protected readonly tourAnchors = QUICK_START_TOUR_ANCHORS;

    private router = inject(Router);
    private currentPath = toSignal(
        this.router.events.pipe(
            filter((e): e is NavigationEnd => e instanceof NavigationEnd),
            map(() => this.readCurrentPath())
        ),
        { initialValue: this.readCurrentPath() }
    );

    /**
     * The inbox stream follows the signed-in user, the active org and the `chats:read` permission; it stops with the
     * layout (logout).
     */
    private readonly chatStreamEffect = effect(() => {
        const orgId = this.activeOrgService.activeOrgId();
        const userId = this.user()?.id;
        const permitted =
            this.configService.isChatEnabled && this.permissionService.can(ResourceCode.Chats, ActionCode.Read);
        untracked(() =>
            permitted && orgId && userId ? this.chatInboxStream.start(orgId, userId) : this.chatInboxStream.stop()
        );
    });

    /** Workspace and My Profile are reached from the account menu, so their pages highlight its row. */
    protected readonly isAccountRoute = computed(() =>
        ['/workspace', '/profile'].some(
            (prefix) => this.currentPath() === prefix || this.currentPath().startsWith(`${prefix}/`)
        )
    );

    /** The account row shows the organization the user is working in. */
    protected readonly activeMembership = computed(() => {
        const user = this.user();
        if (!user) return null;
        const orgId = this.activeOrgService.activeOrgId();
        return user.memberships.find((membership) => membership.organization.id === orgId) ?? null;
    });

    /** Same fallback as the user menu header: the display name, or the email when there is none. */
    protected readonly accountLabel = computed(() => {
        const user = this.user();
        return user ? user.display_name || user.email : '';
    });

    private readonly activeOrgService = inject(ActiveOrgService);
    private readonly configService = inject(ConfigService);
    private readonly permissionService = inject(PermissionsService);
    private readonly chatInboxStream = inject(ChatInboxStreamService);
    private readonly dialog = inject(Dialog);
    private readonly activatedRoute = inject(ActivatedRoute);
    private readonly workspaceNavItem: NavItem = {
        id: 'workspace',
        routeLink: 'workspace',
        label: 'Workspace',
        isPermitted: () => this.activeMembership() !== null && this.permissionService.canAccessWorkspace(),
        showTooltip: false,
    };
    private readonly profileNavItem: NavItem = {
        id: 'profile',
        routeLink: 'profile',
        label: 'Profile',
        isPermitted: () => this.user() !== null,
        showTooltip: false,
    };

    constructor() {
        this.destroyRef.onDestroy(() => this.chatInboxStream.stop());
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
                id: 'venvs',
                routeLink: 'venvs',
                activePaths: ['/venvs'],
                icon: 'venvs',
                label: 'Virtual Environments',
                isPermitted: () => this.permissionService.can(ResourceCode.Venvs, ActionCode.Read),
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
                id: 'chat',
                routeLink: 'chat-bindings',
                activePaths: ['/chat-bindings'],
                icon: 'messages',
                label: 'Conversations',
                isPermitted: () =>
                    this.configService.isChatEnabled && this.permissionService.can(ResourceCode.Chats, ActionCode.Read),
                badge: () => this.chatInboxStream.waitingCount(),
                badgeLink: '/chat-bindings/all',
                badgeLabel: (count) => `Conversations inbox: ${count} waiting for a person`,
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
                separatedAbove: true,
            },
        ];

        this.bottomNavItems = [];
        this.bottomNavItems.push({
            id: 'settings',
            routeLink: 'settings',
            activePaths: ['/settings'],
            icon: 'settings',
            label: 'Settings',
            isPermitted: () => this.permissionService.canOpenConfigureModelsDialog(),
            showTooltip: false,
            customClass: 'settings-tooltip',
        });

        // Hidden when no bin tab is readable, the same rule as Files. No `icon`: that names a sprite icon,
        // and the template draws Tabler's outline trash instead (the sprite's trash is solid).
        this.recycleBinNavItem = {
            id: 'recycle-bin',
            routeLink: 'recycle-bin',
            activePaths: ['/recycle-bin'],
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

    public handleItemClick(item: NavItem, event: MouseEvent): void {
        if (item.action) {
            event.preventDefault();
            item.action();
        }
    }

    protected onDocumentKeydown(event: KeyboardEvent): void {
        if (event.defaultPrevented) return;
        const step = PAGE_STEP_BY_CODE[event.code as keyof typeof PAGE_STEP_BY_CODE];
        if (step === undefined || !isPlainAltChord(event) || this.dialog.openDialogs.length > 0) return;
        if (event.target instanceof Element && isEditableTarget(event.target)) return;

        const nextItem = this.findSteppedItem(step);
        if (!nextItem?.routeLink) return;

        event.preventDefault();
        this.closeUserMenu();
        void this.router.navigate([nextItem.routeLink], { relativeTo: this.activatedRoute });
    }

    public isItemActive(item: NavItem): boolean {
        return this.matchesCurrentPath(item.activePaths ?? []);
    }

    public badgeCount(item: NavItem): number {
        return item.badge?.() ?? 0;
    }

    public resolveRouteLink(item: NavItem): string | null {
        return item.routeLink ?? null;
    }

    private findSteppedItem(step: number): NavItem | null {
        const visibleItems = [
            this.workspaceNavItem,
            ...this.topNavItems,
            this.recycleBinNavItem,
            ...this.bottomNavItems,
            this.profileNavItem,
        ].filter((item) => item.isPermitted());
        const currentIndex = visibleItems.findIndex((item) => this.isCurrentPage(item));
        if (currentIndex === -1) {
            return (step > 0 ? visibleItems[0] : visibleItems[visibleItems.length - 1]) ?? null;
        }
        return visibleItems[currentIndex + step] ?? null;
    }

    private isCurrentPage(item: NavItem): boolean {
        const ownPaths = item.routeLink ? [`/${item.routeLink}`] : [];
        return this.matchesCurrentPath(item.activePaths ?? ownPaths);
    }

    private matchesCurrentPath(prefixes: string[]): boolean {
        const path = this.currentPath();
        return prefixes.some((prefix) => path === prefix || path.startsWith(`${prefix}/`));
    }

    private readCurrentPath(): string {
        return this.router.url.split(/[?#;]/)[0];
    }
}
