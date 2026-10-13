import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { FormGroup } from '@angular/forms';
import { GetLlmConfigRequest } from '@shared/models';
import { LlmConfigStorageService, SecretsStorageService } from '@shared/services';
import { of, Subject } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { LlmModelConfigDialogComponent } from './llm-model-config-dialog.component';

const EDITED_CONFIG: GetLlmConfigRequest = {
    id: 3,
    custom_name: 'gateway-llm',
    model: 11,
    api_key_secret_id: 4,
    temperature: 0.5,
    top_p: 1,
    stop: null,
    max_tokens: 4096,
    presence_penalty: 0,
    frequency_penalty: 0,
    logit_bias: null,
    seed: null,
    timeout: 120,
    is_visible: true,
    extra_headers: {},
    input_cost_per_token: 2.5e-6,
    output_cost_per_token: 1e-5,
    tags: [],
    created_at: '2026-04-01T08:00:00Z',
    created_by: null,
    last_edited_by: null,
    last_edited_at: null,
};

/** Class logic only: the component is built without its template. */
describe('LlmModelConfigDialogComponent pricing', () => {
    let createConfig: ReturnType<typeof vi.fn>;
    let updateConfig: ReturnType<typeof vi.fn>;

    function createComponent(
        dialogData: { configId?: number } | null,
        loadedConfig: GetLlmConfigRequest = EDITED_CONFIG
    ): LlmModelConfigDialogComponent {
        createConfig = vi.fn(() => of(EDITED_CONFIG));
        updateConfig = vi.fn(() => of(EDITED_CONFIG));

        TestBed.configureTestingModule({
            providers: [
                {
                    provide: DialogRef,
                    useValue: { keydownEvents: new Subject<KeyboardEvent>(), close: vi.fn() } as unknown as DialogRef,
                },
                { provide: DIALOG_DATA, useValue: dialogData },
                {
                    provide: LlmConfigStorageService,
                    useValue: {
                        getConfigById: () => of(loadedConfig),
                        createConfig,
                        updateConfig,
                    } as unknown as LlmConfigStorageService,
                },
                {
                    provide: SecretsStorageService,
                    useValue: {
                        secrets: signal([]),
                        getSecrets: () => of([]),
                        maskTail: (tail: string) => tail,
                    } as unknown as SecretsStorageService,
                },
                {
                    provide: ToastService,
                    useValue: { success: vi.fn(), error: vi.fn() } as unknown as ToastService,
                },
            ],
        });
        const component = TestBed.runInInjectionContext(() => new LlmModelConfigDialogComponent());
        component.ngOnInit();
        return component;
    }

    /** Sets the prices the way the user does: through the inputs, which marks them dirty. */
    function typePrices(
        component: LlmModelConfigDialogComponent,
        pricing: { input_price_per_million: number | null; output_price_per_million: number | null }
    ): void {
        const pricingGroup = component.form.get('pricing')!;
        pricingGroup.setValue(pricing);
        pricingGroup.markAsDirty();
        Object.values((pricingGroup as FormGroup).controls).forEach((control) => control.markAsDirty());
    }

    it('prefills the edited prices per 1M tokens, without float noise', () => {
        const component = createComponent({ configId: EDITED_CONFIG.id });

        expect(component.form.get('pricing')?.value).toEqual({
            input_price_per_million: 2.5,
            output_price_per_million: 10,
        });
    });

    it('prefills empty prices when the configuration uses default pricing', () => {
        const component = createComponent(
            { configId: EDITED_CONFIG.id },
            { ...EDITED_CONFIG, input_cost_per_token: null, output_cost_per_token: null }
        );

        expect(component.form.get('pricing')?.value).toEqual({
            input_price_per_million: null,
            output_price_per_million: null,
        });
    });

    it('sends the edited prices per token, never per 1M tokens', () => {
        const component = createComponent({ configId: EDITED_CONFIG.id });
        typePrices(component, { input_price_per_million: 3.3, output_price_per_million: 15 });

        component.onSave();

        const request = updateConfig.mock.calls[0][0];
        expect(request.id).toBe(EDITED_CONFIG.id);
        expect(request.input_cost_per_token).toBe(3.3e-6);
        expect(request.output_cost_per_token).toBe(1.5e-5);
        expect(request).not.toHaveProperty('pricing');
    });

    it('sends untouched prices back exactly as stored when only the name is edited', () => {
        // More significant digits than the per-1M display keeps: converting would change them.
        const storedPrices = { input_cost_per_token: 3.3e-6, output_cost_per_token: 1.2345678912345678e-7 };
        const component = createComponent({ configId: EDITED_CONFIG.id }, { ...EDITED_CONFIG, ...storedPrices });
        component.form.get('custom_name')!.setValue('renamed-llm');
        component.form.get('custom_name')!.markAsDirty();

        component.onSave();

        const request = updateConfig.mock.calls[0][0];
        expect(request.custom_name).toBe('renamed-llm');
        expect(request.input_cost_per_token).toBe(storedPrices.input_cost_per_token);
        expect(request.output_cost_per_token).toBe(storedPrices.output_cost_per_token);
    });

    it('sends null prices when both are cleared, meaning default pricing', () => {
        const component = createComponent({ configId: EDITED_CONFIG.id });
        typePrices(component, { input_price_per_million: null, output_price_per_million: null });

        component.onSave();

        expect(updateConfig).toHaveBeenCalledWith(
            expect.objectContaining({ input_cost_per_token: null, output_cost_per_token: null })
        );
    });

    it('sends per-token prices when creating a configuration', () => {
        const component = createComponent(null);
        component.form.patchValue({
            custom_name: 'free-llm',
            model: 11,
            pricing: { input_price_per_million: 0, output_price_per_million: 0 },
        });

        component.onSave();

        expect(createConfig).toHaveBeenCalledWith(
            expect.objectContaining({ input_cost_per_token: 0, output_cost_per_token: 0 })
        );
    });

    it.each([
        { input_price_per_million: 2.5, output_price_per_million: null },
        { input_price_per_million: null, output_price_per_million: 10 },
    ])('blocks saving when only one price is set: %o', (pricing) => {
        const component = createComponent({ configId: EDITED_CONFIG.id });
        component.form.patchValue({ pricing });

        component.onSave();

        expect(component.form.get('pricing')?.hasError('pricePair')).toBe(true);
        expect(updateConfig).not.toHaveBeenCalled();
    });

    it('blocks saving when a price is negative', () => {
        const component = createComponent({ configId: EDITED_CONFIG.id });
        component.form.patchValue({ pricing: { input_price_per_million: 2.5, output_price_per_million: -1 } });

        component.onSave();

        expect(component.form.get('pricing.output_price_per_million')?.hasError('min')).toBe(true);
        expect(updateConfig).not.toHaveBeenCalled();
    });
});
