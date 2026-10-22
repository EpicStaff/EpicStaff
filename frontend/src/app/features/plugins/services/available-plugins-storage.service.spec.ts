import { HttpErrorResponse } from '@angular/common/http';
import { signal, WritableSignal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { ActivePermissions } from '@shared/models';
import { APP_STORAGE, AppStorageService } from '@shared/services';
import { Subject } from 'rxjs';

import { ActiveOrgService } from '../../../services/auth/active-org.service';
import { PermissionsService } from '../../../services/auth/permissions.service';
import { ConfigService } from '../../../services/config';
import { AvailablePlugin } from '../models/available-plugin.model';
import { providePluginsStorages } from '../plugins.providers';
import { AvailablePluginsApiService } from './available-plugins-api.service';
import { AVAILABLE_PLUGINS_RETRY_DELAY_MS, AvailablePluginsStorageService } from './available-plugins-storage.service';

function plugin(identifier: string, name: string): AvailablePlugin {
    return {
        identifier,
        name,
        icon_url: `/api/plugin-public/${identifier}/icon/?v=1.0.0`,
        frame_origin: `https://${identifier}.plugins.example.com`,
        permissions: ['read'],
        availability: 'ready',
        development: false,
    };
}

function permissionsIn(orgId: number): ActivePermissions {
    return { org_id: orgId, is_superadmin: false, role: { id: 1, name: 'Member' }, permissions: '*' };
}

describe('AvailablePluginsStorageService', () => {
    let responses: Subject<AvailablePlugin[]>[];
    /** What `ConfigService.isPluginsEnabled` reads: a signal that is `false` until the config loads, as in the app. */
    let isPluginsEnabled: WritableSignal<boolean>;
    const api = {
        list: vi.fn(() => {
            const response = new Subject<AvailablePlugin[]>();
            responses.push(response);
            return response;
        }),
    };

    /** The storages registered as `app.config.ts` does, before the config has loaded and before anyone signed in. */
    function configure(): void {
        isPluginsEnabled = signal(false);
        TestBed.configureTestingModule({
            providers: [
                { provide: APP_STORAGE, useExisting: ActiveOrgService, multi: true },
                { provide: APP_STORAGE, useExisting: PermissionsService, multi: true },
                providePluginsStorages(),
                { provide: AvailablePluginsApiService, useValue: api },
                {
                    provide: ConfigService,
                    useValue: {
                        get isPluginsEnabled(): boolean {
                            return isPluginsEnabled();
                        },
                    },
                },
            ],
        });
    }

    /** What `ProfileService.bootstrapUser` does for the signed-in user: settle the active org, then load the user's permissions in it. */
    function signIn(orgId: number | null): void {
        TestBed.inject(ActiveOrgService).set(orgId);
        TestBed.inject(PermissionsService).setActivePermissions(orgId === null ? null : permissionsIn(orgId));
    }

    /** A user signed in to `orgId`, with the config loaded. */
    function setup(pluginsEnabled = true, orgId: number | null = 1): AvailablePluginsStorageService {
        configure();
        isPluginsEnabled.set(pluginsEnabled);
        signIn(orgId);
        const storage = TestBed.inject(AvailablePluginsStorageService);
        TestBed.tick();
        return storage;
    }

    beforeEach(() => {
        vi.clearAllMocks();
        responses = [];
    });

    afterEach(() => {
        localStorage.clear();
        vi.useRealTimers();
    });

    it('loads the active organization’s plugins when it starts, sorted by name', () => {
        const storage = setup();

        expect(api.list).toHaveBeenCalledTimes(1);
        responses[0].next([plugin('weather', 'Weather'), plugin('atlas', 'Atlas')]);

        expect(storage.plugins().map(({ identifier }) => identifier)).toEqual(['atlas', 'weather']);
    });

    it('loads after a page reload, where the organization is restored before the config and the session', () => {
        // A reload restores the active organization from localStorage while the storages are created, before
        // /config.json, the token refresh and the profile have loaded.
        configure();
        TestBed.inject(ActiveOrgService).set(1);
        const storage = TestBed.inject(AvailablePluginsStorageService);
        TestBed.tick();

        isPluginsEnabled.set(true);
        TestBed.tick();
        // No session yet: a request now would go out without a token.
        expect(api.list).not.toHaveBeenCalled();

        signIn(1);
        TestBed.tick();

        expect(api.list).toHaveBeenCalledTimes(1);
        responses[0].next([plugin('atlas', 'Atlas')]);
        expect(storage.plugins().map(({ identifier }) => identifier)).toEqual(['atlas']);
    });

    it('asks only for the organization the session settles on when the restored one is no longer the user’s', () => {
        configure();
        isPluginsEnabled.set(true);
        TestBed.inject(ActiveOrgService).set(1);
        const storage = TestBed.inject(AvailablePluginsStorageService);
        TestBed.tick();

        signIn(2);
        TestBed.tick();

        expect(api.list).toHaveBeenCalledTimes(1);
        responses[0].next([plugin('atlas', 'Atlas')]);
        expect(storage.plugins().map(({ identifier }) => identifier)).toEqual(['atlas']);
    });

    it('drops a response that lands after an org switch cleared the storage through APP_STORAGE', () => {
        const storage = setup();
        const guardResults: AvailablePlugin[][] = [];
        storage.loadForActiveOrg().subscribe((plugins) => guardResults.push(plugins));

        // What ProfileService.switchOrg does: clear every storage, set the new org, then load its permissions.
        TestBed.inject(AppStorageService).clearAll();
        TestBed.inject(ActiveOrgService).set(2);
        responses[0].next([plugin('weather', 'Weather')]);

        expect(storage.plugins()).toEqual([]);
        expect(guardResults).toEqual([[]]);

        TestBed.inject(PermissionsService).setActivePermissions(permissionsIn(2));
        TestBed.tick();
        expect(api.list).toHaveBeenCalledTimes(2);
        responses[1].next([plugin('atlas', 'Atlas')]);
        expect(storage.plugins().map(({ identifier }) => identifier)).toEqual(['atlas']);
    });

    it('drops the response of an organization that is no longer active, even without a clear', () => {
        const storage = setup();

        TestBed.inject(ActiveOrgService).set(2);
        TestBed.tick();
        responses[1].next([plugin('atlas', 'Atlas')]);
        responses[0].next([plugin('weather', 'Weather')]);

        expect(storage.plugins().map(({ identifier }) => identifier)).toEqual(['atlas']);
    });

    it('shares a load under way, then answers from what it holds', () => {
        const storage = setup();
        const results: string[][] = [];
        const collect = (plugins: AvailablePlugin[]): number =>
            results.push(plugins.map(({ identifier }) => identifier));

        storage.loadForActiveOrg().subscribe(collect);
        responses[0].next([plugin('weather', 'Weather')]);
        responses[0].complete();
        storage.loadForActiveOrg().subscribe(collect);

        expect(api.list).toHaveBeenCalledTimes(1);
        expect(results).toEqual([['weather'], ['weather']]);
    });

    it('answers [] after a refused load without retrying it, and tries again on the next request', () => {
        const storage = setup();
        const results: AvailablePlugin[][] = [];

        storage.loadForActiveOrg().subscribe((plugins) => results.push(plugins));
        responses[0].error(new HttpErrorResponse({ status: 403 }));
        expect(api.list).toHaveBeenCalledTimes(1);
        storage.loadForActiveOrg().subscribe();

        expect(results).toEqual([[]]);
        expect(api.list).toHaveBeenCalledTimes(2);
    });

    it('retries a network failure or a server error once, after a pause', () => {
        vi.useFakeTimers();
        const storage = setup();

        responses[0].error(new HttpErrorResponse({ status: 503 }));
        expect(api.list).toHaveBeenCalledTimes(1);
        vi.advanceTimersByTime(AVAILABLE_PLUGINS_RETRY_DELAY_MS);
        expect(api.list).toHaveBeenCalledTimes(2);
        responses[1].next([plugin('weather', 'Weather')]);

        expect(storage.plugins().map(({ identifier }) => identifier)).toEqual(['weather']);
    });

    it('gives up after the one retry, leaving the list empty', () => {
        vi.useFakeTimers();
        const storage = setup();

        responses[0].error(new HttpErrorResponse({ status: 0 }));
        vi.advanceTimersByTime(AVAILABLE_PLUGINS_RETRY_DELAY_MS);
        responses[1].error(new HttpErrorResponse({ status: 0 }));
        vi.advanceTimersByTime(AVAILABLE_PLUGINS_RETRY_DELAY_MS);

        expect(api.list).toHaveBeenCalledTimes(2);
        expect(storage.plugins()).toEqual([]);
    });

    it('refresh() loads a held list again, and shares a load under way', () => {
        const storage = setup();
        responses[0].next([plugin('weather', 'Weather')]);
        responses[0].complete();

        storage.refresh().subscribe();
        storage.refresh().subscribe();
        expect(api.list).toHaveBeenCalledTimes(2);
        expect(storage.plugins().map(({ identifier }) => identifier)).toEqual(['weather']);

        responses[1].next([plugin('weather', 'Weather'), plugin('atlas', 'Atlas')]);
        expect(storage.plugins().map(({ identifier }) => identifier)).toEqual(['atlas', 'weather']);
    });

    it('requests nothing while the plugin platform is off', () => {
        const storage = setup(false);
        let result: AvailablePlugin[] | null = null;
        storage.loadForActiveOrg().subscribe((plugins) => (result = plugins));
        storage.refresh().subscribe();

        expect(api.list).not.toHaveBeenCalled();
        expect(result).toEqual([]);
    });

    it('requests nothing without an active organization', () => {
        const storage = setup(true, null);
        let result: AvailablePlugin[] | null = null;
        storage.loadForActiveOrg().subscribe((plugins) => (result = plugins));

        expect(api.list).not.toHaveBeenCalled();
        expect(result).toEqual([]);
    });

    it('logout clears the list and keeps it clear', () => {
        const storage = setup();
        responses[0].next([plugin('weather', 'Weather')]);

        TestBed.inject(AppStorageService).clearAll();
        TestBed.inject(ActiveOrgService).set(null);
        TestBed.tick();

        expect(storage.plugins()).toEqual([]);
        expect(api.list).toHaveBeenCalledTimes(1);
    });
});
