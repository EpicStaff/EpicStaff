import { TestBed } from '@angular/core/testing';
import { ActivatedRouteSnapshot, provideRouter, Router, RouterStateSnapshot, UrlTree } from '@angular/router';
import { ResourceCode } from '@shared/models';

import { PermissionsService } from '../../../services/auth/permissions.service';
import { ConfigService } from '../../../services/config';
import { AuditDomainName } from '../models/audit-domain.models';
import { allowedAuditTabs, sessionAuditEnabledGuard, userAuditEnabledGuard } from './audit-domain-enabled.guard';

const DEFAULT_ROUTE = '/agents';

function configure(
    switches: { isSessionAuditEnabled: boolean; isUserAuditEnabled: boolean },
    readable: ResourceCode[] = [ResourceCode.Audit, ResourceCode.UserAudit]
): void {
    TestBed.configureTestingModule({
        providers: [
            provideRouter([]),
            { provide: ConfigService, useValue: switches },
            {
                provide: PermissionsService,
                useValue: {
                    resolveDefaultRoute: () => DEFAULT_ROUTE,
                    can: (resource: ResourceCode) => readable.includes(resource),
                },
            },
        ],
    });
}

function run(guard: typeof sessionAuditEnabledGuard): unknown {
    return TestBed.runInInjectionContext(() => guard({} as ActivatedRouteSnapshot, {} as RouterStateSnapshot));
}

describe('allowedAuditTabs', () => {
    const cases: [boolean, boolean, ResourceCode[], AuditDomainName[]][] = [
        [true, true, [ResourceCode.Audit, ResourceCode.UserAudit], ['sessions', 'user_actions']],
        [true, true, [ResourceCode.UserAudit], ['user_actions']],
        [true, false, [ResourceCode.Audit, ResourceCode.UserAudit], ['sessions']],
        [false, true, [ResourceCode.Audit], []],
        [false, false, [ResourceCode.Audit, ResourceCode.UserAudit], []],
    ];

    it.each(cases)('switches %s/%s with read on %j gives %j', (session, user, readable, expected) => {
        configure({ isSessionAuditEnabled: session, isUserAuditEnabled: user }, readable);

        expect(TestBed.runInInjectionContext(() => allowedAuditTabs())).toEqual(expected);
    });
});

describe('audit domain guards', () => {
    it('allows a tab whose switch is on', () => {
        configure({ isSessionAuditEnabled: true, isUserAuditEnabled: true });

        expect(run(sessionAuditEnabledGuard)).toBe(true);
        expect(run(userAuditEnabledGuard)).toBe(true);
    });

    it('redirects to the default route when only the other switch is on', () => {
        configure({ isSessionAuditEnabled: true, isUserAuditEnabled: false });

        const result = run(userAuditEnabledGuard);

        expect(run(sessionAuditEnabledGuard)).toBe(true);
        expect(result).toBeInstanceOf(UrlTree);
        expect(TestBed.inject(Router).serializeUrl(result as UrlTree)).toBe(DEFAULT_ROUTE);
    });
});
