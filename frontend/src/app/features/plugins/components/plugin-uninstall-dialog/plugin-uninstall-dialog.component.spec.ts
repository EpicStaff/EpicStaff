import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Observable, of, Subject, throwError } from 'rxjs';
import type { Mock } from 'vitest';

import { PluginDetail } from '../../models/plugin-admin.model';
import { PluginPurgePreview, PluginPurgePreviewOrganization } from '../../models/plugin-purge-preview.model';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import { buildPluginDetail, buildPluginPurgePreview } from '../../testing/plugin-fixtures';
import { PLUGIN_ERROR_MESSAGES } from '../../utils/plugin-error-message.util';
import { PluginUninstallDialogComponent, PluginUninstallDialogData } from './plugin-uninstall-dialog.component';

class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

const UNINSTALLED: PluginDetail = buildPluginDetail({
    state: 'uninstalling',
    allowed_actions: ['reinstall', 'purge'],
    uninstall_requested_at: '2026-10-21T09:00:00Z',
    purge_after: '2026-11-20T09:00:00Z',
});

function organization(grantId: number, name: string): PluginPurgePreviewOrganization {
    return { grant_id: grantId, organization: { id: grantId + 10, name }, state: 'active', owned_resource_count: 1 };
}

describe('PluginUninstallDialogComponent', () => {
    let fixture: ComponentFixture<PluginUninstallDialogComponent>;
    let element: HTMLElement;
    let storage: {
        getPluginPurgePreview: Mock<(identifier: string) => Observable<PluginPurgePreview>>;
        uninstallPlugin: Mock<(identifier: string) => Observable<PluginDetail>>;
    };
    let dialogRef: { close: Mock<(result?: PluginDetail) => void>; keydownEvents: Subject<KeyboardEvent> };

    function render(): void {
        fixture = TestBed.createComponent(PluginUninstallDialogComponent);
        element = fixture.nativeElement as HTMLElement;
        fixture.detectChanges();
    }

    function text(node: Element | null | undefined): string {
        return node?.textContent?.replace(/\s+/g, ' ').trim() ?? '';
    }

    function button(label: string): HTMLButtonElement {
        return Array.from(element.querySelectorAll<HTMLButtonElement>('button')).find(
            (candidate) => text(candidate) === label
        )!;
    }

    function section(heading: string): HTMLElement | undefined {
        return Array.from(element.querySelectorAll<HTMLElement>('app-plugin-preview-section')).find(
            (candidate) => text(candidate.querySelector('h3')) === heading
        );
    }

    function items(heading: string): string[] {
        return Array.from(section(heading)?.querySelectorAll('li') ?? []).map((item) =>
            [text(item.querySelector('.section__name')), text(item.querySelector('.section__detail'))]
                .filter(Boolean)
                .join(' | ')
        );
    }

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        storage = {
            getPluginPurgePreview: vi.fn(() => of(buildPluginPurgePreview())),
            uninstallPlugin: vi.fn(() => of(UNINSTALLED)),
        };
        dialogRef = { close: vi.fn(), keydownEvents: new Subject<KeyboardEvent>() };
        const data: PluginUninstallDialogData = { identifier: 'weather', pluginName: 'Weather' };
        TestBed.configureTestingModule({
            imports: [PluginUninstallDialogComponent],
            providers: [
                { provide: PluginsAdminStorageService, useValue: storage },
                { provide: DIALOG_DATA, useValue: data },
                { provide: DialogRef, useValue: dialogRef },
            ],
        });
    });

    afterEach(() => vi.unstubAllGlobals());

    it('waits for the preview before it can uninstall', () => {
        const preview = new Subject<PluginPurgePreview>();
        storage.getPluginPurgePreview.mockReturnValue(preview);
        render();

        expect(storage.getPluginPurgePreview).toHaveBeenCalledWith('weather');
        expect(element.querySelector('app-loading-spinner')).not.toBeNull();
        expect(text(element.querySelector('.dialog__title'))).toBe('Uninstall Weather');
        expect(text(element.querySelector('.uninstall__summary'))).toBe(
            'Uninstall Weather? It stops working in every organization it is granted to. Its process stops, and ' +
                'every flow that uses its resources stops.'
        );
        expect(button('Uninstall').disabled).toBe(true);
        button('Uninstall').click();
        expect(storage.uninstallPlugin).not.toHaveBeenCalled();

        preview.next(buildPluginPurgePreview());
        preview.complete();
        fixture.detectChanges();

        expect(button('Uninstall').disabled).toBe(false);
    });

    it('shows the organizations with their state and owned counts, the owned totals and until when data is kept', () => {
        render();

        expect(items('Organizations')).toEqual(['Acme | Active · 2 owned']);
        expect(items('What Weather owns in all organizations')).toEqual(['Files | 1', 'Flows | 1']);
        expect(text(element.querySelector('.uninstall__kept'))).toBe(
            'Its data is kept until Nov 20, 2026. Reinstall before then to restore everything.'
        );
        expect(element.querySelector('.purge__verification-input')).toBeNull();
    });

    it('says how many more organizations there are, and when it is granted to none', () => {
        storage.getPluginPurgePreview.mockReturnValueOnce(
            of(
                buildPluginPurgePreview({
                    organizations: { total: 5, items: [organization(1, 'Acme'), organization(2, 'Beta')] },
                })
            )
        );
        render();
        expect(items('Organizations')).toEqual(['Acme | Active · 1 owned', 'Beta | Active · 1 owned']);
        expect(text(section('Organizations')?.querySelector('.section__more'))).toBe('and 3 more');

        storage.getPluginPurgePreview.mockReturnValueOnce(
            of(buildPluginPurgePreview({ organizations: { total: 0, items: [] }, owned_resources: [] }))
        );
        render();
        expect(text(section('Organizations')?.querySelector('.section__empty'))).toBe(
            'None. Weather is not granted to any organization.'
        );
        expect(section('What Weather owns in all organizations')).toBeUndefined();
    });

    it('shows why the preview did not load, keeps Uninstall disabled, and loads it again on Retry', () => {
        storage.getPluginPurgePreview.mockReturnValueOnce(
            throwError(() => new HttpErrorResponse({ status: 502, error: null }))
        );
        render();

        expect(text(element.querySelector('.dialog__load-error'))).toContain(
            "Couldn't load what uninstalling would stop."
        );
        expect(button('Uninstall').disabled).toBe(true);

        button('Retry').click();
        fixture.detectChanges();

        expect(storage.getPluginPurgePreview).toHaveBeenCalledTimes(2);
        expect(button('Uninstall').disabled).toBe(false);
    });

    it('uninstalls and closes with the plugin uninstalled', () => {
        render();
        button('Uninstall').click();

        expect(storage.uninstallPlugin).toHaveBeenCalledWith('weather');
        expect(dialogRef.close).toHaveBeenCalledWith(UNINSTALLED);
    });

    it('keeps the dialog open with the reason when the uninstall is refused', () => {
        storage.uninstallPlugin.mockReturnValue(
            throwError(
                () =>
                    new HttpErrorResponse({
                        status: 409,
                        error: { status_code: 409, code: 'plugin_not_uninstallable', message: 'Refused.' },
                    })
            )
        );
        render();
        button('Uninstall').click();
        fixture.detectChanges();

        expect(dialogRef.close).not.toHaveBeenCalled();
        expect(text(element.querySelector('.dialog__error'))).toBe(PLUGIN_ERROR_MESSAGES.plugin_not_uninstallable);
    });

    it('closes on Cancel and on Escape without a call, but not while the uninstall is under way', () => {
        render();

        button('Cancel').click();
        dialogRef.keydownEvents.next(new KeyboardEvent('keydown', { key: 'Escape' }));
        expect(dialogRef.close).toHaveBeenCalledTimes(2);
        expect(storage.uninstallPlugin).not.toHaveBeenCalled();

        storage.uninstallPlugin.mockReturnValue(new Subject<PluginDetail>());
        button('Uninstall').click();
        fixture.detectChanges();
        dialogRef.keydownEvents.next(new KeyboardEvent('keydown', { key: 'Escape' }));

        expect(dialogRef.close).toHaveBeenCalledTimes(2);
        expect(button('Cancel').disabled).toBe(true);
    });
});
