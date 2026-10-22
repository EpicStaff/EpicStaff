import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { AppStorageService } from '@shared/services';
import { Subject } from 'rxjs';

import { ActiveOrgService } from '../../../services/auth/active-org.service';
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

describe('AvailablePluginsStorageService', () => {
    let responses: Subject<AvailablePlugin[]>[];
    let config: { isPluginsEnabled: boolean };
    const api = {
        list: vi.fn(() => {
            const response = new Subject<AvailablePlugin[]>();
            responses.push(response);
            return response;
        }),
    };

    function setup(isPluginsEnabled = true, orgId: number | null = 1): AvailablePluginsStorageService {
        config = { isPluginsEnabled };
        TestBed.configureTestingModule({
            providers: [
                providePluginsStorages(),
                { provide: AvailablePluginsApiService, useValue: api },
                { provide: ConfigService, useValue: config },
            ],
        });
        TestBed.inject(ActiveOrgService).set(orgId);
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

    it('drops a response that lands after an org switch cleared the storage through APP_STORAGE', () => {
        const storage = setup();
        const guardResults: AvailablePlugin[][] = [];
        storage.loadForActiveOrg().subscribe((plugins) => guardResults.push(plugins));

        // What ProfileService.switchOrg does: clear every storage, then set the new org.
        TestBed.inject(AppStorageService).clearAll();
        TestBed.inject(ActiveOrgService).set(2);
        responses[0].next([plugin('weather', 'Weather')]);

        expect(storage.plugins()).toEqual([]);
        expect(guardResults).toEqual([[]]);

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
