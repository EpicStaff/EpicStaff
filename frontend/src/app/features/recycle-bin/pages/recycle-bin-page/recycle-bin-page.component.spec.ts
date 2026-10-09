import { Component, input, signal, WritableSignal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router, Routes } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { ConfirmationDialogData, ConfirmationDialogService, ConfirmationResult } from '@shared/components';
import { ActionCode, ResourceCode } from '@shared/models';
import { Observable, of } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { RecycleBinSettingsStorageService } from '../../../../services/recycle-bin';
import { RecycleBinPurgeResult, RecycleBinSourceKey, RecycleBinTabKey } from '../../models/recycle-bin.model';
import { RECYCLE_BIN_ROUTES } from '../../recycle-bin.routes';
import { RecycleBinBulkService } from '../../services/recycle-bin-bulk.service';

// jsdom has no ResizeObserver; the overflow directive in the header only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

@Component({ selector: 'app-recycle-bin-tab', template: '' })
class RecycleBinTabStubComponent {
    readonly recycleBinTab = input<RecycleBinTabKey>();
}

/** The real routes with the tab component swapped for a stub, so no tab loads its list. */
function routesWithStubTabs(): Routes {
    const [pageRoute] = RECYCLE_BIN_ROUTES;
    return [
        {
            ...pageRoute,
            children: pageRoute.children?.map((child) =>
                child.component ? { ...child, component: RecycleBinTabStubComponent } : child
            ),
        },
    ];
}

describe('RecycleBinPageComponent', () => {
    let readable: ResourceCode[];
    let deletable: ResourceCode[];
    let retentionDays: WritableSignal<number | null>;
    let confirm: ReturnType<typeof vi.fn<(options: ConfirmationDialogData) => Observable<ConfirmationResult>>>;
    let purgeAll: ReturnType<
        typeof vi.fn<(sources: readonly RecycleBinSourceKey[]) => Observable<RecycleBinPurgeResult>>
    >;
    let toast: { success: ReturnType<typeof vi.fn>; error: ReturnType<typeof vi.fn> };

    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    beforeEach(() => {
        readable = [];
        deletable = [];
        retentionDays = signal<number | null>(7);
        confirm = vi.fn(() => of<ConfirmationResult>(true));
        purgeAll = vi.fn(() => of<RecycleBinPurgeResult>({ purgedCount: 3, failed: [] }));
        toast = { success: vi.fn(), error: vi.fn() };
        TestBed.configureTestingModule({
            providers: [
                provideRouter([
                    { path: 'recycle-bin', children: routesWithStubTabs() },
                    { path: 'profile', component: RecycleBinTabStubComponent },
                ]),
                {
                    provide: PermissionsService,
                    useValue: {
                        can: (resource: ResourceCode, action: ActionCode) =>
                            (action === ActionCode.Read && readable.includes(resource)) ||
                            (action === ActionCode.Delete && deletable.includes(resource)),
                        resolveDefaultRoute: () => '/profile',
                    },
                },
                { provide: RecycleBinSettingsStorageService, useValue: { retentionDays } },
                { provide: ConfirmationDialogService, useValue: { confirm } },
                { provide: RecycleBinBulkService, useValue: { purgeAll } },
                { provide: ToastService, useValue: toast },
            ],
        });
    });

    async function open(url: string): Promise<RouterTestingHarness> {
        const harness = await RouterTestingHarness.create();
        await harness.navigateByUrl(url);
        return harness;
    }

    function subtitleText(harness: RouterTestingHarness): string {
        return harness.routeNativeElement?.querySelector('.subtitle-inline')?.textContent ?? '';
    }

    it('opens the first readable tab in page order', async () => {
        readable = [ResourceCode.Files, ResourceCode.Flows];
        await open('/recycle-bin');
        expect(TestBed.inject(Router).url).toBe('/recycle-bin/flows');
    });

    it('opens Files when that is the only readable tab', async () => {
        readable = [ResourceCode.Files];
        await open('/recycle-bin');
        expect(TestBed.inject(Router).url).toBe('/recycle-bin/files');
    });

    it('falls back to the default route without any readable tab', async () => {
        await open('/recycle-bin');
        expect(TestBed.inject(Router).url).toBe('/profile');
    });

    it('shows only the tabs the user can read', async () => {
        readable = [ResourceCode.Tools, ResourceCode.Agents];
        const harness = await open('/recycle-bin/agents');
        const tabLabels = Array.from(harness.routeNativeElement?.querySelectorAll('app-tab-button') ?? [], (tab) =>
            tab.textContent?.trim()
        );
        expect(tabLabels).toEqual(['Agents', 'Tools']);
    });

    it('names the retention time in the subtitle', async () => {
        readable = [ResourceCode.Flows];
        const harness = await open('/recycle-bin/flows');
        expect(subtitleText(harness)).toContain('7 days');
    });

    it('leaves the number out while the retention time is unknown', async () => {
        readable = [ResourceCode.Flows];
        retentionDays.set(null);
        const harness = await open('/recycle-bin/flows');
        expect(subtitleText(harness)).toContain('for a while');
    });

    function emptyBinButton(harness: RouterTestingHarness): HTMLElement | null {
        return harness.routeNativeElement?.querySelector<HTMLElement>('.empty-bin-btn button') ?? null;
    }

    it('hides "Empty recycle bin" without DELETE on any visible tab', async () => {
        readable = [ResourceCode.Flows];
        const harness = await open('/recycle-bin/flows');
        expect(emptyBinButton(harness)).toBeNull();
    });

    it('empties only the tabs the user may delete on, Tools as both tool bins, after the typed phrase', async () => {
        readable = [ResourceCode.Flows, ResourceCode.Files, ResourceCode.Tools];
        deletable = [ResourceCode.Flows, ResourceCode.Tools, ResourceCode.Agents];
        const harness = await open('/recycle-bin/flows');

        emptyBinButton(harness)?.click();

        expect(confirm.mock.calls[0][0]).toMatchObject({
            type: 'danger',
            verification: { phrase: 'empty-recycle-bin' },
        });
        expect(purgeAll).toHaveBeenCalledWith(['flow', 'python_tool', 'mcp_tool']);
        expect(toast.success).toHaveBeenCalledWith('3 items deleted permanently.');
    });

    it('reports only the failure when nothing could be deleted, never "already empty"', async () => {
        readable = [ResourceCode.Flows];
        deletable = [ResourceCode.Flows];
        purgeAll.mockReturnValue(
            of<RecycleBinPurgeResult>({ purgedCount: 0, failed: [{ name: 'Report', message: 'It is locked.' }] })
        );
        const harness = await open('/recycle-bin/flows');

        emptyBinButton(harness)?.click();

        expect(toast.success).not.toHaveBeenCalled();
        expect(toast.error).toHaveBeenCalled();
    });

    it('sends nothing when emptying the bin is cancelled', async () => {
        readable = [ResourceCode.Flows];
        deletable = [ResourceCode.Flows];
        confirm.mockReturnValue(of<ConfirmationResult>(false));
        const harness = await open('/recycle-bin/flows');

        emptyBinButton(harness)?.click();

        expect(purgeAll).not.toHaveBeenCalled();
    });
});
