import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { ActionCode, ResourceCode } from '@shared/models';

import { PermissionsService } from '../../../services/auth/permissions.service';
import { ConfigService } from '../../../services/config';
import { AuditDomainName } from '../models/audit-domain.models';

const AUDIT_DOMAIN_RESOURCES: Record<AuditDomainName, ResourceCode> = {
    sessions: ResourceCode.Audit,
    user_actions: ResourceCode.UserAudit,
};

/** The audit tabs the caller may open: the deployment switch is on and the role can read; sessions first. */
export function auditTabsFor(configService: ConfigService, permissionsService: PermissionsService): AuditDomainName[] {
    const switches: Record<AuditDomainName, boolean> = {
        sessions: configService.isSessionAuditEnabled,
        user_actions: configService.isUserAuditEnabled,
    };
    return (Object.keys(AUDIT_DOMAIN_RESOURCES) as AuditDomainName[]).filter(
        (domain) => switches[domain] && permissionsService.can(AUDIT_DOMAIN_RESOURCES[domain], ActionCode.Read)
    );
}

export function allowedAuditTabs(): AuditDomainName[] {
    return auditTabsFor(inject(ConfigService), inject(PermissionsService));
}

/**
 * Blocks an audit tab when the deployment runs without that domain (the auditor service is not started then,
 * so the page could only show errors). Redirects to the caller's default route, as a forbidden page does.
 */
function domainEnabledGuard(isEnabled: (configService: ConfigService) => boolean): CanActivateFn {
    return () => {
        const permissionsService = inject(PermissionsService);
        return isEnabled(inject(ConfigService))
            ? true
            : inject(Router).parseUrl(permissionsService.resolveDefaultRoute());
    };
}

export const sessionAuditEnabledGuard = domainEnabledGuard((configService) => configService.isSessionAuditEnabled);
export const userAuditEnabledGuard = domainEnabledGuard((configService) => configService.isUserAuditEnabled);
