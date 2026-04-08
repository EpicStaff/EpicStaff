import { OverlayModule } from '@angular/cdk/overlay';
import { PortalModule } from '@angular/cdk/portal';
import {
    AfterViewInit,
    ChangeDetectionStrategy,
    Component,
    CUSTOM_ELEMENTS_SCHEMA,
    ElementRef,
    ViewChild,
} from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { environment } from 'src/environments/environment';

import { EpicChatService } from '../../../features/epic-chat/epic-chat.service';
import { SettingsDialogService } from '../../../features/settings-dialog/settings-dialog.service';
import { ConfigService } from '../../../services/config/config.service';
import { AppSvgIconComponent } from '../../../shared/components/app-svg-icon/app-svg-icon.component';
import { TooltipComponent } from './tooltip/tooltip.component';

interface NavItem {
    id: string;
    routeLink?: string;
    icon?: string;
    label: string;
    showTooltip: boolean;
    action?: () => void;
    customClass?: string;
}

@Component({
    selector: 'app-left-sidebar',
    standalone: true,
    imports: [TooltipComponent, RouterLinkActive, RouterLink, OverlayModule, PortalModule, AppSvgIconComponent],
    templateUrl: './sidenav.component.html',
    styleUrls: ['./sidenav.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    schemas: [CUSTOM_ELEMENTS_SCHEMA],
})
export class LeftSidebarComponent implements AfterViewInit {
    public topNavItems: NavItem[];
    public bottomNavItems: NavItem[];
    public isEpicChatEnabled: boolean;
    public apiBaseUrl: string;
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
    @ViewChild('epicChat', { static: false })
    private epicChat?: ElementRef<HTMLElement>;

    constructor(
        public epicChatService: EpicChatService,
        private settingsDialogService: SettingsDialogService,
        private configService: ConfigService
    ) {
        this.isEpicChatEnabled = this.configService.isEpicChatEnabled;
        // COMMIT_COMMENTS: Derive apiBaseUrl from browser origin so the EpicChat widget's
        // syncAgentsFromApi call always matches the actual access host (localhost vs 127.0.0.1),
        // avoiding CORS failures and hardcoded URLs.
        // this.apiBaseUrl = `${window.location.origin}/api/`;

        // Bad approach to use window.location because ui and backend can be on different domains
        // fixed localhost vs 127.0.0.1 problem in widget code
        this.apiBaseUrl = environment.apiUrl;
        this.topNavItems = [
            {
                id: 'projects',
                routeLink: 'projects',
                icon: 'project',
                label: 'Projects',
                showTooltip: false,
            },
            {
                id: 'staff',
                routeLink: 'staff',
                icon: 'agent',
                label: 'Staff',
                showTooltip: false,
            },
            {
                id: 'tools',
                routeLink: 'tools',
                icon: 'tools',
                label: 'Tools',
                showTooltip: false,
            },
            {
                id: 'flows',
                routeLink: 'flows',
                icon: 'flows',
                label: 'Flows',
                showTooltip: false,
            },
            {
                id: 'knowledge-sources',
                routeLink: 'knowledge-sources',
                icon: 'sources',
                label: 'Knowledge Sources',
                showTooltip: false,
            },
            {
                id: 'chats',
                routeLink: 'chats',
                icon: 'chats',
                label: 'Chats',
                showTooltip: false,
            },
        ];

        this.bottomNavItems = [];
        this.bottomNavItems.push({
            id: 'settings',
            icon: 'settings',
            label: 'Settings',
            showTooltip: false,
            action: () => this.onSettingsClick(),
            customClass: 'settings-tooltip',
        });
    }

    public ngAfterViewInit(): void {
        // COMMIT_COMMENTS: Widget's internal syncAgentsFromApi does not reliably fire in
        // custom-element mode. Instead, we use AGENT_REMOVE + AGENT_CREATE per flow —
        // idempotent sync that works on every load without creating duplicates.
        if (this.isEpicChatEnabled) {
            setTimeout(() => this.epicChatService.reconnectAgents(), 2000);
        }
    }

    private onSettingsClick(): void {
        this.settingsDialogService.openSettingsDialog();
    }

    public toggleEpicChat(): void {
        this.epicChatService.toggleChat(this.epicChat?.nativeElement);
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
}
