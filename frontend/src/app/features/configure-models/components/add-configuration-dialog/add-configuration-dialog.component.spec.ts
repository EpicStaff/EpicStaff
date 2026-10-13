import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { EmbeddingConfig } from '@shared/models';
import { EmbeddingConfigStorageService, LlmConfigStorageService, SecretsStorageService } from '@shared/services';
import { of, Subject } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { ElevenLabsRealtimeConfigStorageService } from '../../services/llms/elevenlabs-realtime-config-storage.service';
import { GeminiRealtimeConfigStorageService } from '../../services/llms/gemini-realtime-config-storage.service';
import { OpenAIRealtimeConfigStorageService } from '../../services/llms/openai-realtime-config-storage.service';
import { AddConfigurationDialogComponent } from './add-configuration-dialog.component';

/** Class logic only: the component is built without its template. */
describe('AddConfigurationDialogComponent embedding extra headers and LLM pricing', () => {
    let component: AddConfigurationDialogComponent;
    let createEmbeddingConfig: ReturnType<typeof vi.fn>;
    let createLlmConfig: ReturnType<typeof vi.fn>;

    beforeEach(() => {
        createEmbeddingConfig = vi.fn(() => of({}));
        createLlmConfig = vi.fn(() => of({}));

        TestBed.configureTestingModule({
            providers: [
                {
                    provide: DialogRef,
                    useValue: { keydownEvents: new Subject<KeyboardEvent>(), close: vi.fn() } as unknown as DialogRef,
                },
                { provide: DIALOG_DATA, useValue: { initialTab: 'embedding' } },
                {
                    provide: EmbeddingConfigStorageService,
                    useValue: {
                        configs: signal<EmbeddingConfig[]>([]),
                        createConfig: createEmbeddingConfig,
                    } as unknown as EmbeddingConfigStorageService,
                },
                {
                    provide: LlmConfigStorageService,
                    useValue: { createConfig: createLlmConfig } as unknown as LlmConfigStorageService,
                },
                { provide: OpenAIRealtimeConfigStorageService, useValue: {} as OpenAIRealtimeConfigStorageService },
                {
                    provide: ElevenLabsRealtimeConfigStorageService,
                    useValue: {} as ElevenLabsRealtimeConfigStorageService,
                },
                { provide: GeminiRealtimeConfigStorageService, useValue: {} as GeminiRealtimeConfigStorageService },
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
        component = TestBed.runInInjectionContext(() => new AddConfigurationDialogComponent());
        component.ngOnInit();
    });

    it('starts the embedding form with no extra headers', () => {
        expect(component.embeddingForm.controls.extra_headers.value).toEqual({});
    });

    it('sends the extra headers when creating an embedding configuration', () => {
        component.embeddingForm.setValue({
            model: 20,
            api_key_secret_id: 4,
            custom_name: '  proxy-embedder  ',
            extra_headers: { 'X-Proxy-Key': 'epicstaff_secret(PROXY_KEY)' },
        });

        component.onSubmit();

        expect(createEmbeddingConfig).toHaveBeenCalledWith({
            model: 20,
            api_key_secret_id: 4,
            custom_name: 'proxy-embedder',
            extra_headers: { 'X-Proxy-Key': 'epicstaff_secret(PROXY_KEY)' },
        });
    });

    describe('LLM pricing', () => {
        beforeEach(() => {
            component.setActiveTab('llm');
            component.llmForm.patchValue({ custom_name: 'gateway-llm', model: 11 });
        });

        it('sends both prices per token, converted from the per-1M values', () => {
            component.llmForm.patchValue({ pricing: { input_price_per_million: 2.5, output_price_per_million: 10 } });

            component.onSubmit();

            const request = createLlmConfig.mock.calls[0][0];
            expect(request.input_cost_per_token).toBe(2.5e-6);
            expect(request.output_cost_per_token).toBe(1e-5);
            expect(request).not.toHaveProperty('pricing');
        });

        it('sends null prices when both are left empty, meaning default pricing', () => {
            component.onSubmit();

            expect(createLlmConfig).toHaveBeenCalledWith(
                expect.objectContaining({ input_cost_per_token: null, output_cost_per_token: null })
            );
        });

        it('sends explicit 0 prices for a free model', () => {
            component.llmForm.patchValue({ pricing: { input_price_per_million: 0, output_price_per_million: 0 } });

            component.onSubmit();

            expect(createLlmConfig).toHaveBeenCalledWith(
                expect.objectContaining({ input_cost_per_token: 0, output_cost_per_token: 0 })
            );
        });

        it.each([
            { input_price_per_million: 2.5, output_price_per_million: null },
            { input_price_per_million: null, output_price_per_million: 10 },
        ])('blocks submit when only one price is set: %o', (pricing) => {
            component.llmForm.patchValue({ pricing });

            component.onSubmit();

            expect(component.llmForm.get('pricing')?.hasError('pricePair')).toBe(true);
            expect(createLlmConfig).not.toHaveBeenCalled();
        });

        it('blocks submit when a price is negative', () => {
            component.llmForm.patchValue({ pricing: { input_price_per_million: -1, output_price_per_million: 10 } });

            component.onSubmit();

            expect(component.llmForm.get('pricing.input_price_per_million')?.hasError('min')).toBe(true);
            expect(createLlmConfig).not.toHaveBeenCalled();
        });
    });
});
