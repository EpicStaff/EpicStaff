import { Component, computed, inject } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { RouteTab, RouteTabsComponent } from '@shared/components';

import { PermissionsService } from '../../services/auth/permissions.service';
import { ConfigService } from '../../services/config';
import { auditTabsFor } from './guards/audit-domain-enabled.guard';
import { AuditDomainName } from './models/audit-domain.models';

const TABS: Record<AuditDomainName, RouteTab> = {
    sessions: { routerLink: 'sessions', label: 'Sessions', isPermitted: () => true },
    user_actions: { routerLink: 'actions', label: 'User Actions', isPermitted: () => true },
};

@Component({
    selector: 'app-audit-page',
    imports: [RouterOutlet, RouteTabsComponent],
    templateUrl: './audit-page.component.html',
    styleUrls: ['./audit-page.component.scss'],
})
export class AuditPageComponent {
    protected readonly routeTabs = computed<RouteTab[]>(() =>
        auditTabsFor(this.configService, this.permissionsService).map((domain) => TABS[domain])
    );

    private readonly configService = inject(ConfigService);
    private readonly permissionsService = inject(PermissionsService);
}
