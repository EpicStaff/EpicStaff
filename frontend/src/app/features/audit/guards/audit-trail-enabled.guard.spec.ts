import { TestBed } from '@angular/core/testing';
import { ActivatedRouteSnapshot, provideRouter, Router, RouterStateSnapshot, UrlTree } from '@angular/router';

import { PermissionsService } from '../../../services/auth/permissions.service';
import { ConfigService } from '../../../services/config';
import { auditTrailEnabledGuard } from './audit-trail-enabled.guard';

const DEFAULT_ROUTE = '/agents';

function runGuard(isAuditTrailEnabled: boolean): ReturnType<typeof auditTrailEnabledGuard> {
    TestBed.configureTestingModule({
        providers: [
            provideRouter([]),
            { provide: ConfigService, useValue: { isAuditTrailEnabled } },
            { provide: PermissionsService, useValue: { resolveDefaultRoute: () => DEFAULT_ROUTE } },
        ],
    });
    return TestBed.runInInjectionContext(() =>
        auditTrailEnabledGuard({} as ActivatedRouteSnapshot, {} as RouterStateSnapshot)
    );
}

describe('auditTrailEnabledGuard', () => {
    it('allows navigation when the audit trail is enabled', () => {
        expect(runGuard(true)).toBe(true);
    });

    it('redirects to the default route when the audit trail is disabled', () => {
        const result = runGuard(false);
        const router = TestBed.inject(Router);

        expect(result).toBeInstanceOf(UrlTree);
        expect(router.serializeUrl(result as UrlTree)).toBe(DEFAULT_ROUTE);
    });
});
