import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Observable, of, throwError } from 'rxjs';
import type { Mock } from 'vitest';

import { ToastService } from '../../../../services/notifications';
import { PluginSettingsResponse, PluginSettingsUpdate } from '../../models/plugin-backend.model';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import { buildPluginSetting, buildPluginSettings } from '../../testing/plugin-fixtures';
import { PluginSettingsFormComponent, SECRET_MASK } from './plugin-settings-form.component';

class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

/** One setting of every type; the URL is required and missing. */
function everyType(): PluginSettingsResponse {
    return buildPluginSettings({
        settings: [
            buildPluginSetting({
                key: 'city',
                type: 'string',
                label: 'City',
                values: null,
                default: null,
                value: 'Kyiv',
                is_set: true,
                updated_at: '2026-10-20T10:00:00Z',
                updated_by: { id: 1, email: 'admin@example.com' },
            }),
            buildPluginSetting({ key: 'notes', type: 'text', label: 'Notes', values: null, default: null }),
            buildPluginSetting({ key: 'days', type: 'integer', label: 'Days', values: null, default: 3 }),
            buildPluginSetting({ key: 'alerts', type: 'boolean', label: 'Alerts', values: null, default: false }),
            buildPluginSetting({
                key: 'endpoint',
                type: 'url',
                label: 'Endpoint',
                values: null,
                default: null,
                required: true,
            }),
            buildPluginSetting(),
            buildPluginSetting({
                key: 'forecast_api_token',
                type: 'secret',
                label: 'Forecast API token',
                values: null,
                default: null,
                is_set: true,
                tail: 'abcd',
            }),
            buildPluginSetting({
                key: 'backup_token',
                type: 'secret',
                label: 'Backup token',
                values: null,
                default: null,
            }),
        ],
        missing_required: ['endpoint'],
    });
}

describe('PluginSettingsFormComponent', () => {
    let fixture: ComponentFixture<PluginSettingsFormComponent>;
    let element: HTMLElement;
    let storage: {
        getSettings: Mock<(identifier: string) => Observable<PluginSettingsResponse>>;
        updateSettings: Mock<(identifier: string, update: PluginSettingsUpdate) => Observable<PluginSettingsResponse>>;
    };

    async function render(response: PluginSettingsResponse = everyType()): Promise<void> {
        storage.getSettings.mockReturnValue(of(response));
        fixture = TestBed.createComponent(PluginSettingsFormComponent);
        element = fixture.nativeElement as HTMLElement;
        fixture.componentRef.setInput('identifier', 'weather');
        await settle();
    }

    async function settle(): Promise<void> {
        fixture.detectChanges();
        await fixture.whenStable();
        fixture.detectChanges();
    }

    function field(key: string): HTMLElement {
        return element.querySelector<HTMLElement>(`[data-setting-key="${key}"]`)!;
    }

    function buttonIn(container: Element, text: string): HTMLButtonElement | undefined {
        return Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find(
            (button) => button.textContent?.trim() === text
        );
    }

    function saveButton(): HTMLButtonElement {
        return buttonIn(element.querySelector('.settings__footer')!, 'Save settings')!;
    }

    async function type(key: string, text: string): Promise<void> {
        const input = field(key).querySelector<HTMLInputElement>('input')!;
        input.value = text;
        input.dispatchEvent(new Event('input'));
        await settle();
    }

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        storage = {
            getSettings: vi.fn(() => of(everyType())),
            updateSettings: vi.fn(() => of(everyType())),
        };
        TestBed.configureTestingModule({
            imports: [PluginSettingsFormComponent],
            providers: [
                { provide: PluginsAdminStorageService, useValue: storage },
                { provide: ToastService, useValue: { success: vi.fn(), error: vi.fn() } },
            ],
        });
    });

    afterEach(() => vi.unstubAllGlobals());

    it('shows one control per setting type, the required markers and the missing-required banner', async () => {
        await render();

        expect(storage.getSettings).toHaveBeenCalledWith('weather');
        expect(field('city').querySelector('app-custom-input')).not.toBeNull();
        expect(field('notes').querySelector('app-textarea')).not.toBeNull();
        expect(field('days').querySelector('app-custom-input')).not.toBeNull();
        expect(field('alerts').querySelector('app-toggle-switch')).not.toBeNull();
        expect(field('endpoint').querySelector('app-custom-input')).not.toBeNull();
        expect(field('units').querySelector('app-select')).not.toBeNull();
        expect(field('endpoint').querySelector('.required')).not.toBeNull();
        expect(field('city').querySelector('.required')).toBeNull();
        expect(element.querySelector('.settings__missing')?.textContent).toContain(
            'The plugin stays stopped until these required settings are set: Endpoint.'
        );
        expect(field('city').querySelector<HTMLInputElement>('input')!.value).toBe('Kyiv');
        expect(element.querySelector('.settings__footer')?.textContent).toContain('Saving restarts the plugin');
    });

    it('never shows or prefills a secret: only the tail of a stored one, and an empty input to replace it', async () => {
        await render();

        expect(field('forecast_api_token').querySelector('input')).toBeNull();
        expect(field('forecast_api_token').textContent).toContain(`${SECRET_MASK} abcd`);
        expect(buttonIn(field('backup_token'), 'Set')).toBeDefined();
        expect(field('backup_token').textContent).toContain('Not set');

        buttonIn(field('forecast_api_token'), 'Replace')!.click();
        await settle();

        const input = field('forecast_api_token').querySelector<HTMLInputElement>('input')!;
        expect(input.type).toBe('password');
        expect(input.autocomplete).toBe('new-password');
        expect(input.value).toBe('');
        expect(saveButton().disabled).toBe(true);

        await type('forecast_api_token', 'new-secret-value');
        saveButton().click();

        expect(storage.updateSettings).toHaveBeenCalledWith('weather', {
            values: { forecast_api_token: 'new-secret-value' },
        });
    });

    it('clears a stored secret with null, and Undo takes the clearing back', async () => {
        await render();

        buttonIn(field('forecast_api_token'), 'Clear')!.click();
        await settle();
        expect(field('forecast_api_token').textContent).toContain('Cleared when you save.');
        buttonIn(field('forecast_api_token'), 'Undo')!.click();
        await settle();
        expect(saveButton().disabled).toBe(true);

        buttonIn(field('forecast_api_token'), 'Clear')!.click();
        await settle();
        saveButton().click();

        expect(storage.updateSettings).toHaveBeenCalledWith('weather', { values: { forecast_api_token: null } });
    });

    it('sends only the changed keys: an integer as a number, an emptied field as null', async () => {
        await render();
        expect(saveButton().disabled).toBe(true);

        await type('days', '-2');
        await type('city', '');
        saveButton().click();

        expect(storage.updateSettings).toHaveBeenCalledWith('weather', { values: { days: -2, city: null } });
    });

    it('refuses to save an integer setting that is not a whole number', async () => {
        await render();

        await type('days', '2.5');

        expect(field('days').querySelector('.error-message')?.textContent?.trim()).toBe('Enter a whole number.');
        expect(saveButton().disabled).toBe(true);
    });

    it('shows the errors of a refused save next to their fields by loc, and the rest above', async () => {
        await render();
        storage.updateSettings.mockReturnValueOnce(
            throwError(
                () =>
                    new HttpErrorResponse({
                        status: 400,
                        error: {
                            status_code: 400,
                            code: 'invalid_plugin_settings',
                            message: 'Invalid settings.',
                            errors: [
                                { loc: 'values.endpoint', message: 'Enter an http(s) URL.' },
                                { loc: 'values.city', message: 'At most 1000 characters.' },
                                { loc: 'values', message: 'Unknown key "colour".' },
                            ],
                        },
                    })
            )
        );

        await type('endpoint', 'ftp://example.com');
        saveButton().click();
        await settle();

        expect(field('endpoint').querySelector('.error-message')?.textContent?.trim()).toBe('Enter an http(s) URL.');
        expect(field('city').querySelector('.error-message')?.textContent?.trim()).toBe('At most 1000 characters.');
        const banner = element.querySelector('.settings__error')!;
        expect(banner.textContent).toContain('Some settings are not valid.');
        expect(banner.textContent).toContain('Unknown key "colour".');
        // The edit is kept, so it can be fixed.
        expect(field('endpoint').querySelector<HTMLInputElement>('input')!.value).toBe('ftp://example.com');
    });

    it('starts again from the saved state after a save', async () => {
        await render();
        const saved = everyType();
        saved.settings[0] = { ...saved.settings[0], value: 'Lviv' };
        storage.updateSettings.mockReturnValueOnce(of(saved));
        const emitted: PluginSettingsResponse[] = [];
        fixture.componentInstance.saved.subscribe((response) => emitted.push(response));

        await type('city', 'Lviv');
        saveButton().click();
        await settle();

        expect(emitted).toEqual([saved]);
        expect(field('city').querySelector<HTMLInputElement>('input')!.value).toBe('Lviv');
        expect(saveButton().disabled).toBe(true);
    });

    it('labels every control: the text input by id, the select and the textarea by their own label', async () => {
        await render();

        const cityInput = field('city').querySelector<HTMLInputElement>('input')!;
        expect(field('city').querySelector('label')?.getAttribute('for')).toBe(cityInput.id);
        expect(cityInput.id).toBe('plugin-setting-city');
        expect(field('units').querySelector('app-select .tooltip-label-text')?.textContent?.trim()).toBe('Units');
        expect(field('notes').querySelector('app-textarea .tooltip-label-text')?.textContent?.trim()).toBe('Notes');
        expect(field('alerts').querySelector('input')?.getAttribute('aria-label')).toBe('Alerts');
    });

    it('saves a required setting the plugin waits for as it is shown, a toggle left Off included', async () => {
        const response = everyType();
        response.settings = response.settings.map((setting) =>
            setting.key === 'alerts' ? { ...setting, required: true, default: null } : setting
        );
        response.missing_required = ['endpoint', 'alerts'];
        await render(response);

        expect(saveButton().disabled).toBe(false);
        saveButton().click();

        expect(storage.updateSettings).toHaveBeenCalledWith('weather', { values: { alerts: false } });
    });

    it('saves what is picked for a setting that is not stored once it is touched, even the shown value', async () => {
        await render();
        const toggle = field('alerts').querySelector<HTMLInputElement>('input')!;

        toggle.click();
        await settle();
        toggle.click();
        await settle();
        saveButton().click();

        expect(storage.updateSettings).toHaveBeenCalledWith('weather', { values: { alerts: false } });
    });

    it('puts a stored setting back to its default with null, and Undo takes that back', async () => {
        await render();

        buttonIn(field('city'), 'Use default')!.click();
        await settle();
        expect(field('city').querySelector<HTMLInputElement>('input')!.disabled).toBe(true);
        expect(field('city').textContent).toContain('Goes back to the default when you save.');

        buttonIn(field('city'), 'Undo')!.click();
        await settle();
        expect(field('city').querySelector<HTMLInputElement>('input')!.value).toBe('Kyiv');
        expect(saveButton().disabled).toBe(true);

        buttonIn(field('city'), 'Use default')!.click();
        await settle();
        saveButton().click();

        expect(storage.updateSettings).toHaveBeenCalledWith('weather', { values: { city: null } });
    });

    it('offers no default for a secret or for a required setting without one', async () => {
        const response = everyType();
        response.settings = response.settings.map((setting) =>
            setting.key === 'endpoint' ? { ...setting, value: 'https://api.example.com', is_set: true } : setting
        );
        await render(response);

        expect(buttonIn(field('endpoint'), 'Use default')).toBeUndefined();
        expect(buttonIn(field('forecast_api_token'), 'Use default')).toBeUndefined();
    });

    it('drops a typed secret once it is saved', async () => {
        await render();
        buttonIn(field('forecast_api_token'), 'Replace')!.click();
        await settle();
        await type('forecast_api_token', 'new-secret-value');

        saveButton().click();
        await settle();

        expect(field('forecast_api_token').querySelector('input')).toBeNull();
        expect(saveButton().disabled).toBe(true);
        buttonIn(field('forecast_api_token'), 'Replace')!.click();
        await settle();
        expect(field('forecast_api_token').querySelector<HTMLInputElement>('input')!.value).toBe('');
    });
});
