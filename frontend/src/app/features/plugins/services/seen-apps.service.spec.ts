import { signal, WritableSignal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { GetMeResponse } from '@shared/models';

import { ProfileService } from '../../../services/auth/profile.service';
import { AvailablePlugin } from '../models/available-plugin.model';
import { buildAvailablePlugin } from '../testing/plugin-fixtures';
import { AvailablePluginsStorageService } from './available-plugins-storage.service';
import { SeenAppsService } from './seen-apps.service';

const WEATHER = buildAvailablePlugin();
const ATLAS = buildAvailablePlugin({ identifier: 'atlas', name: 'Atlas' });
const CHART = buildAvailablePlugin({ identifier: 'chart', name: 'Chart' });

describe('SeenAppsService', () => {
    let plugins: WritableSignal<AvailablePlugin[]>;
    let loadedOrgId: WritableSignal<number | null>;
    let user: WritableSignal<GetMeResponse | null>;

    function create(): SeenAppsService {
        TestBed.configureTestingModule({
            providers: [
                { provide: AvailablePluginsStorageService, useValue: { plugins, loadedOrgId } },
                { provide: ProfileService, useValue: { currentUserSignal: user } },
            ],
        });
        const service = TestBed.inject(SeenAppsService);
        TestBed.tick();
        return service;
    }

    /** What the storage does when a list lands: the list and its organization together. */
    function land(orgId: number, apps: AvailablePlugin[]): void {
        plugins.set(apps);
        loadedOrgId.set(orgId);
        TestBed.tick();
    }

    function newIdentifiers(service: SeenAppsService): string[] {
        return [...service.newIdentifiers()].sort();
    }

    beforeEach(() => {
        plugins = signal([]);
        loadedOrgId = signal(null);
        user = signal({ id: 7 } as GetMeResponse);
    });

    afterEach(() => {
        localStorage.clear();
        vi.restoreAllMocks();
    });

    it('takes the first list that lands as seen, silently', () => {
        const service = create();

        land(1, [ATLAS, WEATHER]);

        expect(newIdentifiers(service)).toEqual([]);
        expect(JSON.parse(localStorage.getItem('epicstaff.seenApps.7.1')!)).toEqual(['atlas', 'weather']);
    });

    it('seeds nothing before the list lands, so the empty list before it marks nothing', () => {
        create();

        expect(localStorage.length).toBe(0);
    });

    it('marks an app granted after the first list as new until an apps list is opened', () => {
        const service = create();
        land(1, [WEATHER]);

        land(1, [ATLAS, WEATHER]);
        expect(newIdentifiers(service)).toEqual(['atlas']);

        service.markSeen();
        expect(newIdentifiers(service)).toEqual([]);
    });

    it('marks an app new in an organization whose first list was empty', () => {
        const service = create();
        land(1, []);

        land(1, [WEATHER]);

        expect(newIdentifiers(service)).toEqual(['weather']);
    });

    it('remembers per organization', () => {
        const service = create();
        land(1, [WEATHER]);
        land(1, [ATLAS, WEATHER]);

        // An organization switch clears the list, then the new organization's lands.
        plugins.set([]);
        loadedOrgId.set(null);
        land(2, [ATLAS, CHART]);
        expect(newIdentifiers(service)).toEqual([]);

        land(1, [ATLAS, WEATHER]);
        expect(newIdentifiers(service)).toEqual(['atlas']);
    });

    it('remembers per user', () => {
        const service = create();
        land(1, [WEATHER]);
        land(1, [ATLAS, WEATHER]);

        user.set({ id: 8 } as GetMeResponse);
        TestBed.tick();

        expect(newIdentifiers(service)).toEqual([]);
        expect(JSON.parse(localStorage.getItem('epicstaff.seenApps.8.1')!)).toEqual(['atlas', 'weather']);
    });

    it('knows nothing without a signed-in user', () => {
        user.set(null);
        const service = create();

        land(1, [WEATHER]);

        expect(newIdentifiers(service)).toEqual([]);
        expect(localStorage.length).toBe(0);
    });

    it('starts over from a stored value it cannot read', () => {
        localStorage.setItem('epicstaff.seenApps.7.1', '{not json');
        const service = create();

        land(1, [WEATHER]);

        expect(newIdentifiers(service)).toEqual([]);
        expect(JSON.parse(localStorage.getItem('epicstaff.seenApps.7.1')!)).toEqual(['weather']);
    });

    it('shows nothing as new and never fails when the storage is blocked', () => {
        vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
            throw new Error('blocked');
        });
        vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
            throw new Error('blocked');
        });
        const service = create();

        land(1, [WEATHER]);
        land(1, [ATLAS, WEATHER]);

        expect(newIdentifiers(service)).toEqual([]);
        expect(() => service.markSeen()).not.toThrow();
    });
});
