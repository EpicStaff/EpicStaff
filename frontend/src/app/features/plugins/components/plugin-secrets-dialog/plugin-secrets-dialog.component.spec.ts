import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Observable, of, Subject, throwError } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { PluginDetail, PluginSecretsRequest, PluginStatus } from '../../models/plugin.model';
import { PluginsStoreService } from '../../services/plugins-store.service';
import { PluginSecretsDialogComponent, PluginSecretsDialogData } from './plugin-secrets-dialog.component';

// jsdom has no ResizeObserver; the overflow directive inside app-button only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

function buildPlugin(status: PluginStatus): PluginDetail {
    return {
        id: 7,
        plugin_id: 'chat-bot',
        version: '0.1.0',
        name: 'Chat Bot',
        description: '',
        icon_data_url: '',
        format_version: 1,
        bridge_version: 1,
        has_ui: true,
        status,
        // A suspended plugin can still be failing underneath; retry is refused while it is suspended.
        state: status === 'suspended' ? 'needs_attention' : status,
        status_reason: status === 'needs_attention' ? 'Indexing failed: invalid API key' : '',
        suspended: status === 'suspended',
        suspended_at: null,
        access: [],
        secret_slots: [
            {
                name: 'OPENAI_API_KEY',
                description: 'OpenAI API key used by the chat model.',
                secret_id: 17,
                secret_name: 'CHAT_BOT__OPENAI_API_KEY',
                configured: true,
                destinations: [
                    { resource_type: 'llm_config', name: 'Chat Bot GPT-4o mini', provider: 'openai', host: null },
                    {
                        resource_type: 'embedding_config',
                        name: 'Chat Bot embeddings',
                        provider: 'openai',
                        host: 'llm-proxy.example.com',
                    },
                ],
            },
            {
                name: 'SEARCH_API_KEY',
                description: 'Search API key.',
                secret_id: null,
                secret_name: null,
                configured: false,
                destinations: [],
            },
        ],
        contents: {},
        created_by: 1,
        created_at: '2026-10-06T21:30:00Z',
        updated_at: '2026-10-06T21:30:00Z',
        resources: [],
    };
}

describe('PluginSecretsDialogComponent', () => {
    let fixture: ComponentFixture<PluginSecretsDialogComponent>;
    let updateSecrets: ReturnType<
        typeof vi.fn<(id: number, request: PluginSecretsRequest) => Observable<PluginDetail>>
    >;
    let retry: ReturnType<typeof vi.fn<(id: number) => Observable<PluginDetail>>>;
    let close: ReturnType<typeof vi.fn>;
    let toastSuccess: ReturnType<typeof vi.fn>;
    let keydownEvents: Subject<KeyboardEvent>;

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        updateSecrets = vi.fn<(id: number, request: PluginSecretsRequest) => Observable<PluginDetail>>();
        retry = vi.fn<(id: number) => Observable<PluginDetail>>();
        close = vi.fn();
        toastSuccess = vi.fn();
        keydownEvents = new Subject<KeyboardEvent>();
    });

    afterEach(() => vi.unstubAllGlobals());

    async function open(plugin: PluginDetail): Promise<HTMLElement> {
        const data: PluginSecretsDialogData = { plugin };
        TestBed.configureTestingModule({
            imports: [PluginSecretsDialogComponent],
            providers: [
                {
                    provide: DialogRef,
                    useValue: {
                        close,
                        backdropClick: new Subject<MouseEvent>(),
                        keydownEvents,
                        disableClose: false,
                    } as unknown as DialogRef,
                },
                { provide: DIALOG_DATA, useValue: data },
                { provide: PluginsStoreService, useValue: { updateSecrets, retry } as unknown as PluginsStoreService },
                {
                    provide: ToastService,
                    useValue: { success: toastSuccess, error: vi.fn() } as unknown as ToastService,
                },
            ],
        });
        fixture = TestBed.createComponent(PluginSecretsDialogComponent);
        await render();
        return fixture.nativeElement as HTMLElement;
    }

    async function render(): Promise<void> {
        fixture.detectChanges();
        await fixture.whenStable();
        fixture.detectChanges();
    }

    function secretInput(slot: string): HTMLInputElement {
        const input = (fixture.nativeElement as HTMLElement).querySelector<HTMLInputElement>(`#plugin-secret-${slot}`);
        if (!input) throw new Error(`No input for the slot ${slot}`);
        return input;
    }

    async function enter(slot: string, value: string): Promise<void> {
        const input = secretInput(slot);
        input.value = value;
        input.dispatchEvent(new Event('input'));
        await render();
    }

    function button(label: string): HTMLButtonElement | null {
        const hosts = Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('app-button'));
        return hosts.find((host) => host.textContent?.trim() === label)?.querySelector('button') ?? null;
    }

    async function click(label: string): Promise<void> {
        const target = button(label);
        if (!target) throw new Error(`No "${label}" button`);
        target.click();
        await render();
    }

    /** What the dialog still holds for every slot. */
    function heldValues(component: PluginSecretsDialogComponent = fixture.componentInstance): string[] {
        return Object.values(component['form'].getRawValue());
    }

    it('sends only the slots that were entered, and leaves the retry to the admin', async () => {
        updateSecrets.mockReturnValue(of(buildPlugin('ready')));
        await open(buildPlugin('ready'));

        await enter('OPENAI_API_KEY', 'sk-new');
        await click('Save');

        expect(updateSecrets).toHaveBeenCalledTimes(1);
        expect(updateSecrets).toHaveBeenCalledWith(7, {
            secrets: { OPENAI_API_KEY: 'sk-new' },
            retry_indexing: false,
        });
    });

    it('keeps Save disabled until a slot has a value that is not only spaces', async () => {
        await open(buildPlugin('ready'));
        expect(button('Save')?.disabled).toBe(true);

        await enter('OPENAI_API_KEY', '   ');
        expect(button('Save')?.disabled).toBe(true);

        await enter('OPENAI_API_KEY', 'sk-new');
        expect(button('Save')?.disabled).toBe(false);
    });

    it('clears the entered values, inputs included, when the dialog is closed', async () => {
        await open(buildPlugin('needs_attention'));
        await enter('OPENAI_API_KEY', 'sk-new');
        await enter('SEARCH_API_KEY', 'search-new');

        await click('Cancel');

        expect(close).toHaveBeenCalledWith(undefined);
        expect(heldValues()).toEqual(['', '']);
        expect(secretInput('OPENAI_API_KEY').value).toBe('');
        expect(secretInput('SEARCH_API_KEY').value).toBe('');
    });

    it('clears the entered values when something else closes the dialog', async () => {
        await open(buildPlugin('ready'));
        await enter('OPENAI_API_KEY', 'sk-new');
        const component = fixture.componentInstance;

        fixture.destroy();

        expect(heldValues(component)).toEqual(['', '']);
    });

    it('does not close while the save is on its way', async () => {
        updateSecrets.mockReturnValue(new Subject<PluginDetail>());
        await open(buildPlugin('ready'));
        await enter('OPENAI_API_KEY', 'sk-new');
        await click('Save');

        keydownEvents.next(new KeyboardEvent('keydown', { key: 'Escape', cancelable: true }));

        expect(close).not.toHaveBeenCalled();
    });

    it('offers Retry now after a save that leaves the plugin needing attention, and retries', async () => {
        updateSecrets.mockReturnValue(of(buildPlugin('needs_attention')));
        retry.mockReturnValue(of(buildPlugin('preparing')));
        const element = await open(buildPlugin('needs_attention'));
        expect(element.textContent).toContain('Needs attention: Indexing failed: invalid API key');

        await enter('OPENAI_API_KEY', 'sk-new');
        await click('Save');

        expect(close).not.toHaveBeenCalled();
        expect(heldValues()).toEqual(['', '']);
        expect(element.textContent).toContain('Secrets saved');
        expect(button('Retry now')).not.toBeNull();

        await click('Retry now');

        expect(retry).toHaveBeenCalledWith(7);
        expect(toastSuccess).toHaveBeenCalledWith('Preparing knowledge again');
        expect(close).toHaveBeenCalledWith(expect.objectContaining({ status: 'preparing' }));
    });

    it.each<PluginStatus>(['ready', 'preparing', 'suspended'])(
        'closes without offering Retry when the save leaves the plugin %s',
        async (status) => {
            updateSecrets.mockReturnValue(of(buildPlugin(status)));
            await open(buildPlugin(status));

            await enter('OPENAI_API_KEY', 'sk-new');
            await click('Save');

            expect(button('Retry now')).toBeNull();
            expect(retry).not.toHaveBeenCalled();
            expect(toastSuccess).toHaveBeenCalledWith('Secrets of Chat Bot updated');
            expect(close).toHaveBeenCalledWith(expect.objectContaining({ status }));
            expect(heldValues()).toEqual(['', '']);
        }
    );

    it('shows where each value is sent and calls out a custom host', async () => {
        const element = await open(buildPlugin('ready'));

        const items = Array.from(element.querySelectorAll('.plugin-secret-destinations__item'));

        expect(items.map((item) => item.textContent?.replace(/\s+/g, ' ').trim())).toEqual([
            "Sent to: openai's standard endpoint by LLM configuration 'Chat Bot GPT-4o mini'",
            "Sent to: llm-proxy.example.com (custom endpoint) by Embedding configuration 'Chat Bot embeddings'",
        ]);
        expect(items.map((item) => item.classList.contains('plugin-secret-destinations__item--custom'))).toEqual([
            false,
            true,
        ]);
    });

    it('shows the error envelope, keeps the values to correct, and never echoes them', async () => {
        updateSecrets.mockReturnValue(
            throwError(
                () =>
                    new HttpErrorResponse({
                        status: 400,
                        error: {
                            status_code: 400,
                            code: 'invalid_plugin_secrets',
                            message: 'Some secret values are invalid.',
                            errors: [{ slot: 'OPENAI_API_KEY', message: 'This secret name is already taken.' }],
                        },
                    })
            )
        );
        const element = await open(buildPlugin('needs_attention'));

        await enter('OPENAI_API_KEY', 'sk-wrong');
        await click('Save');

        const alert = element.querySelector('[role="alert"]');
        expect(alert?.textContent).toContain('Some secret values are invalid.');
        expect(alert?.textContent).toContain('OPENAI_API_KEY: This secret name is already taken.');
        expect(close).not.toHaveBeenCalled();
        expect(heldValues()).toEqual(['sk-wrong', '']);
        expect(element.textContent).not.toContain('sk-wrong');
    });
});
