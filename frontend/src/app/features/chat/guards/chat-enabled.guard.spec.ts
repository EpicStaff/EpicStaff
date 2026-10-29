import { TestBed } from '@angular/core/testing';
import { ActivatedRouteSnapshot, Router, RouterStateSnapshot, UrlTree } from '@angular/router';

import { PermissionsService } from '../../../services/auth/permissions.service';
import { ConfigService } from '../../../services/config';
import { chatEnabledGuard } from './chat-enabled.guard';

describe('chatEnabledGuard', () => {
    function run(isChatEnabled: boolean): boolean | UrlTree {
        TestBed.configureTestingModule({
            providers: [
                { provide: ConfigService, useValue: { isChatEnabled } as unknown as ConfigService },
                {
                    provide: PermissionsService,
                    useValue: { resolveDefaultRoute: () => '/flows' } as unknown as PermissionsService,
                },
            ],
        });
        return TestBed.runInInjectionContext(() =>
            chatEnabledGuard({} as ActivatedRouteSnapshot, {} as RouterStateSnapshot)
        ) as boolean | UrlTree;
    }

    it('lets the route activate when chat is enabled', () => {
        expect(run(true)).toBe(true);
    });

    it('redirects to the default route when chat is disabled', () => {
        const result = run(false);
        expect(result).toBeInstanceOf(UrlTree);
        expect(TestBed.inject(Router).serializeUrl(result as UrlTree)).toBe('/flows');
    });
});
