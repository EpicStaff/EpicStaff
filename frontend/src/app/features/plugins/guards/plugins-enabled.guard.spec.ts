import { TestBed } from '@angular/core/testing';
import { ActivatedRouteSnapshot, Router, RouterStateSnapshot, UrlTree } from '@angular/router';

import { PermissionsService } from '../../../services/auth/permissions.service';
import { ConfigService } from '../../../services/config';
import { pluginsEnabledGuard } from './plugins-enabled.guard';

describe('pluginsEnabledGuard', () => {
    function run(isPluginsEnabled: boolean): boolean | UrlTree {
        TestBed.configureTestingModule({
            providers: [
                { provide: ConfigService, useValue: { isPluginsEnabled } as unknown as ConfigService },
                {
                    provide: PermissionsService,
                    useValue: { resolveDefaultRoute: () => '/flows' } as unknown as PermissionsService,
                },
            ],
        });
        return TestBed.runInInjectionContext(() =>
            pluginsEnabledGuard({} as ActivatedRouteSnapshot, {} as RouterStateSnapshot)
        ) as boolean | UrlTree;
    }

    it('lets the route activate when the plugin platform is on', () => {
        expect(run(true)).toBe(true);
    });

    it('redirects to the default route when the plugin platform is off', () => {
        const result = run(false);
        expect(result).toBeInstanceOf(UrlTree);
        expect(TestBed.inject(Router).serializeUrl(result as UrlTree)).toBe('/flows');
    });
});
