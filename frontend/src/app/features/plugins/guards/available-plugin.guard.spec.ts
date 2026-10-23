import { TestBed } from '@angular/core/testing';
import { ActivatedRouteSnapshot, convertToParamMap, Router, RouterStateSnapshot, UrlTree } from '@angular/router';
import { firstValueFrom, Observable, of } from 'rxjs';

import { PermissionsService } from '../../../services/auth/permissions.service';
import { AvailablePlugin } from '../models/available-plugin.model';
import { AvailablePluginsStorageService } from '../services/available-plugins-storage.service';
import { buildAvailablePlugin } from '../testing/plugin-fixtures';
import { availablePluginGuard } from './available-plugin.guard';

describe('availablePluginGuard', () => {
    function run(identifier: string, available: AvailablePlugin[]): Promise<boolean | UrlTree> {
        TestBed.configureTestingModule({
            providers: [
                { provide: AvailablePluginsStorageService, useValue: { loadForActiveOrg: () => of(available) } },
                {
                    provide: PermissionsService,
                    useValue: { resolveDefaultRoute: () => '/flows' } as unknown as PermissionsService,
                },
            ],
        });
        const route = { paramMap: convertToParamMap({ identifier }) } as ActivatedRouteSnapshot;
        const result = TestBed.runInInjectionContext(() =>
            availablePluginGuard(route, {} as RouterStateSnapshot)
        ) as Observable<boolean | UrlTree>;
        return firstValueFrom(result);
    }

    it('opens a plugin of the active organization’s available list', async () => {
        expect(await run('weather', [buildAvailablePlugin()])).toBe(true);
    });

    it.each([
        ['a plugin that is not in the list', 'chat', [buildAvailablePlugin()]],
        ['any plugin when the list is empty (off, no organization, or the load failed)', 'weather', []],
    ])('redirects to the default route for %s', async (_label, identifier, available) => {
        const result = await run(identifier, available);

        expect(result).toBeInstanceOf(UrlTree);
        expect(TestBed.inject(Router).serializeUrl(result as UrlTree)).toBe('/flows');
    });
});
