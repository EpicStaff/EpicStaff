import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Observable, of, Subject, throwError } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { PluginDetail, PluginSummary } from '../../models/plugin.model';
import { PluginsStoreService } from '../../services/plugins-store.service';
import { PluginDevModeDialogComponent, PluginDevModeDialogData } from './plugin-dev-mode-dialog.component';

// jsdom has no ResizeObserver; the overflow directive inside app-button only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

function buildPlugin(overrides: Partial<PluginSummary> = {}): PluginDetail {
    return {
        id: 8,
        plugin_id: 'chat-admin',
        version: '0.2.0',
        name: 'Chat Admin',
        description: '',
        icon_data_url: '',
        format_version: 1,
        bridge_version: 2,
        has_ui: true,
        status: 'ready',
        state: 'ready',
        status_reason: '',
        suspended: false,
        suspended_at: null,
        access: [],
        secret_slots: [],
        contents: {},
        dev_mode_available: true,
        dev_ui_url: null,
        dev_ui_user: null,
        created_by: 1,
        created_at: '2026-10-07T10:00:00Z',
        updated_at: '2026-10-07T10:00:00Z',
        resources: [],
        ...overrides,
    };
}

describe('PluginDevModeDialogComponent', () => {
    let fixture: ComponentFixture<PluginDevModeDialogComponent>;
    let setDevUi: ReturnType<typeof vi.fn<(id: number, url: string) => Observable<PluginDetail>>>;
    let clearDevUi: ReturnType<typeof vi.fn<(id: number) => Observable<PluginDetail>>>;
    let close: ReturnType<typeof vi.fn>;

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        setDevUi = vi.fn<(id: number, url: string) => Observable<PluginDetail>>();
        clearDevUi = vi.fn<(id: number) => Observable<PluginDetail>>();
        close = vi.fn();
    });

    afterEach(() => vi.unstubAllGlobals());

    async function open(plugin: PluginSummary): Promise<HTMLElement> {
        const data: PluginDevModeDialogData = { plugin };
        TestBed.configureTestingModule({
            imports: [PluginDevModeDialogComponent],
            providers: [
                {
                    provide: DialogRef,
                    useValue: {
                        close,
                        backdropClick: new Subject<MouseEvent>(),
                        keydownEvents: new Subject<KeyboardEvent>(),
                        disableClose: false,
                    } as unknown as DialogRef,
                },
                { provide: DIALOG_DATA, useValue: data },
                { provide: PluginsStoreService, useValue: { setDevUi, clearDevUi } },
                { provide: ToastService, useValue: { success: vi.fn(), error: vi.fn() } },
            ],
        });
        fixture = TestBed.createComponent(PluginDevModeDialogComponent);
        await render();
        return fixture.nativeElement as HTMLElement;
    }

    async function render(): Promise<void> {
        fixture.detectChanges();
        await fixture.whenStable();
        fixture.detectChanges();
    }

    async function enterUrl(value: string): Promise<void> {
        const input = (fixture.nativeElement as HTMLElement).querySelector<HTMLInputElement>('#plugin-dev-ui-url');
        if (!input) throw new Error('No URL input');
        input.value = value;
        input.dispatchEvent(new Event('input'));
        await render();
    }

    function button(label: string): HTMLButtonElement | null {
        const buttons = [...(fixture.nativeElement as HTMLElement).querySelectorAll('button')];
        return buttons.find((candidate) => candidate.textContent?.trim() === label) ?? null;
    }

    it('saves a localhost dev URL for the plugin and closes with the updated plugin', async () => {
        const updated = buildPlugin({ dev_ui_url: 'http://127.0.0.1:5173/' });
        setDevUi.mockReturnValue(of(updated));
        await open(buildPlugin());

        await enterUrl(' http://127.0.0.1:5173/ ');
        button('Use this address')?.click();

        expect(setDevUi).toHaveBeenCalledWith(8, 'http://127.0.0.1:5173/');
        expect(close).toHaveBeenCalledWith(updated);
    });

    it.each(['https://localhost:4300/', 'http://localhost.evil.com/', 'http://localhost:4300/?x=1', ''])(
        'refuses to save %j',
        async (url) => {
            await open(buildPlugin());

            await enterUrl(url);
            button('Use this address')?.click();

            expect(button('Use this address')?.disabled).toBe(true);
            expect(setDevUi).not.toHaveBeenCalled();
        }
    );

    it('turns dev mode off only when a dev URL is set', async () => {
        clearDevUi.mockReturnValue(of(buildPlugin()));
        await open(buildPlugin({ dev_ui_url: 'http://localhost:4300/' }));

        button('Turn off')?.click();

        expect(clearDevUi).toHaveBeenCalledWith(8);
        expect(close).toHaveBeenCalled();
    });

    it('offers no turn off without a dev URL', async () => {
        await open(buildPlugin());

        expect(button('Turn off')).toBeNull();
    });

    it("shows the server's reason and stays open when the instance is not in dev mode", async () => {
        setDevUi.mockReturnValue(
            throwError(
                () =>
                    new HttpErrorResponse({
                        status: 409,
                        error: {
                            status_code: 409,
                            code: 'plugin_dev_mode_disabled',
                            message: 'Plugin dev mode is off on this EpicStaff.',
                        },
                    })
            )
        );
        await open(buildPlugin());

        button('Use this address')?.click();
        await render();

        expect((fixture.nativeElement as HTMLElement).textContent).toContain(
            'Plugin dev mode is off on this EpicStaff.'
        );
        expect(close).not.toHaveBeenCalled();
    });
});
