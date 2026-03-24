import { Component, ChangeDetectionStrategy } from '@angular/core';
import { TooltipComponent } from './tooltip/tooltip.component';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { AppSvgIconComponent } from '../../../shared/components/app-svg-icon/app-svg-icon.component';
import { SettingsDialogService } from '../../../features/settings-dialog/settings-dialog.service';
import { OverlayModule } from '@angular/cdk/overlay';
import { PortalModule } from '@angular/cdk/portal';

interface NavItem {
    id: string;
    routeLink?: string;
    icon: string;
    label: string;
    showTooltip: boolean;
    action?: () => void;
    customClass?: string;
}

@Component({
    selector: 'app-left-sidebar',
    standalone: true,
    imports: [
        TooltipComponent,
        RouterLinkActive,
        RouterLink,
        OverlayModule,
        PortalModule,
        AppSvgIconComponent,
    ],
    templateUrl: './sidenav.component.html',
    styleUrls: ['./sidenav.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LeftSidebarComponent {
    public topNavItems: NavItem[];
    public bottomNavItems: NavItem[];

    constructor(
        private settingsDialogService: SettingsDialogService
    ) {
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

        this.bottomNavItems = [
            {
                id: 'settings',
                icon: 'settings',
                label: 'Settings',
                showTooltip: false,
                action: () => this.onSettingsClick(),
                customClass: 'settings-tooltip',
            },
        ];
    }

    private onSettingsClick(): void {
        this.settingsDialogService.openSettingsDialog();
    }

    public handleItemClick(item: NavItem, event: MouseEvent): void {
        if (item.action) {
            event.preventDefault();
            item.action();
        }
    }
}
