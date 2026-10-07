import { Dialog } from '@angular/cdk/dialog';
import { signal, WritableSignal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ConfirmationDialogService } from '@shared/components';
import { ActionCode, ResourceCode } from '@shared/models';
import { of } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { PluginSummary } from '../../models/plugin.model';
import { PluginsStoreService } from '../../services/plugins-store.service';
import { PluginDevModeDialogComponent } from '../plugin-dev-mode-dialog/plugin-dev-mode-dialog.component';
import { PluginsSectionComponent } from './plugins-section.component';

// jsdom has no ResizeObserver; the overflow directive inside app-button only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

function buildPlugin(overrides: Partial<PluginSummary> = {}): PluginSummary {
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
        ...overrides,
    };
}

describe('PluginsSectionComponent', () => {
    let fixture: ComponentFixture<PluginsSectionComponent>;
    let plugins: WritableSignal<PluginSummary[]>;
    let canUpdatePlugins: boolean;
    let openDialog: ReturnType<typeof vi.fn>;
    let clearDevUi: ReturnType<typeof vi.fn>;

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        plugins = signal<PluginSummary[]>([]);
        canUpdatePlugins = true;
        openDialog = vi.fn();
        clearDevUi = vi.fn((id: number) => of(buildPlugin({ id })));
        TestBed.configureTestingModule({
            imports: [PluginsSectionComponent],
            providers: [
                {
                    provide: PluginsStoreService,
                    useValue: {
                        plugins,
                        loading: signal(false),
                        loaded: signal(true),
                        refresh: () => of([]),
                        clearDevUi,
                    },
                },
                {
                    provide: PermissionsService,
                    useValue: {
                        can: (resource: ResourceCode, action: ActionCode) =>
                            resource === ResourceCode.Plugins && (action !== ActionCode.Update || canUpdatePlugins),
                        canAny: () => false,
                    },
                },
                { provide: Dialog, useValue: { open: openDialog } },
                { provide: ConfirmationDialogService, useValue: { confirm: vi.fn() } },
                { provide: ToastService, useValue: { success: vi.fn(), error: vi.fn() } },
            ],
        });
    });

    afterEach(() => vi.unstubAllGlobals());

    async function render(...rows: PluginSummary[]): Promise<HTMLElement> {
        plugins.set(rows);
        fixture = TestBed.createComponent(PluginsSectionComponent);
        await fixture.whenStable();
        fixture.detectChanges();
        return fixture.nativeElement as HTMLElement;
    }

    function devModeButton(element: HTMLElement): HTMLButtonElement | undefined {
        return buttonLabelled(element, 'Dev mode');
    }

    function buttonLabelled(element: HTMLElement, label: string): HTMLButtonElement | undefined {
        return [...element.querySelectorAll('button')].find((button) => button.textContent?.trim() === label);
    }

    it('offers dev mode for a plugin with a page while the instance runs in dev mode', async () => {
        const plugin = buildPlugin();
        const element = await render(plugin);

        devModeButton(element)?.click();

        expect(openDialog).toHaveBeenCalledWith(
            PluginDevModeDialogComponent,
            expect.objectContaining({ data: { plugin } })
        );
    });

    it.each([
        ['the instance is not in dev mode', buildPlugin({ dev_mode_available: false }), true],
        ['the plugin has no page', buildPlugin({ has_ui: false }), true],
        ['the role may not update plugins', buildPlugin(), false],
    ])('offers no dev mode when %s', async (_label, plugin, canUpdate) => {
        canUpdatePlugins = canUpdate;

        const element = await render(plugin);

        expect(devModeButton(element)).toBeUndefined();
    });

    it('marks a plugin whose dev URL is set with a DEV badge, saying where it loads from', async () => {
        const element = await render(
            buildPlugin({ id: 8, dev_ui_url: 'http://localhost:4300/', dev_ui_user: 3 }),
            buildPlugin({ id: 9, name: 'Other' })
        );

        const badges = element.querySelectorAll('.plugins-section__dev-badge');
        expect(badges).toHaveLength(1);
        expect(badges[0].textContent?.trim()).toBe('DEV');
        expect(badges[0].getAttribute('title')).toContain('http://localhost:4300/');
    });

    it('lets a stale dev URL be cleared while the instance is not in dev mode, without offering to set one', async () => {
        const element = await render(buildPlugin({ dev_mode_available: false, dev_ui_url: 'http://localhost:4300/' }));

        expect(devModeButton(element)).toBeUndefined();
        buttonLabelled(element, 'Turn off dev mode')?.click();

        expect(clearDevUi).toHaveBeenCalledWith(8);
    });

    it('offers to turn dev mode off whenever a dev URL is set, next to changing it', async () => {
        const element = await render(buildPlugin({ dev_ui_url: 'http://localhost:4300/' }));

        expect(devModeButton(element)).toBeDefined();
        expect(buttonLabelled(element, 'Turn off dev mode')).toBeDefined();
    });

    it.each([
        ['no dev URL is set', buildPlugin({ dev_mode_available: false }), true],
        ['the role may not update plugins', buildPlugin({ dev_ui_url: 'http://localhost:4300/' }), false],
    ])('offers no turn off when %s', async (_label, plugin, canUpdate) => {
        canUpdatePlugins = canUpdate;

        const element = await render(plugin);

        expect(buttonLabelled(element, 'Turn off dev mode')).toBeUndefined();
    });

    it('says a dev URL is inactive while the instance is not in dev mode', async () => {
        const element = await render(buildPlugin({ dev_mode_available: false, dev_ui_url: 'http://localhost:4300/' }));

        expect(element.querySelector('.plugins-section__dev-badge')?.getAttribute('title')).toContain('Inactive');
    });
});
