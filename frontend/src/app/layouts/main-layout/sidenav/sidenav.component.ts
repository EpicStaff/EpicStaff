import { OverlayModule } from '@angular/cdk/overlay';
import { PortalModule } from '@angular/cdk/portal';
import {
    AfterViewInit,
    ChangeDetectionStrategy,
    Component,
    computed,
    CUSTOM_ELEMENTS_SCHEMA,
    DestroyRef,
    ElementRef,
    inject,
    signal,
    ViewChild,
} from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterLink } from '@angular/router';
import { AppSvgIconComponent } from '@shared/components';
import { ClickOutsideDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import { filter, map } from 'rxjs/operators';

import { EpicChatService } from '../../../features/epic-chat/epic-chat.service';
import { OrgAvatarComponent } from '../../../features/role-base-access/components/org-avatar/org-avatar.component';
import { OrganizationsMenuComponent } from '../../../features/role-base-access/components/organizations-sidebar-menu/organizations-menu.component';
import { UserAvatarComponent } from '../../../features/role-base-access/components/user-avatar/user-avatar.component';
import { UserMenuComponent } from '../../../features/role-base-access/components/user-sidebar-menu/user-menu.component';
import { ActiveOrgService } from '../../../services/auth/active-org.service';
import { AuthService } from '../../../services/auth/auth.service';
import { PermissionsService } from '../../../services/auth/permissions.service';
import { ProfileService } from '../../../services/auth/profile.service';
import { ConfigService } from '../../../services/config';
import { EasterEggTriggerService } from '../../../services/easter-egg-trigger.service';
import { TooltipComponent } from './tooltip/tooltip.component';

interface NavItem {
    id: string;
    routeLink?: string | (() => string | null);
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
    ],
    templateUrl: './sidenav.component.html',
    styleUrls: ['./sidenav.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    schemas: [CUSTOM_ELEMENTS_SCHEMA],
})
export class LeftSidebarComponent implements AfterViewInit {
    private currentUserService = inject(ProfileService);
    private destroyRef = inject(DestroyRef);
    private readonly easterEggTrigger = inject(EasterEggTriggerService);

    public topNavItems: NavItem[];
    public bottomNavItems: NavItem[];
    public isEpicChatEnabled: boolean;
    public apiBaseUrl: string;
    /** Follows every token refresh so the EpicChat widget never holds a stale JWT. */
    protected readonly accessToken = computed(() => this.authService.accessToken() ?? '');
    public showLogoTooltip = false;
    public showProfileTooltip = false;
    public readonly epicChatThemeConfig = {
        semantic: {
            surface: 'var(--color-background-body)',
            surfaceAlt: 'var(--color-nodes-background)',
            text: 'var(--color-text-primary)',
            textMuted: 'var(--color-text-secondary)',
            border: 'var(--color-divider-regular)',
            borderMuted: 'var(--color-divider-subtle)',
            accent: 'var(--accent-color)',
            accentContrast: 'var(--color-text-primary)',
            accentSoft: 'var(--color-ghost-btn-hover)',
            danger: 'var(--color-ks-status-failed)',
            dangerSoft: 'var(--agent-node-accent-color)',
            disabledBg: 'var(--gray-600)',
            scrollbar: 'var(--color-scrollbar-thumb)',
        },
        components: {
            chat: {
                bgQuestion: 'var(--accent-color)',
                // bgAnswer: 'var(--color-nodes-background)',
                bgAnswer: '#2b2d30',
                textQuestion: 'var(--color-text-primary)',
            },
            header: {
                iconColor: 'var(--accent-color)',
            },
            table: {
                headerBg: 'transparent',
                headerText: 'var(--color-text-secondary)',
                rowBg: 'transparent',
                rowAltBg: 'color-mix(in srgb, var(--color-nodes-background) 65%, transparent)',
                rowHoverBg: 'var(--color-ghost-btn-hover)',
                border: 'var(--color-divider-subtle)',
                columnDivider: 'var(--color-divider-regular)',
                cellText: 'var(--color-text-primary)',
            },
            button: {
                radius: '6px',
                heightMd: '28px',
                paddingMd: '6px 10px',
                fontSizeMd: '12px',
                secondaryBg: 'transparent',
                secondaryBorder: 'var(--color-divider-regular)',
                secondaryText: 'var(--color-text-primary)',
                secondaryHoverBg: 'var(--color-ghost-btn-hover)',
                primaryBg: 'var(--color-nodes-background)',
                primaryBorder: 'var(--accent-color)',
                primaryText: 'var(--accent-color)',
                primaryHoverBg: 'color-mix(in srgb, var(--color-nodes-background) 70%, var(--accent-color) 30%)',
                ghostBg: 'transparent',
                ghostText: 'var(--color-text-secondary)',
                ghostHoverBg: 'var(--color-ghost-btn-hover)',
            },
        },
        foundation: {
            shadowMd: 'rgba(0, 0, 0, 0.6)',
        },
    };

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

    @ViewChild('epicChat', { static: false })
    private epicChat?: ElementRef<HTMLElement>;

    /** Gates the EpicChat widget's own flow-list request. Read as a method (not a field) so the
     *  binding re-evaluates when active-org permissions reload after an org switch. */
    public canReadFlows(): boolean {
        return this.permissionService.can(ResourceCode.Flows, ActionCode.Read);
    }

    public readonly epicChatService = inject(EpicChatService);
    public readonly activeOrgService = inject(ActiveOrgService);
    private readonly configService = inject(ConfigService);
    private readonly authService = inject(AuthService);
    private readonly permissionService = inject(PermissionsService);

    constructor() {
        this.isEpicChatEnabled = this.configService.isEpicChatEnabled;
        // COMMIT_COMMENTS: Derive apiBaseUrl from browser origin so the EpicChat widget's
        // syncAgentsFromApi call always matches the actual access host (localhost vs 127.0.0.1),
        // avoiding CORS failures and hardcoded URLs.
        // this.apiBaseUrl = `${window.location.origin}/api/`;

        // Comment on the comment above:
        // Bad approach to use window.location because ui and backend can be on different domains
        // fixed localhost vs 127.0.0.1 problem in widget code
        this.apiBaseUrl = this.configService.apiUrl;
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
                routeLink: () => this.permissionService.resolveStorageTab(),
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
                isPermitted: () => this.permissionService.can(ResourceCode.Audit, ActionCode.Read),
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
    }

    public ngAfterViewInit(): void {
        if (this.isEpicChatEnabled) {
            setTimeout(() => this.epicChatService.reconnectAgents(), 2000);
        }
    }

    public onLogoClick(): void {
        this.easterEggTrigger.registerLogoClick();
    }

    public toggleEpicChat(): void {
        this.epicChatService.toggleChat(this.epicChat?.nativeElement);
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

    public onEpChatCommandResult(event: Event): void {
        this.epicChatService.onEpChatCommandResult(event);
    }

    public onEpChatEvent(event: Event): void {
        this.epicChatService.onEpChatEvent(event);
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
        if (typeof item.routeLink === 'function') return item.routeLink();
        return item.routeLink ?? null;
    }

    private readCurrentPath(): string {
        return this.router.url.split(/[?#;]/)[0];
    }
}
