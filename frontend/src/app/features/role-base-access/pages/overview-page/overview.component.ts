import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { RouteTab, RouteTabsComponent } from '@shared/components';
import { ActionCode, ResourceCode } from '@shared/models';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { HideInlineSubtitleOnOverflowDirective } from '../../../../shared/directives/hide-inline-subtitle-on-overflow.directive';

@Component({
    selector: 'app-overview',
    templateUrl: './overview.component.html',
    styleUrls: ['./overview.component.scss'],
    imports: [RouterOutlet, HideInlineSubtitleOnOverflowDirective, RouteTabsComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class OverviewComponent {
    private readonly permissionsService = inject(PermissionsService);

    protected readonly tabs: RouteTab[] = [
        {
            routerLink: 'main',
            icon: 'home',
            label: 'Main',
            isPermitted: () => this.permissionsService.isSuperadmin,
        },
        {
            routerLink: 'organizations',
            icon: 'buildings',
            label: 'Organizations',
            isPermitted: () => this.permissionsService.canInAnyOrg(ResourceCode.Organizations, ActionCode.Read),
        },
        {
            routerLink: 'users',
            icon: 'profile',
            label: 'Users',
            isPermitted: () => this.permissionsService.canInAnyOrg(ResourceCode.Users, ActionCode.Read),
        },
        {
            routerLink: 'roles',
            icon: 'briefcase',
            label: 'Roles',
            isPermitted: () => this.permissionsService.canInAnyOrg(ResourceCode.Roles, ActionCode.Read),
        },
        {
            routerLink: 'api-keys',
            icon: 'key',
            label: 'API Keys',
            isPermitted: () => this.permissionsService.canInAnyOrg(ResourceCode.Secrets, ActionCode.Read),
        },
    ];
}
