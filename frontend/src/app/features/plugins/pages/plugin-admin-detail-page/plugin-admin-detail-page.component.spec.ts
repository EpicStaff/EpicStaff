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
import { PluginPurgeTarget } from '../../components/plugin-purge-dialog/plugin-purge-dialog.component';
import { PluginUninstallDialogData } from '../../components/plugin-uninstall-dialog/plugin-uninstall-dialog.component';
import { PluginActivityEvent, PluginAdminActivityQuery } from '../../models/plugin-activity.model';
import { PluginDetail } from '../../models/plugin-admin.model';
import { PluginActivityApiService } from '../../services/plugin-activity-api.service';
import { PluginDialogsService } from '../../services/plugin-dialogs.service';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import {
    buildPackageReview,
    buildPluginActivityEvent,
    buildPluginDetail,
    buildPluginPurgeProgress,
} from '../../testing/plugin-fixtures';
import { PLUGIN_ERROR_MESSAGES } from '../../utils/plugin-error-message.util';
import { PLUGIN_DELETION_POLL_MS, PluginAdminDetailPageComponent } from './plugin-admin-detail-page.component';

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
        vi.advanceTimersByTime(PLUGIN_DELETION_POLL_MS);
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

    it('keeps the plugin shown and keeps asking after a failed poll', () => {
        render(DELETING);
        storage.getPlugin.mockReturnValue(throwError(() => new HttpErrorResponse({ status: 502, error: null })));
        poll();

        expect(banner()).toContain('Deleting Weather');
        expect(element.querySelector('app-fetch-error-state')).toBeNull();

        storage.getPlugin.mockReturnValue(of(DELETING));
        poll();
        expect(storage.getPlugin).toHaveBeenCalledTimes(3);
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
