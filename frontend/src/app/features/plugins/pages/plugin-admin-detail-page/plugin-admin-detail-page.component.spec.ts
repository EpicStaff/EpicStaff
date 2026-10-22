import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { provideRouter, Router } from '@angular/router';
import { ConfirmationDialogData, ConfirmationDialogService, SelectComponent } from '@shared/components';
import { GetOrganizationResponse } from '@shared/models';
import { Observable, of, throwError } from 'rxjs';
import type { Mock } from 'vitest';

import { ApiGetRequest } from '../../../../core/models/api-request.model';
import { ToastService } from '../../../../services/notifications';
import { AdminOrganizationsService } from '../../../role-base-access/services/admin/organizations.service';
import { PluginAdminActivityComponent } from '../../components/plugin-admin-activity/plugin-admin-activity.component';
import { PluginDevelopmentPanelComponent } from '../../components/plugin-development-panel/plugin-development-panel.component';
import { PluginPurgeTarget } from '../../components/plugin-purge-dialog/plugin-purge-dialog.component';
import { PluginUninstallDialogData } from '../../components/plugin-uninstall-dialog/plugin-uninstall-dialog.component';
import { PluginActivityEvent, PluginAdminActivityQuery } from '../../models/plugin-activity.model';
import { PluginDetail } from '../../models/plugin-admin.model';
import { PluginRuntimeResponse } from '../../models/plugin-backend.model';
import { PluginDevelopment, PluginDevelopmentUpdate } from '../../models/plugin-development.model';
import { PluginActivityApiService } from '../../services/plugin-activity-api.service';
import { PluginDialogsService } from '../../services/plugin-dialogs.service';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import {
    buildFailedMigrationUpgrade,
    buildMigratingUpgrade,
    buildPackageReview,
    buildPluginActivityEvent,
    buildPluginBackupList,
    buildPluginDetail,
    buildPluginDevelopment,
    buildPluginDevelopmentTarget,
    buildPluginPurgeProgress,
    buildPluginRestore,
    buildPluginRuntime,
    buildPluginRuntimeDatabase,
    buildPluginUpgrade,
} from '../../testing/plugin-fixtures';
import { PLUGIN_ERROR_MESSAGES } from '../../utils/plugin-error-message.util';
import { PLUGIN_DETAIL_POLL_MS, PluginAdminDetailPageComponent } from './plugin-admin-detail-page.component';

class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

function withBackend(hasBackend: boolean): PluginDetail {
    const review = buildPackageReview({ review_state: 'approved' });
    return buildPluginDetail({
        current_package: { ...review, contents: { ...review.contents, has_backend: hasBackend } },
    });
}

function organization(id: number, name: string): GetOrganizationResponse {
    return { id, name } as GetOrganizationResponse;
}

describe('PluginAdminDetailPageComponent tabs', () => {
    let fixture: ComponentFixture<PluginAdminDetailPageComponent>;
    let listPluginActivity: Mock<
        (identifier: string, query: PluginAdminActivityQuery) => Observable<ApiGetRequest<PluginActivityEvent>>
    >;

    function render(plugin: PluginDetail): void {
        TestBed.configureTestingModule({
            imports: [PluginAdminDetailPageComponent],
            providers: [
                provideRouter([]),
                { provide: PluginsAdminStorageService, useValue: { getPlugin: () => of(plugin) } },
                { provide: PluginDialogsService, useValue: {} },
                { provide: PluginActivityApiService, useValue: { listPluginActivity } },
                {
                    provide: AdminOrganizationsService,
                    useValue: {
                        list: () =>
                            of({
                                count: 2,
                                next: null,
                                previous: null,
                                results: [organization(4, 'Bravo'), organization(3, 'Acme')],
                            }),
                    },
                },
            ],
        });
        fixture = TestBed.createComponent(PluginAdminDetailPageComponent);
        fixture.componentRef.setInput('identifier', plugin.identifier);
        refresh();
    }

    function refresh(): void {
        fixture.detectChanges();
        TestBed.tick();
        fixture.detectChanges();
    }

    function tabs(): HTMLElement[] {
        return Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('.detail__tabs app-tab-button'));
    }

    function tabLabels(): string[] {
        return tabs().map((tab) => tab.textContent?.trim() ?? '');
    }

    function openTab(label: string): void {
        tabs()
            .find((tab) => tab.textContent?.trim() === label)!
            .querySelector('button')!
            .click();
        refresh();
    }

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        listPluginActivity = vi.fn(() =>
            of({ count: 1, next: null, previous: null, results: [buildPluginActivityEvent()] })
        );
    });

    afterEach(() => vi.unstubAllGlobals());

    it('offers Settings, Limits and Runtime for a plugin whose current package has a backend', () => {
        render(withBackend(true));

        expect(tabLabels()).toEqual(['Overview', 'Organizations', 'Settings', 'Limits', 'Runtime', 'Activity']);
    });

    it('offers Overview, Organizations and Activity for a plugin without a backend', () => {
        render(withBackend(false));

        expect(tabLabels()).toEqual(['Overview', 'Organizations', 'Activity']);
    });

    it("shows the plugin's activity in every organization, with an organization column and filter", () => {
        render(withBackend(false));

        openTab('Activity');

        expect(listPluginActivity).toHaveBeenCalledWith('weather', { page: 1, pageSize: 50, organizationId: null });
        const element = fixture.nativeElement as HTMLElement;
        expect(element.querySelector('app-plugin-admin-activity .table-header')?.textContent).toContain('Organization');
        expect(element.querySelector('app-plugin-admin-activity .table-body')?.textContent).toContain(
            'Weather (plugin) on behalf of ada@example.com'
        );

        const filter = fixture.debugElement
            .query(By.directive(PluginAdminActivityComponent))
            .query(By.directive(SelectComponent)).componentInstance as SelectComponent;
        expect(filter.items().map((item) => item.name)).toEqual(['All organizations', 'Acme', 'Bravo']);

        filter.changed.emit(3);
        refresh();

        expect(listPluginActivity).toHaveBeenLastCalledWith('weather', { page: 1, pageSize: 50, organizationId: 3 });
    });
});

const UNINSTALLED = buildPluginDetail({
    state: 'uninstalling',
    allowed_actions: ['reinstall', 'purge'],
    uninstall_requested_at: '2026-10-21T09:00:00Z',
    purge_after: '2026-11-20T09:00:00Z',
});
const DELETING = buildPluginDetail({
    state: 'purging',
    allowed_actions: [],
    uninstall_requested_at: '2026-10-21T09:00:00Z',
    purge_after: '2026-10-21T09:00:00Z',
    purge_started_at: '2026-10-21T09:00:00Z',
    purge_progress: buildPluginPurgeProgress(),
});

function notFound(): HttpErrorResponse {
    return new HttpErrorResponse({
        status: 404,
        error: { status_code: 404, code: 'plugin_not_found', message: 'Not found.' },
    });
}

describe('PluginAdminDetailPageComponent uninstall, reinstall and deletion', () => {
    let fixture: ComponentFixture<PluginAdminDetailPageComponent>;
    let element: HTMLElement;
    let storage: {
        getPlugin: Mock<(identifier: string) => Observable<PluginDetail>>;
        reinstallPlugin: Mock<(identifier: string) => Observable<PluginDetail>>;
        retryRemoval: Mock<(identifier: string) => Observable<PluginDetail>>;
        forgetPlugin: Mock<(identifier: string) => void>;
    };
    let dialogs: {
        openUninstall: Mock<(data: PluginUninstallDialogData) => Observable<PluginDetail | undefined>>;
        openPluginPurge: Mock<(data: PluginPurgeTarget) => Observable<PluginDetail | undefined>>;
    };
    let confirm: Mock<(options: ConfirmationDialogData) => Observable<boolean | 'close'>>;
    let toast: { success: Mock; warning: Mock; error: Mock };
    let navigateByUrl: Mock;

    function render(plugin: PluginDetail): void {
        storage.getPlugin.mockReturnValue(of(plugin));
        fixture = TestBed.createComponent(PluginAdminDetailPageComponent);
        element = fixture.nativeElement as HTMLElement;
        fixture.componentRef.setInput('identifier', plugin.identifier);
        refresh();
    }

    function refresh(): void {
        fixture.detectChanges();
        TestBed.tick();
        fixture.detectChanges();
    }

    function poll(): void {
        vi.advanceTimersByTime(PLUGIN_DETAIL_POLL_MS);
        refresh();
    }

    function text(node: Element | null | undefined): string {
        return node?.textContent?.replace(/\s+/g, ' ').trim() ?? '';
    }

    function headerButtons(): string[] {
        return Array.from(element.querySelectorAll('.detail__actions button')).map((button) => text(button));
    }

    function headerButton(label: string): HTMLButtonElement {
        return Array.from(element.querySelectorAll<HTMLButtonElement>('.detail__actions button')).find(
            (button) => text(button) === label
        )!;
    }

    function banner(): string {
        return text(element.querySelector('app-plugin-lifecycle-banner .banner'));
    }

    beforeEach(() => {
        vi.useFakeTimers();
        vi.setSystemTime(new Date('2026-10-21T12:00:00'));
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        storage = {
            getPlugin: vi.fn(),
            reinstallPlugin: vi.fn(() => of(buildPluginDetail({ state: 'provisioning' }))),
            retryRemoval: vi.fn(() => of(DELETING)),
            forgetPlugin: vi.fn(),
        };
        dialogs = {
            openUninstall: vi.fn(() => of<PluginDetail | undefined>(undefined)),
            openPluginPurge: vi.fn(() => of<PluginDetail | undefined>(undefined)),
        };
        confirm = vi.fn(() => of<boolean | 'close'>(true));
        toast = { success: vi.fn(), warning: vi.fn(), error: vi.fn() };
        TestBed.configureTestingModule({
            imports: [PluginAdminDetailPageComponent],
            providers: [
                provideRouter([]),
                { provide: PluginsAdminStorageService, useValue: storage },
                { provide: PluginDialogsService, useValue: dialogs },
                { provide: ConfirmationDialogService, useValue: { confirm } },
                { provide: ToastService, useValue: toast },
            ],
        });
        navigateByUrl = vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true) as unknown as Mock;
    });

    afterEach(() => {
        vi.useRealTimers();
        vi.unstubAllGlobals();
    });

    it("offers exactly the actions the plugin allows, in the server's order", () => {
        render(buildPluginDetail());
        expect(headerButtons()).toEqual(['Uninstall…', 'Delete permanently…']);
        fixture.destroy();

        render(UNINSTALLED);
        expect(headerButtons()).toEqual(['Reinstall', 'Delete permanently…']);
        fixture.destroy();

        render({ ...DELETING, allowed_actions: ['retry_removal'] });
        expect(headerButtons()).toEqual(['Retry removal']);
        fixture.destroy();

        render(buildPluginDetail({ state: 'uploaded', allowed_actions: [] }));
        expect(element.querySelector('.detail__actions')).toBeNull();
    });

    it('leaves out an action this page does not know', () => {
        render(buildPluginDetail({ allowed_actions: ['transfer', 'uninstall'] } as unknown as Partial<PluginDetail>));

        expect(headerButtons()).toEqual(['Uninstall…']);
    });

    it('says since when an uninstalled plugin is uninstalled, and until when its data is kept', () => {
        render(UNINSTALLED);

        expect(text(element.querySelector('.detail__badges'))).toContain('Uninstalled');
        expect(banner()).toBe('Uninstalled on Oct 21, 2026. Its data is kept until Nov 20, 2026 (in 30 days).');
    });

    it('shows no banner for a plugin that is neither uninstalled nor being deleted', () => {
        render(buildPluginDetail());

        expect(element.querySelector('app-plugin-lifecycle-banner .banner')).toBeNull();
    });

    it('shows how far the deletion has come, the node included only for a plugin with a backend', () => {
        render(DELETING);
        expect(text(element.querySelector('.detail__badges'))).toContain('Deleting');
        expect(banner()).toBe(
            'Deleting Weather: 1 organization left · 1 data removal waiting · 0 failed · Plugin node: Waiting'
        );
        fixture.destroy();

        render({
            ...DELETING,
            purge_progress: buildPluginPurgeProgress({
                grants_left: 0,
                data_removals_waiting: 0,
                data_removals_failed: 2,
                node: 'failed',
                node_error: 'conflict: the database belongs to another installation',
            }),
        });
        expect(banner()).toBe(
            'Deleting Weather: 0 organizations left · 0 data removals waiting · 2 failed · Plugin node: Failed: ' +
                'conflict: the database belongs to another installation'
        );
        fixture.destroy();

        render({ ...DELETING, purge_progress: buildPluginPurgeProgress({ grants_left: 2, node: 'not_needed' }) });
        expect(banner()).toBe('Deleting Weather: 2 organizations left · 1 data removal waiting · 0 failed');
    });

    it('asks again every few seconds while the plugin is being deleted, then says it was deleted and leaves', () => {
        render(DELETING);
        expect(storage.getPlugin).toHaveBeenCalledTimes(1);

        storage.getPlugin.mockReturnValue(
            of({ ...DELETING, purge_progress: buildPluginPurgeProgress({ grants_left: 0, node: 'removing' }) })
        );
        poll();
        expect(storage.getPlugin).toHaveBeenCalledTimes(2);
        expect(banner()).toContain('Plugin node: Removing');

        storage.getPlugin.mockReturnValue(throwError(() => notFound()));
        poll();

        expect(toast.success).toHaveBeenCalledWith('Weather was deleted.');
        expect(storage.forgetPlugin).toHaveBeenCalledWith('weather');
        expect(navigateByUrl).toHaveBeenCalledWith('/workspace/plugins');

        poll();
        expect(storage.getPlugin).toHaveBeenCalledTimes(3);
    });

    it('keeps the plugin shown and keeps asking after a failed poll, and says the progress may be old', () => {
        render(DELETING);
        storage.getPlugin.mockReturnValue(throwError(() => new HttpErrorResponse({ status: 502, error: null })));
        poll();

        expect(banner()).toContain('Deleting Weather');
        expect(element.querySelector('app-fetch-error-state')).toBeNull();
        expect(text(element.querySelector('.banner--stale'))).toBe(
            "Couldn't refresh: Couldn't load the plugin. Showing the last known progress."
        );

        storage.getPlugin.mockReturnValue(of(DELETING));
        poll();
        expect(storage.getPlugin).toHaveBeenCalledTimes(3);
        expect(element.querySelector('.banner--stale')).toBeNull();
    });

    it('says a plugin on screen that the server no longer knows was deleted, whatever its state', () => {
        render(buildPluginDetail({ open_upgrade: buildPluginUpgrade() }));
        storage.getPlugin.mockReturnValue(throwError(() => notFound()));

        poll();

        expect(toast.success).toHaveBeenCalledWith('Weather was deleted.');
        expect(navigateByUrl).toHaveBeenCalledWith('/workspace/plugins');
    });

    it('never polls a plugin that is not being deleted', () => {
        render(UNINSTALLED);
        poll();
        poll();

        expect(storage.getPlugin).toHaveBeenCalledTimes(1);
    });

    it('says a plugin it cannot find is not found, unless it was being deleted', () => {
        storage.getPlugin.mockReturnValue(throwError(() => notFound()));
        fixture = TestBed.createComponent(PluginAdminDetailPageComponent);
        element = fixture.nativeElement as HTMLElement;
        fixture.componentRef.setInput('identifier', 'weather');
        refresh();

        expect(element.querySelector('app-fetch-error-state')?.textContent).toContain('Plugin not found');
        expect(navigateByUrl).not.toHaveBeenCalled();
        expect(toast.success).not.toHaveBeenCalled();
    });

    it('opens the uninstall preview, and once uninstalled shows the plugin and says so', () => {
        dialogs.openUninstall.mockReturnValue(of(UNINSTALLED));
        render(buildPluginDetail());
        storage.getPlugin.mockReturnValue(of(UNINSTALLED));

        headerButton('Uninstall…').click();
        refresh();

        expect(dialogs.openUninstall).toHaveBeenCalledWith({ identifier: 'weather', pluginName: 'Weather' });
        expect(toast.success).toHaveBeenCalledWith('Weather is uninstalled.');
        expect(headerButtons()).toEqual(['Reinstall', 'Delete permanently…']);
        expect(banner()).toContain('Its data is kept until Nov 20, 2026');
    });

    it('reinstalls only after confirmation, then shows the plugin as it is now', () => {
        render(UNINSTALLED);
        storage.getPlugin.mockReturnValue(of(buildPluginDetail({ state: 'provisioning' })));

        confirm.mockReturnValueOnce(of(false));
        headerButton('Reinstall').click();
        expect(storage.reinstallPlugin).not.toHaveBeenCalled();

        headerButton('Reinstall').click();
        refresh();

        expect(confirm).toHaveBeenLastCalledWith(
            expect.objectContaining({
                message: 'Reinstall Weather? Organizations it was uninstalled from get it back, with their data.',
                confirmText: 'Reinstall',
            })
        );
        expect(storage.reinstallPlugin).toHaveBeenCalledWith('weather');
        expect(toast.success).toHaveBeenCalledWith('Weather is reinstalled.');
        expect(text(element.querySelector('.detail__badges'))).toContain('Provisioning');
        expect(element.querySelector('app-plugin-lifecycle-banner .banner')).toBeNull();
    });

    it('says why a reinstall was refused, and shows the plugin as it is now', () => {
        storage.reinstallPlugin.mockReturnValue(
            throwError(
                () =>
                    new HttpErrorResponse({
                        status: 409,
                        error: { status_code: 409, code: 'plugin_not_uninstalling', message: 'Refused.' },
                    })
            )
        );
        render(UNINSTALLED);

        headerButton('Reinstall').click();
        refresh();

        expect(toast.error).toHaveBeenCalledWith(PLUGIN_ERROR_MESSAGES.plugin_not_uninstalling);
        expect(storage.getPlugin).toHaveBeenCalledTimes(2);
    });

    it('opens the deletion preview, and once deleting starts polling', () => {
        dialogs.openPluginPurge.mockReturnValue(of(DELETING));
        render(UNINSTALLED);
        storage.getPlugin.mockReturnValue(of(DELETING));

        headerButton('Delete permanently…').click();
        refresh();

        expect(dialogs.openPluginPurge).toHaveBeenCalledWith({ identifier: 'weather', pluginName: 'Weather' });
        expect(toast.success).toHaveBeenCalledWith('Deleting Weather.');
        expect(banner()).toContain('Deleting Weather:');
        const loads = storage.getPlugin.mock.calls.length;

        poll();
        expect(storage.getPlugin).toHaveBeenCalledTimes(loads + 1);
    });

    it('asks the node again to remove the plugin on Retry removal', () => {
        render({ ...DELETING, allowed_actions: ['retry_removal'] });

        headerButton('Retry removal').click();
        refresh();

        expect(confirm).not.toHaveBeenCalled();
        expect(storage.retryRemoval).toHaveBeenCalledWith('weather');
        expect(toast.success).toHaveBeenCalledWith('The plugin node tries again to remove Weather.');
    });
});

describe('PluginAdminDetailPageComponent upgrades', () => {
    let fixture: ComponentFixture<PluginAdminDetailPageComponent>;
    let element: HTMLElement;
    let storage: {
        getPlugin: Mock<(identifier: string) => Observable<PluginDetail>>;
        cancelUpgrade: Mock<(identifier: string) => Observable<PluginDetail>>;
        retryUpgrade: Mock<(identifier: string) => Observable<PluginDetail>>;
        getRuntime: Mock;
        listBackups: Mock;
    };
    let openReview: Mock;
    let confirm: Mock<(options: ConfirmationDialogData) => Observable<boolean | 'close'>>;
    let toast: { success: Mock; warning: Mock; error: Mock };

    const PREPARING = buildPluginDetail({
        current_version: '0.6.0',
        allowed_actions: ['cancel_upgrade', 'purge'],
        open_upgrade: buildPluginUpgrade(),
        upgrade: { to_version: '0.7.0', stage: 'preparing', failed: false },
    });
    const OFFLINE = buildPluginDetail({
        state: 'maintenance',
        current_version: '0.6.0',
        allowed_actions: ['purge'],
        open_upgrade: buildMigratingUpgrade(),
        upgrade: { to_version: '0.7.0', stage: 'migrating', failed: false },
    });
    const FAILED = buildPluginDetail({
        state: 'maintenance',
        current_version: '0.7.0',
        allowed_actions: ['retry_upgrade', 'restore_backup', 'purge'],
        open_upgrade: buildFailedMigrationUpgrade(),
        upgrade: { to_version: '0.7.1', stage: 'migrating', failed: true },
        needs_attention: true,
    });

    function withBackendPackage(plugin: PluginDetail): PluginDetail {
        const review = buildPackageReview({ review_state: 'approved' });
        return {
            ...plugin,
            current_package: { ...review, contents: { ...review.contents, has_backend: true, has_database: true } },
        };
    }

    function render(plugin: PluginDetail): void {
        storage.getPlugin.mockReturnValue(of(plugin));
        fixture = TestBed.createComponent(PluginAdminDetailPageComponent);
        element = fixture.nativeElement as HTMLElement;
        fixture.componentRef.setInput('identifier', plugin.identifier);
        refresh();
    }

    function refresh(): void {
        fixture.detectChanges();
        TestBed.tick();
        fixture.detectChanges();
    }

    function poll(): void {
        vi.advanceTimersByTime(PLUGIN_DETAIL_POLL_MS);
        refresh();
    }

    function text(node: Element | null | undefined): string {
        return node?.textContent?.replace(/\s+/g, ' ').trim() ?? '';
    }

    function bannerLines(): string[] {
        return Array.from(element.querySelectorAll('app-plugin-lifecycle-banner .banner')).map((line) => text(line));
    }

    function headerButtons(): string[] {
        return Array.from(element.querySelectorAll('.detail__actions button')).map((button) => text(button));
    }

    function headerButton(label: string): HTMLButtonElement {
        return Array.from(element.querySelectorAll<HTMLButtonElement>('.detail__actions button')).find(
            (button) => text(button) === label
        )!;
    }

    beforeEach(() => {
        vi.useFakeTimers();
        vi.setSystemTime(new Date('2026-10-21T10:04:00Z'));
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        storage = {
            getPlugin: vi.fn(),
            cancelUpgrade: vi.fn(() => of(buildPluginDetail({ state: 'provisioning' }))),
            retryUpgrade: vi.fn(() => of(PREPARING)),
            getRuntime: vi.fn(() =>
                of(
                    buildPluginRuntime({
                        database: buildPluginRuntimeDatabase(),
                        upgrade: { from_version: '0.7.0', to_version: '0.7.1' },
                    })
                )
            ),
            listBackups: vi.fn(() => of(buildPluginBackupList())),
        };
        openReview = vi.fn(() => of(undefined));
        confirm = vi.fn(() => of<boolean | 'close'>(true));
        toast = { success: vi.fn(), warning: vi.fn(), error: vi.fn() };
        TestBed.configureTestingModule({
            imports: [PluginAdminDetailPageComponent],
            providers: [
                provideRouter([]),
                { provide: PluginsAdminStorageService, useValue: storage },
                { provide: PluginDialogsService, useValue: { openReview } },
                { provide: ConfirmationDialogService, useValue: { confirm } },
                { provide: ToastService, useValue: toast },
            ],
        });
        vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);
    });

    afterEach(() => {
        vi.useRealTimers();
        vi.unstubAllGlobals();
    });

    it('says what is prepared while the plugin keeps running, with the node’s step', () => {
        render(PREPARING);

        expect(bannerLines()).toEqual(['Preparing 0.7.0 — Weather keeps running (Downloading the package)']);
        expect(headerButtons()).toEqual(['Cancel upgrade', 'Delete permanently…']);
    });

    it('says the plugin is offline, with the step and for how long', () => {
        render(OFFLINE);

        expect(bannerLines()).toEqual([
            'Upgrading to 0.7.0 — Weather is offline (Running migrations · offline for 3 min)',
        ]);
        expect(text(element.querySelector('.detail__badges'))).toContain('Maintenance');
    });

    it('keeps the time offline out of what a screen reader hears, as it changes every minute', () => {
        render(OFFLINE);

        const detail = element.querySelector('app-plugin-lifecycle-banner .banner__detail')!;
        const unannounced = Array.from(detail.querySelectorAll('[aria-hidden="true"]')).map((part) => text(part));
        expect(unannounced).toEqual(['· offline for 3 min']);
        expect(detail.closest('[aria-live]')).not.toBeNull();
        const heard = Array.from(detail.childNodes)
            .filter((node) => !(node instanceof Element && node.getAttribute('aria-hidden') === 'true'))
            .map((node) => node.textContent)
            .join('');
        expect(heard).toBe('(Running migrations)');
    });

    it('says an upgrade that adds a backend keeps the plugin running', () => {
        render(
            buildPluginDetail({
                open_upgrade: buildPluginUpgrade({ stage: 'migrating', step: 'migrate', adds_backend: true }),
            })
        );

        expect(bannerLines()).toEqual(['Upgrading to 0.7.0 — Weather keeps running (Running migrations)']);
        expect(element.textContent).toContain('Runtime');
    });

    it('says while doing what an upgrade failed, why, and that the database already holds its changes', () => {
        render(FAILED);

        expect(bannerLines()).toEqual([
            'The upgrade to 0.7.1 failed while running migrations: 005_broken.sql line 1: [22012] division by zero',
            'The database already holds changes of 0.7.1. Restore the backup to go back.',
        ]);
        expect(headerButtons()).toEqual(['Retry', 'Restore backup…', 'Delete permanently…']);
    });

    it('names the stage when the node reported no step, and leaves out the database line when it is unchanged', () => {
        render({
            ...FAILED,
            open_upgrade: buildFailedMigrationUpgrade({ step: null, database_changed: false, last_error: null }),
        });

        expect(bannerLines()).toEqual(['The upgrade to 0.7.1 failed while running migrations: no reason was given']);
    });

    it('shows a restore under way, then the database restored, as the latest news', () => {
        render({ ...FAILED, open_upgrade: buildFailedMigrationUpgrade({ restore: buildPluginRestore() }) });
        expect(bannerLines()).toContain(
            'Restoring the database from the backup taken before the upgrade to 0.7.1 (Restoring the backup)'
        );
        fixture.destroy();

        render({
            ...FAILED,
            allowed_actions: ['cancel_upgrade', 'retry_upgrade', 'restore_backup', 'purge'],
            open_upgrade: buildFailedMigrationUpgrade({
                database_changed: false,
                last_error: 'Database restored from x.dump. Retry, upload a newer version, or cancel the upgrade.',
                restore: buildPluginRestore({ state: 'succeeded', finished_at: '2026-10-21T11:06:00Z' }),
            }),
        });
        expect(bannerLines()).toEqual([
            'The upgrade to 0.7.1 is stopped.',
            'Database restored from the backup taken before the upgrade to 0.7.1',
        ]);
        expect(headerButtons()).toContain('Cancel upgrade');
    });

    it("names a restore's backup by its file name when the server no longer knows why it was taken", () => {
        render({
            ...FAILED,
            open_upgrade: buildFailedMigrationUpgrade({
                restore: buildPluginRestore({ backup: { id: null, file_name: 'x.dump', reason: null } }),
            }),
        });

        expect(bannerLines()).toContain('Restoring the database from the backup x.dump (Restoring the backup)');
    });

    it('says a failed restore, and how to undo it once the database was touched', () => {
        render({
            ...FAILED,
            open_upgrade: buildFailedMigrationUpgrade({
                restore: buildPluginRestore({
                    state: 'failed',
                    step: 'restore',
                    pre_restore_backup_id: 63,
                    last_error: 'pg_restore: error: could not execute query',
                    finished_at: '2026-10-21T11:06:00Z',
                }),
            }),
        });

        expect(bannerLines().at(-1)).toBe(
            'The restore failed while restoring the backup: pg_restore: error: could not execute query. ' +
                'Restore the backup taken before the restore to undo it.'
        );
    });

    it('treats a restore from before the latest failure as history', () => {
        render({
            ...FAILED,
            open_upgrade: buildFailedMigrationUpgrade({
                failed_at: '2026-10-21T11:20:00Z',
                restore: buildPluginRestore({ state: 'succeeded', finished_at: '2026-10-21T11:06:00Z' }),
            }),
        });

        expect(bannerLines()).toHaveLength(2);
        expect(bannerLines()[0]).toContain('failed while running migrations');
    });

    it('counts the organizations still upgrading once the upgrade is done, and polls until none is', () => {
        render(buildPluginDetail({ current_version: '0.7.0', upgrade_hooks: { upgrading: 1, upgrade_failed: 1 } }));
        expect(bannerLines()).toEqual(['Organizations upgrading: 1 · failed: 1']);

        storage.getPlugin.mockReturnValue(
            of(buildPluginDetail({ current_version: '0.7.0', upgrade_hooks: { upgrading: 0, upgrade_failed: 1 } }))
        );
        poll();
        poll();

        expect(storage.getPlugin).toHaveBeenCalledTimes(2);
        expect(bannerLines()).toEqual(['Organizations upgrading: 0 · failed: 1']);
    });

    it('polls while an upgrade is open and stops once it is done', () => {
        render(PREPARING);
        storage.getPlugin.mockReturnValue(of(OFFLINE));
        poll();
        expect(bannerLines()[0]).toContain('Weather is offline');

        storage.getPlugin.mockReturnValue(of(buildPluginDetail({ current_version: '0.7.0' })));
        poll();
        poll();

        expect(storage.getPlugin).toHaveBeenCalledTimes(3);
        expect(element.querySelector('app-plugin-lifecycle-banner .banner')).toBeNull();
    });

    it('opens the pending package’s review from "Upgrade to <version>…", and polls the upgrade it started', () => {
        const pending = buildPluginDetail({
            current_version: '0.6.0',
            allowed_actions: ['uninstall', 'upgrade', 'purge'],
            pending_package: { id: 12, version: '0.7.0', trust: 'trusted' },
        });
        openReview.mockReturnValue(of({ kind: 'approved', plugin: PREPARING }));
        render(pending);
        storage.getPlugin.mockReturnValue(of(PREPARING));

        expect(headerButtons()).toEqual(['Uninstall…', 'Upgrade to 0.7.0…', 'Delete permanently…']);
        headerButton('Upgrade to 0.7.0…').click();
        refresh();

        expect(openReview).toHaveBeenCalledWith({ packageId: 12 });
        expect(bannerLines()[0]).toContain('Preparing 0.7.0');
        const loads = storage.getPlugin.mock.calls.length;
        poll();
        expect(storage.getPlugin).toHaveBeenCalledTimes(loads + 1);
    });

    it('cancels the upgrade only after confirmation', () => {
        render(PREPARING);

        confirm.mockReturnValueOnce(of(false));
        headerButton('Cancel upgrade').click();
        expect(storage.cancelUpgrade).not.toHaveBeenCalled();

        headerButton('Cancel upgrade').click();
        refresh();

        expect(confirm).toHaveBeenLastCalledWith(
            expect.objectContaining({
                message: 'Cancel the upgrade of Weather to 0.7.0? 0.7.0 is deleted, and Weather goes on with 0.6.0.',
                confirmText: 'Cancel upgrade',
            })
        );
        expect(storage.cancelUpgrade).toHaveBeenCalledWith('weather');
        expect(toast.success).toHaveBeenCalledWith('The upgrade of Weather is cancelled.');
    });

    it('retries a failed upgrade at once, and says why when it is refused', () => {
        render(FAILED);

        headerButton('Retry').click();
        refresh();
        expect(confirm).not.toHaveBeenCalled();
        expect(storage.retryUpgrade).toHaveBeenCalledWith('weather');
        expect(toast.success).toHaveBeenCalledWith('The plugin node tries the upgrade of Weather again.');
        fixture.destroy();

        storage.retryUpgrade.mockReturnValue(
            throwError(
                () =>
                    new HttpErrorResponse({
                        status: 409,
                        error: { status_code: 409, code: 'upgrade_not_retryable', message: 'Refused.' },
                    })
            )
        );
        render(FAILED);
        headerButton('Retry').click();
        refresh();
        expect(toast.error).toHaveBeenCalledWith(PLUGIN_ERROR_MESSAGES.upgrade_not_retryable);
    });

    it('opens the Runtime tab with its backups on "Restore backup…"', () => {
        render(withBackendPackage(FAILED));

        headerButton('Restore backup…').click();
        refresh();
        // The runtime panel loads at its first timer tick.
        vi.advanceTimersByTime(0);
        refresh();

        expect(element.querySelector('app-plugin-runtime-panel')).not.toBeNull();
        expect(element.querySelector('app-plugin-backups')).not.toBeNull();
        expect(storage.listBackups).toHaveBeenCalledWith('weather');
        expect(text(element.querySelector('.runtime__upgrade'))).toBe('Running 0.7.0 → 0.7.1');
    });
});

describe('PluginAdminDetailPageComponent development', () => {
    let fixture: ComponentFixture<PluginAdminDetailPageComponent>;
    let element: HTMLElement;
    let storage: {
        getPlugin: Mock<(identifier: string) => Observable<PluginDetail>>;
        getDevelopment: Mock<(identifier: string) => Observable<PluginDevelopment>>;
        updateDevelopment: Mock<(identifier: string, update: PluginDevelopmentUpdate) => Observable<PluginDevelopment>>;
        getRuntime: Mock<(identifier: string) => Observable<PluginRuntimeResponse>>;
    };

    function inDevelopment(overrides: Partial<PluginDetail> = {}): PluginDetail {
        return { ...withBackend(true), development_mode: true, ...overrides };
    }

    function render(plugin: PluginDetail): void {
        storage.getPlugin.mockReturnValue(of(plugin));
        fixture = TestBed.createComponent(PluginAdminDetailPageComponent);
        element = fixture.nativeElement as HTMLElement;
        fixture.componentRef.setInput('identifier', plugin.identifier);
        refresh();
    }

    function refresh(): void {
        fixture.detectChanges();
        TestBed.tick();
        fixture.detectChanges();
    }

    function tabLabels(): string[] {
        return Array.from(element.querySelectorAll('.detail__tabs app-tab-button')).map(
            (tab) => tab.textContent?.trim() ?? ''
        );
    }

    function openTab(label: string): void {
        Array.from(element.querySelectorAll('.detail__tabs app-tab-button'))
            .find((tab) => tab.textContent?.trim() === label)!
            .querySelector('button')!
            .click();
        refresh();
    }

    beforeEach(() => {
        vi.useFakeTimers();
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        storage = {
            getPlugin: vi.fn(),
            getDevelopment: vi.fn(() => of(buildPluginDevelopment())),
            updateDevelopment: vi.fn(() => of(buildPluginDevelopment({ target: buildPluginDevelopmentTarget() }))),
            getRuntime: vi.fn(() => of(buildPluginRuntime())),
        };
        TestBed.configureTestingModule({
            imports: [PluginAdminDetailPageComponent],
            providers: [
                provideRouter([]),
                { provide: PluginsAdminStorageService, useValue: storage },
                { provide: PluginDialogsService, useValue: {} },
                { provide: ConfirmationDialogService, useValue: { confirm: vi.fn() } },
                { provide: ToastService, useValue: { success: vi.fn(), error: vi.fn() } },
            ],
        });
    });

    afterEach(() => {
        vi.useRealTimers();
        vi.unstubAllGlobals();
    });

    it('offers the Development tab only while the deployment runs in development mode', () => {
        render(inDevelopment());
        expect(tabLabels()).toEqual([
            'Overview',
            'Organizations',
            'Settings',
            'Limits',
            'Runtime',
            'Development',
            'Activity',
        ]);

        fixture.destroy();
        render({ ...withBackend(false), development_mode: true });
        expect(tabLabels()).toEqual(['Overview', 'Organizations', 'Development', 'Activity']);

        fixture.destroy();
        render(withBackend(true));
        expect(tabLabels()).not.toContain('Development');
    });

    it('shows the development panel, and reloads the plugin once its target changed', () => {
        render(inDevelopment());

        openTab('Development');

        expect(storage.getDevelopment).toHaveBeenCalledWith('weather');
        expect(element.querySelector('app-plugin-development-panel')).not.toBeNull();
        const loads = storage.getPlugin.mock.calls.length;

        fixture.debugElement.query(By.directive(PluginDevelopmentPanelComponent)).componentInstance.changed.emit();
        refresh();

        expect(storage.getPlugin.mock.calls.length).toBe(loads + 1);
    });

    it('goes back to Overview when development mode is turned off while the tab is open', () => {
        render(inDevelopment());
        openTab('Development');

        storage.getPlugin.mockReturnValue(of(withBackend(true)));
        fixture.debugElement.query(By.directive(PluginDevelopmentPanelComponent)).componentInstance.changed.emit();
        refresh();

        expect(tabLabels()).not.toContain('Development');
        expect(element.querySelector('app-plugin-development-panel')).toBeNull();
        expect(element.querySelector('.detail__overview')).not.toBeNull();
    });

    it("tells the Runtime tab the development backend's port", () => {
        render(inDevelopment({ development: { backend_port: 8001, spa_port: null } }));

        openTab('Runtime');
        vi.advanceTimersByTime(0);
        refresh();

        expect(element.querySelector('.runtime__development')?.textContent?.trim()).toBe(
            'Requests go to the development backend at host.docker.internal:8001; the installed process still runs hooks.'
        );
    });
});
