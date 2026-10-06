import { HttpErrorResponse } from '@angular/common/http';
import { signal, WritableSignal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { ActionCode, ResourceCode } from '@shared/models';
import { AppStorageService } from '@shared/services';
import { of, Subject, throwError } from 'rxjs';

import { ActiveOrgService } from '../../../services/auth/active-org.service';
import { PermissionsService } from '../../../services/auth/permissions.service';
import { PluginDetail, PluginNavItem, PluginStatus, PluginSummary } from '../models/plugin.model';
import { providePluginsStorages } from '../plugins.providers';
import { PluginsApiService } from './plugins-api.service';
import { isNavPlugin, PLUGIN_POLL_INTERVAL_MS, PluginsStoreService } from './plugins-store.service';

function buildPlugin(id: number, status: PluginStatus, overrides: Partial<PluginSummary> = {}): PluginDetail {
    return {
        id,
        plugin_id: `plugin-${id}`,
        version: '0.1.0',
        name: `Plugin ${id}`,
        description: '',
        icon_data_url: '',
        format_version: 1,
        bridge_version: 1,
        has_ui: true,
        status,
        state: status === 'suspended' ? 'ready' : status,
        status_reason: '',
        suspended: status === 'suspended',
        suspended_at: null,
        access: [],
        secret_slots: [],
        contents: {},
        created_by: 1,
        created_at: '2026-10-06T21:30:00Z',
        updated_at: '2026-10-06T21:30:00Z',
        resources: [],
        ...overrides,
    };
}

function navItem(id: number): PluginNavItem {
    return { id, name: `Plugin ${id}`, icon_data_url: null };
}

describe('PluginsStoreService', () => {
    let store: PluginsStoreService;
    let api: {
        list: ReturnType<typeof vi.fn>;
        listNav: ReturnType<typeof vi.fn>;
        get: ReturnType<typeof vi.fn>;
        install: ReturnType<typeof vi.fn>;
        suspend: ReturnType<typeof vi.fn>;
        delete: ReturnType<typeof vi.fn>;
    };
    let activeOrgId: WritableSignal<number | null>;
    let canUsePlugins: WritableSignal<boolean>;

    beforeEach(() => {
        vi.useFakeTimers();
        api = {
            list: vi.fn(),
            listNav: vi.fn(() => of([])),
            get: vi.fn(),
            install: vi.fn(),
            suspend: vi.fn(),
            delete: vi.fn(),
        };
        activeOrgId = signal<number | null>(1);
        canUsePlugins = signal(true);
        const permissions = {
            can: (resource: ResourceCode, action: ActionCode) =>
                resource === ResourceCode.Plugins && action === ActionCode.Use && canUsePlugins(),
        };

        TestBed.configureTestingModule({
            providers: [
                { provide: PluginsApiService, useValue: api as unknown as PluginsApiService },
                { provide: ActiveOrgService, useValue: { activeOrgId } },
                { provide: PermissionsService, useValue: permissions },
                ...providePluginsStorages(),
            ],
        });
        store = TestBed.inject(PluginsStoreService);
        TestBed.tick();
        api.listNav.mockClear();
    });

    afterEach(() => {
        store.clear();
        vi.useRealTimers();
    });

    it('loads the list and marks it loaded', () => {
        api.list.mockReturnValue(of([buildPlugin(1, 'ready')]));

        store.refresh().subscribe();

        expect(store.plugins().map((plugin) => plugin.id)).toEqual([1]);
        expect(store.loaded()).toBe(true);
        expect(store.loading()).toBe(false);
    });

    describe('navPlugins', () => {
        it('loads the buttons from the nav endpoint for the active org', () => {
            api.listNav.mockReturnValue(of([navItem(1), navItem(2)]));

            activeOrgId.set(2);
            TestBed.tick();

            expect(api.listNav).toHaveBeenCalledTimes(1);
            expect(store.navPlugins().map((plugin) => plugin.id)).toEqual([1, 2]);
        });

        it('is empty without plugins:use and reloads when the permission arrives', () => {
            api.listNav.mockReturnValue(of([navItem(1)]));
            store.refreshNav();
            expect(store.navPlugins()).toHaveLength(1);

            canUsePlugins.set(false);
            TestBed.tick();
            expect(store.navPlugins()).toEqual([]);

            api.listNav.mockClear();
            canUsePlugins.set(true);
            TestBed.tick();
            expect(api.listNav).toHaveBeenCalledTimes(1);
            expect(store.navPlugins()).toHaveLength(1);
        });

        it('comes back after an org switch: cleared, then reloaded once permissions reload', () => {
            api.listNav.mockReturnValue(of([navItem(1)]));
            store.refreshNav();

            // ProfileService.switchOrg: clearAll() (permissions too), set the org, reload permissions.
            TestBed.inject(AppStorageService).clearAll();
            canUsePlugins.set(false);
            activeOrgId.set(3);
            TestBed.tick();
            expect(store.navPlugins()).toEqual([]);

            api.listNav.mockReturnValue(of([navItem(5)]));
            canUsePlugins.set(true);
            TestBed.tick();
            expect(store.navPlugins().map((plugin) => plugin.id)).toEqual([5]);
        });

        it("drops a nav response that arrives after the switch instead of showing the old org's buttons", () => {
            const response = new Subject<PluginNavItem[]>();
            api.listNav.mockReturnValue(response);
            store.refreshNav();

            store.clear();
            response.next([navItem(1)]);

            expect(store.navPlugins()).toEqual([]);
        });

        it('keeps the buttons when a reload fails', () => {
            api.listNav.mockReturnValue(of([navItem(1)]));
            store.refreshNav();

            api.listNav.mockReturnValue(throwError(() => new HttpErrorResponse({ status: 502 })));
            store.refreshNav();

            expect(store.navPlugins().map((plugin) => plugin.id)).toEqual([1]);
        });

        it('reloads when an action adds or removes a button, and not otherwise', () => {
            api.list.mockReturnValue(of([buildPlugin(1, 'ready'), buildPlugin(2, 'needs_attention')]));
            store.refresh().subscribe();
            expect(api.listNav).toHaveBeenCalledTimes(1);

            api.suspend.mockReturnValue(of(buildPlugin(2, 'suspended')));
            store.suspend(2).subscribe();
            expect(api.listNav).toHaveBeenCalledTimes(1);

            api.suspend.mockReturnValue(of(buildPlugin(1, 'suspended')));
            store.suspend(1).subscribe();
            expect(api.listNav).toHaveBeenCalledTimes(2);

            api.delete.mockReturnValue(of(undefined));
            store.delete(2).subscribe();
            expect(api.listNav).toHaveBeenCalledTimes(2);
        });

        it('reloads after installing a ready plugin with a page', () => {
            api.list.mockReturnValue(of([]));
            store.refresh().subscribe();
            api.install.mockReturnValue(of({ kind: 'done', plugin: buildPlugin(7, 'ready') }));

            store.install(new File(['zip'], 'plugin.zip'), {}).subscribe();

            expect(api.listNav).toHaveBeenCalledTimes(1);
        });

        it('treats only ready, unsuspended plugins with a page as having a button', () => {
            expect(isNavPlugin(buildPlugin(1, 'ready'))).toBe(true);
            expect(isNavPlugin(buildPlugin(2, 'ready', { has_ui: false }))).toBe(false);
            expect(isNavPlugin(buildPlugin(3, 'suspended'))).toBe(false);
            expect(isNavPlugin(buildPlugin(4, 'needs_attention'))).toBe(false);
            expect(isNavPlugin(buildPlugin(5, 'preparing'))).toBe(false);
            // Defensive: a suspended flag wins even if status were stale.
            expect(isNavPlugin(buildPlugin(6, 'ready', { suspended: true }))).toBe(false);
        });
    });

    describe('polling', () => {
        it('re-reads a preparing plugin every interval and stops once it is ready', () => {
            api.list.mockReturnValue(of([buildPlugin(1, 'preparing'), buildPlugin(2, 'ready')]));
            api.get.mockReturnValue(of(buildPlugin(1, 'preparing')));

            store.refresh().subscribe();
            expect(api.get).not.toHaveBeenCalled();

            vi.advanceTimersByTime(PLUGIN_POLL_INTERVAL_MS);
            expect(api.get).toHaveBeenCalledTimes(1);
            expect(api.get).toHaveBeenCalledWith(1);

            api.get.mockReturnValue(of(buildPlugin(1, 'ready')));
            vi.advanceTimersByTime(PLUGIN_POLL_INTERVAL_MS);
            expect(api.get).toHaveBeenCalledTimes(2);
            expect(store.plugins().find((plugin) => plugin.id === 1)?.status).toBe('ready');
            // Turning ready adds a button: the nav reloads (once for the list, once for the change).
            expect(api.listNav).toHaveBeenCalledTimes(2);

            vi.advanceTimersByTime(PLUGIN_POLL_INTERVAL_MS * 3);
            expect(api.get).toHaveBeenCalledTimes(2);
        });

        it('does not poll when nothing is preparing', () => {
            api.list.mockReturnValue(of([buildPlugin(1, 'ready'), buildPlugin(2, 'needs_attention')]));

            store.refresh().subscribe();
            vi.advanceTimersByTime(PLUGIN_POLL_INTERVAL_MS * 3);

            expect(api.get).not.toHaveBeenCalled();
        });

        it('starts polling when an install finishes with a preparing plugin', () => {
            api.list.mockReturnValue(of([]));
            store.refresh().subscribe();
            api.install.mockReturnValue(
                of({ kind: 'progress', percent: 100 }, { kind: 'done', plugin: buildPlugin(7, 'preparing') })
            );
            api.get.mockReturnValue(of(buildPlugin(7, 'ready')));

            store.install(new File(['zip'], 'plugin.zip'), {}).subscribe();
            expect(store.plugins().map((plugin) => plugin.id)).toEqual([7]);

            vi.advanceTimersByTime(PLUGIN_POLL_INTERVAL_MS);
            expect(api.get).toHaveBeenCalledWith(7);
            expect(store.plugins()[0].status).toBe('ready');
        });

        it.each([404, 403])('drops a plugin that answers %i while polling, and stops', (status) => {
            api.list.mockReturnValue(of([buildPlugin(1, 'preparing')]));
            api.get.mockReturnValue(throwError(() => new HttpErrorResponse({ status })));

            store.refresh().subscribe();
            vi.advanceTimersByTime(PLUGIN_POLL_INTERVAL_MS * 3);

            expect(store.plugins()).toEqual([]);
            expect(api.get).toHaveBeenCalledTimes(1);
        });

        it('keeps polling after a transient error', () => {
            api.list.mockReturnValue(of([buildPlugin(1, 'preparing')]));
            api.get.mockReturnValue(throwError(() => new HttpErrorResponse({ status: 502 })));

            store.refresh().subscribe();
            vi.advanceTimersByTime(PLUGIN_POLL_INTERVAL_MS * 2);

            expect(api.get).toHaveBeenCalledTimes(2);
            expect(store.plugins().map((plugin) => plugin.id)).toEqual([1]);
        });

        it('stops on clear()', () => {
            api.list.mockReturnValue(of([buildPlugin(1, 'preparing')]));
            api.get.mockReturnValue(of(buildPlugin(1, 'preparing')));
            store.refresh().subscribe();

            store.clear();
            vi.advanceTimersByTime(PLUGIN_POLL_INTERVAL_MS * 3);

            expect(api.get).not.toHaveBeenCalled();
        });
    });

    describe('org switch', () => {
        it('is cleared by AppStorageService.clearAll (registered through providePluginsStorages)', () => {
            api.list.mockReturnValue(of([buildPlugin(1, 'preparing')]));
            api.get.mockReturnValue(of(buildPlugin(1, 'preparing')));
            store.refresh().subscribe();

            TestBed.inject(AppStorageService).clearAll();

            expect(store.plugins()).toEqual([]);
            expect(store.navPlugins()).toEqual([]);
            expect(store.loaded()).toBe(false);
            vi.advanceTimersByTime(PLUGIN_POLL_INTERVAL_MS * 2);
            expect(api.get).not.toHaveBeenCalled();
        });

        it("drops a list response that arrives after the switch instead of showing the old org's plugins", () => {
            const response = new Subject<PluginSummary[]>();
            api.list.mockReturnValue(response);
            store.refresh().subscribe();

            store.clear();
            response.next([buildPlugin(1, 'ready')]);
            response.complete();

            expect(store.plugins()).toEqual([]);
            expect(store.loaded()).toBe(false);
        });

        it('drops an action result that arrives after the switch', () => {
            api.list.mockReturnValue(of([]));
            store.refresh().subscribe();
            const response = new Subject<PluginDetail>();
            api.suspend.mockReturnValue(response);
            store.suspend(1).subscribe();

            store.clear();
            response.next(buildPlugin(1, 'suspended'));

            expect(store.plugins()).toEqual([]);
        });
    });

    it('replaces a plugin in place after an action and removes it after delete', () => {
        api.list.mockReturnValue(of([buildPlugin(1, 'ready'), buildPlugin(2, 'ready')]));
        store.refresh().subscribe();

        api.suspend.mockReturnValue(of(buildPlugin(1, 'suspended')));
        store.suspend(1).subscribe();
        expect(store.plugins().map((plugin) => plugin.status)).toEqual(['suspended', 'ready']);

        api.delete.mockReturnValue(of(undefined));
        store.delete(2).subscribe();
        expect(store.plugins().map((plugin) => plugin.id)).toEqual([1]);
    });
});
