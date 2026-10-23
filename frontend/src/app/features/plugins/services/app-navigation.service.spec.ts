import { signal, WritableSignal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { GetMeResponse } from '@shared/models';

import { PermissionsService } from '../../../services/auth/permissions.service';
import { ProfileService } from '../../../services/auth/profile.service';
import { ConfigService } from '../../../services/config';
import { AvailablePlugin } from '../models/available-plugin.model';
import { pluginPageMatcher } from '../pages/plugin-host-page/plugin-page.matcher';
import { buildAvailablePlugin, buildAvailablePluginNavigationItem } from '../testing/plugin-fixtures';
import { AppNavigationService } from './app-navigation.service';
import { AppReturnUrlService } from './app-return-url.service';
import { AvailablePluginsStorageService } from './available-plugins-storage.service';

const ASG = buildAvailablePlugin({
    identifier: 'asg',
    name: 'ASG',
    navigation: [
        buildAvailablePluginNavigationItem({ label: 'Overview', path: '/' }),
        buildAvailablePluginNavigationItem({ label: 'Projects', path: '/projects' }),
        buildAvailablePluginNavigationItem({ label: 'Broken', path: '/projects/' }),
        buildAvailablePluginNavigationItem({ label: ' ', path: '/blank' }),
    ],
});
const WEATHER = buildAvailablePlugin();

describe('AppNavigationService', () => {
    let plugins: WritableSignal<AvailablePlugin[]>;
    let loadedOrgId: WritableSignal<number | null>;
    let isSuperadmin: boolean;
    let isPluginsEnabled: boolean;
    let service: AppNavigationService;
    let router: Router;

    beforeEach(() => {
        plugins = signal([ASG, WEATHER]);
        loadedOrgId = signal(1);
        isSuperadmin = false;
        isPluginsEnabled = true;
        TestBed.configureTestingModule({
            providers: [
                provideRouter([
                    { matcher: pluginPageMatcher, children: [] },
                    { path: '**', children: [] },
                ]),
                { provide: AvailablePluginsStorageService, useValue: { plugins, loadedOrgId } },
                { provide: ProfileService, useValue: { currentUserSignal: signal({ id: 7 } as GetMeResponse) } },
                {
                    provide: PermissionsService,
                    useValue: {
                        resolveDefaultRoute: () => '/agents',
                        get isSuperadmin(): boolean {
                            return isSuperadmin;
                        },
                    },
                },
                {
                    provide: ConfigService,
                    useValue: {
                        get isPluginsEnabled(): boolean {
                            return isPluginsEnabled;
                        },
                    },
                },
            ],
        });
        service = TestBed.inject(AppNavigationService);
        router = TestBed.inject(Router);
    });

    afterEach(() => {
        localStorage.clear();
        sessionStorage.clear();
    });

    it('follows the address between EpicStaff and an app', async () => {
        await router.navigateByUrl('/flows/my');
        expect(service.context()).toEqual({ kind: 'epicstaff' });
        expect(service.currentApp()).toBeNull();

        await router.navigateByUrl('/plugins/asg/projects/2?tab=content');
        expect(service.context()).toEqual({ kind: 'app', identifier: 'asg', pageSegments: ['projects', '2'] });
        expect(service.currentApp()).toBe(ASG);
    });

    it('builds the menu as router links, dropping an item with a broken path or a blank label', async () => {
        await router.navigateByUrl('/plugins/asg');

        expect(service.menu().map(({ label, link }) => [label, link])).toEqual([
            ['Overview', ['/plugins', 'asg']],
            ['Projects', ['/plugins', 'asg', 'projects']],
        ]);
    });

    it('moves the highlight with every navigation, as the one a plugin page asks for with nav.changed', async () => {
        await router.navigateByUrl('/plugins/asg');
        expect(service.activeMenuItem()?.label).toBe('Overview');

        await router.navigate(['/plugins', 'asg', 'projects', '2'], { replaceUrl: true });
        expect(service.activeMenuItem()?.label).toBe('Projects');

        await router.navigateByUrl('/plugins/asg/reports');
        expect(service.activeMenuItem()).toBeNull();
    });

    it('has no menu for an app without one, or one missing from the list', async () => {
        await router.navigateByUrl('/plugins/weather');
        expect(service.menu()).toEqual([]);

        await router.navigateByUrl('/plugins/gone/projects');
        expect(service.currentApp()).toBeNull();
        expect(service.menu()).toEqual([]);
    });

    it('leads back to the last EpicStaff page with its query, else to the default page', () => {
        expect(router.serializeUrl(service.returnUrl())).toBe('/agents');

        TestBed.inject(AppReturnUrlService).record('/storage/files?folder=7');

        expect(router.serializeUrl(service.returnUrl())).toBe('/storage/files?folder=7');
    });

    it('offers the address shown as a plain link', async () => {
        await router.navigateByUrl('/plugins/asg/projects?tab=1');

        expect(service.currentHref()).toBe('/plugins/asg/projects?tab=1');
    });

    it.each([
        { pluginsOn: true, superadmin: true, expected: true },
        { pluginsOn: true, superadmin: false, expected: false },
        { pluginsOn: false, superadmin: true, expected: false },
    ])(
        'lets a SuperAdmin manage apps while plugins are on ($pluginsOn, $superadmin)',
        ({ pluginsOn, superadmin, expected }) => {
            isPluginsEnabled = pluginsOn;
            isSuperadmin = superadmin;

            expect(service.canManageApps()).toBe(expected);
        }
    );

    it('hands out the new apps once, when a list opens', () => {
        TestBed.tick();
        plugins.set([ASG, WEATHER, buildAvailablePlugin({ identifier: 'atlas', name: 'Atlas' })]);
        expect(service.hasNewApps()).toBe(true);

        expect([...service.acknowledgeNewApps()]).toEqual(['atlas']);

        expect(service.hasNewApps()).toBe(false);
        expect([...service.acknowledgeNewApps()]).toEqual([]);
    });
});
