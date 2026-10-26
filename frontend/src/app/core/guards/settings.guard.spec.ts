import { provideHttpClient } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { ActivatedRouteSnapshot, CanActivateFn, Router, RouterStateSnapshot, UrlTree } from '@angular/router';
import { ActionCode, ActivePermissions, ResourceCode } from '@shared/models';

import { PermissionsService } from '../../services/auth/permissions.service';
import { ConfigService } from '../../services/config';
import { pluginActivityPermissionGuard, settingsGuard, settingsIndexGuard } from './settings.guard';

type Grants = Partial<Record<ResourceCode, ActionCode[]>>;

/** A role holding only Read on Audit. */
const AUDIT_ONLY: Grants = { [ResourceCode.Audit]: [ActionCode.Read] };

describe('settings guards', () => {
    /** Runs `guard` for a role with `grants` (and nothing that opens another page, so the default is the profile). */
    function run(guard: CanActivateFn, grants: Grants, isPluginsEnabled: boolean): string | true {
        TestBed.resetTestingModule();
        TestBed.configureTestingModule({
            providers: [provideHttpClient(), { provide: ConfigService, useValue: { isPluginsEnabled } }],
        });
        TestBed.inject(PermissionsService).setActivePermissions({
            org_id: 1,
            is_superadmin: false,
            role: { id: 1, name: 'Custom' },
            permissions: grants as ActivePermissions['permissions'],
        });
        const result = TestBed.runInInjectionContext(() =>
            guard({} as ActivatedRouteSnapshot, {} as RouterStateSnapshot)
        ) as boolean | UrlTree;
        return result === true ? true : TestBed.inject(Router).serializeUrl(result as UrlTree);
    }

    describe('settingsGuard', () => {
        it('lets a role that reads only the audit trail into Settings while plugins are on', () => {
            expect(run(settingsGuard, AUDIT_ONLY, true)).toBe(true);
        });

        it('keeps that role out while plugins are off', () => {
            expect(run(settingsGuard, AUDIT_ONLY, false)).toBe('/profile');
        });

        it('still lets in a role with a settings permission and nothing else', () => {
            expect(run(settingsGuard, { [ResourceCode.Voice]: [ActionCode.Read] }, false)).toBe(true);
        });
    });

    describe('settingsIndexGuard', () => {
        it('sends a role that reads only the audit trail to plugin activity while plugins are on', () => {
            expect(run(settingsIndexGuard, AUDIT_ONLY, true)).toBe('/settings/plugin-activity');
        });

        it('sends that role to the default route while plugins are off', () => {
            expect(run(settingsIndexGuard, AUDIT_ONLY, false)).toBe('/profile');
        });

        it('prefers Secrets over plugin activity', () => {
            const grants: Grants = { ...AUDIT_ONLY, [ResourceCode.Secrets]: [ActionCode.Read] };

            expect(run(settingsIndexGuard, grants, true)).toBe('/settings/secrets');
        });
    });

    describe('pluginActivityPermissionGuard', () => {
        it('admits Read on Audit while plugins are on', () => {
            expect(run(pluginActivityPermissionGuard, AUDIT_ONLY, true)).toBe(true);
        });

        it('refuses it while plugins are off, and refuses a role without Read on Audit', () => {
            expect(run(pluginActivityPermissionGuard, AUDIT_ONLY, false)).toBe('/profile');
            expect(run(pluginActivityPermissionGuard, { [ResourceCode.Secrets]: [ActionCode.Read] }, true)).toBe(
                '/profile'
            );
        });
    });
});
