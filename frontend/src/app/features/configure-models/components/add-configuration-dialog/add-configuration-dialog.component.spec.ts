import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse, HttpRequest } from '@angular/common/http';
import { Component, forwardRef, input, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ControlValueAccessor, NG_VALUE_ACCESSOR } from '@angular/forms';
import { JsonEditorFormFieldComponent } from '@shared/components';
import { EmbeddingConfig, LLMModel, ReasoningEffort } from '@shared/models';
import {
    EmbeddingConfigStorageService,
    LlmConfigStorageService,
    LLMLibraryService,
    LlmModelsStorageService,
    LlmProvidersStorageService,
    SecretsStorageService,
} from '@shared/services';
import { EMPTY, Observable, of, Subject, throwError } from 'rxjs';

import { validationErrorsInterceptor } from '../../../../core/interceptors/validation-errors.interceptor';
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

        it('reports an incomplete price pair so the save button can be disabled', () => {
            expect(component.hasIncompletePricePair()).toBe(false);

            component.llmForm.patchValue({ pricing: { input_price_per_million: 2.5, output_price_per_million: null } });
            expect(component.hasIncompletePricePair()).toBe(true);

            component.llmForm.patchValue({ pricing: { output_price_per_million: 10 } });
            expect(component.hasIncompletePricePair()).toBe(false);
        });

        it('reacts to typing as well as patchValue, and ignores other tabs', () => {
            const input = component.llmForm.get('pricing.input_price_per_million')!;

            input.setValue(1);
            expect(component.hasIncompletePricePair()).toBe(true);

            component.setActiveTab('embedding');
            expect(component.hasIncompletePricePair()).toBe(false);
        });

        it('marks the pair group touched once a field is dirty so the error shows without a blur', () => {
            const pricing = component.llmForm.get('pricing')!;
            component.llmForm.patchValue({ pricing: { input_price_per_million: 2.5 } });
            expect(pricing.touched).toBe(false);

            component.llmForm.get('pricing.input_price_per_million')!.markAsDirty();
            component.llmForm.patchValue({ pricing: { input_price_per_million: 3 } });

            expect(pricing.touched).toBe(true);
        });

        it('blocks submit when a price is negative', () => {
            component.llmForm.patchValue({ pricing: { input_price_per_million: -1, output_price_per_million: 10 } });

            component.onSubmit();

            expect(component.llmForm.get('pricing.input_price_per_million')?.hasError('min')).toBe(true);
            expect(createLlmConfig).not.toHaveBeenCalled();
        });
    });
});

const REASONING_MODEL_ID = 1;
const PLAIN_MODEL_ID = 2;
const ALWAYS_REASONING_MODEL_ID = 3;
const UNSUPPORTED_EFFORT_ERROR =
    "Model 'model-3' does not support reasoning effort 'xhigh'. Supported: minimal, low, medium, high.";

// jsdom has no ResizeObserver; app-button's overflow directive only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

/** Stands in for the Monaco-backed JSON editor, which does not run under jsdom. */
@Component({
    selector: 'app-json-editor-form-field',
    template: '',
    providers: [
        { provide: NG_VALUE_ACCESSOR, useExisting: forwardRef(() => JsonEditorFormFieldStubComponent), multi: true },
    ],
})
class JsonEditorFormFieldStubComponent implements ControlValueAccessor {
    readonly label = input('');
    readonly tooltipText = input('');
    readonly writeValueAsJSON = input(true);

    writeValue(): void {}
    registerOnChange(): void {}
    registerOnTouched(): void {}
}

function llmModel(id: number, reasoningEfforts: ReasoningEffort[]): LLMModel {
    return {
        id,
        name: `model-${id}`,
        description: null,
        base_url: null,
        deployment_id: null,
        api_version: null,
        is_visible: true,
        is_custom: false,
        predefined: true,
        supports_reasoning: reasoningEfforts.length > 0,
        reasoning_efforts: reasoningEfforts,
        llm_provider: 1,
    };
}

const MODELS = new Map<number, LLMModel>([
    [REASONING_MODEL_ID, llmModel(REASONING_MODEL_ID, ['none', 'low', 'medium', 'high', 'xhigh'])],
    [PLAIN_MODEL_ID, llmModel(PLAIN_MODEL_ID, [])],
    [ALWAYS_REASONING_MODEL_ID, llmModel(ALWAYS_REASONING_MODEL_ID, ['minimal', 'low', 'medium', 'high'])],
]);

function getCachedModelById(id: number): Observable<LLMModel> {
    const model = MODELS.get(id);
    return model ? of(model) : throwError(() => new Error('not found'));
}

/** Storages the embedding and realtime tabs save through; empty unless a test needs one. */
interface TabStorages {
    embeddingConfigStorage?: object;
    openaiRealtimeStorage?: object;
}

async function render(
    getModelById: (id: number) => Observable<LLMModel> = getCachedModelById,
    createConfig: ReturnType<typeof vi.fn> = vi.fn(() => EMPTY),
    tabStorages: TabStorages = {}
): Promise<{
    fixture: ComponentFixture<AddConfigurationDialogComponent>;
    createConfig: ReturnType<typeof vi.fn>;
    toastError: ReturnType<typeof vi.fn>;
}> {
    const toastError = vi.fn();
    TestBed.configureTestingModule({
        providers: [
            {
                provide: DialogRef,
                useValue: { keydownEvents: new Subject<KeyboardEvent>(), close: vi.fn() } as unknown as DialogRef,
            },
            { provide: DIALOG_DATA, useValue: { initialTab: 'llm' } },
            { provide: LlmConfigStorageService, useValue: { createConfig } as unknown as LlmConfigStorageService },
            {
                provide: LlmModelsStorageService,
                useValue: { getModelById } as unknown as LlmModelsStorageService,
            },
            {
                provide: LlmProvidersStorageService,
                useValue: { getProvidersByType: () => of([]) } as unknown as LlmProvidersStorageService,
            },
            { provide: LLMLibraryService, useValue: { loadModels: () => of([]) } as unknown as LLMLibraryService },
            {
                provide: SecretsStorageService,
                useValue: {
                    secrets: signal([]),
                    getSecrets: () => of([]),
                    maskTail: () => '',
                } as unknown as SecretsStorageService,
            },
            { provide: EmbeddingConfigStorageService, useValue: tabStorages.embeddingConfigStorage ?? {} },
            { provide: OpenAIRealtimeConfigStorageService, useValue: tabStorages.openaiRealtimeStorage ?? {} },
            { provide: ElevenLabsRealtimeConfigStorageService, useValue: {} },
            { provide: GeminiRealtimeConfigStorageService, useValue: {} },
            { provide: ToastService, useValue: { success: vi.fn(), error: toastError } as unknown as ToastService },
        ],
    });
    TestBed.overrideComponent(AddConfigurationDialogComponent, {
        remove: { imports: [JsonEditorFormFieldComponent] },
        add: { imports: [JsonEditorFormFieldStubComponent] },
    });
    const fixture = TestBed.createComponent(AddConfigurationDialogComponent);
    await settle(fixture);
    return { fixture, createConfig, toastError };
}

async function settle(fixture: ComponentFixture<AddConfigurationDialogComponent>): Promise<void> {
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
}

async function pickModel(fixture: ComponentFixture<AddConfigurationDialogComponent>, modelId: number): Promise<void> {
    fixture.componentInstance.llmForm.patchValue({ model: modelId, custom_name: 'reasoning config' });
    await settle(fixture);
}

function reasoningSelect(fixture: ComponentFixture<AddConfigurationDialogComponent>): HTMLElement | null {
    return (fixture.nativeElement as HTMLElement).querySelector('app-llm-reasoning-effort-field app-select');
}

function reasoningErrorText(fixture: ComponentFixture<AddConfigurationDialogComponent>): string {
    return (
        (fixture.nativeElement as HTMLElement).querySelector('app-llm-reasoning-effort-field app-validation-errors')
            ?.textContent ?? ''
    );
}

/** A 400 in the backend's validation envelope, passed through the interceptor the app registers. */
function validationErrorResponse(field: string, value: string, reason: string): Observable<never> {
    const response = new HttpErrorResponse({
        status: 400,
        error: {
            status_code: 400,
            code: 'validation_error',
            message: 'Invalid input.',
            errors: [{ field, value, reason }],
        },
    });
    return validationErrorsInterceptor(new HttpRequest('POST', '/api/llm-configs/', null), () =>
        throwError(() => response)
    ) as Observable<never>;
}

/** The 400 the backend sends when a write would change where a secret goes and the caller lacks Secrets "Use". */
const SECRET_USE_REFUSAL = new HttpErrorResponse({
    status: 400,
    error: {
        status_code: 400,
        code: 'invalid',
        message:
            'api_key_secret_id: Changing the secrets referenced here requires the "Use" permission on Secrets. ' +
            'The existing selection was left unchanged. Ask an organization admin to grant it.',
    },
});

/** The refusal as the banner shows it: the field label in words, the backend's sentence unchanged. */
const SHOWN_REFUSAL =
    'API key secret: Changing the secrets referenced here requires the "Use" permission on Secrets. ' +
    'The existing selection was left unchanged. Ask an organization admin to grant it.';

function unsupportedEffortResponse(): Observable<never> {
    return validationErrorResponse('reasoning_effort', 'xhigh', UNSUPPORTED_EFFORT_ERROR);
}

function bannerText(fixture: ComponentFixture<AddConfigurationDialogComponent>): string {
    const banner = (fixture.nativeElement as HTMLElement).querySelector<HTMLElement>('app-error-banner');
    return banner && !banner.hidden ? (banner.textContent ?? '').trim() : '';
}

function setReasoningEffort(fixture: ComponentFixture<AddConfigurationDialogComponent>, value: ReasoningEffort): void {
    fixture.componentInstance.llmForm.patchValue({ reasoning_effort: value });
}

describe('AddConfigurationDialogComponent LLM reasoning effort', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    it('hides the reasoning effort select for a model without reasoning support', async () => {
        const { fixture } = await render();

        await pickModel(fixture, PLAIN_MODEL_ID);

        expect(reasoningSelect(fixture)).toBeNull();
    });

    it('shows the reasoning effort select for a reasoning model', async () => {
        const { fixture } = await render();

        await pickModel(fixture, REASONING_MODEL_ID);

        expect(reasoningSelect(fixture)).not.toBeNull();
    });

    it('clears the reasoning effort when the model is swapped to one without reasoning support', async () => {
        const { fixture } = await render();
        await pickModel(fixture, REASONING_MODEL_ID);
        setReasoningEffort(fixture, 'high');

        await pickModel(fixture, PLAIN_MODEL_ID);

        expect(fixture.componentInstance.llmForm.get('reasoning_effort')!.value).toBeNull();
        expect(reasoningSelect(fixture)).toBeNull();
    });

    it('shows a rejected effort under the select, keeps the dialog open and clears it when the effort changes', async () => {
        const createConfig = vi.fn(() => unsupportedEffortResponse());
        const { fixture, toastError } = await render(getCachedModelById, createConfig);
        await pickModel(fixture, ALWAYS_REASONING_MODEL_ID);
        setReasoningEffort(fixture, 'xhigh');

        fixture.componentInstance.onSubmit();
        fixture.detectChanges();

        expect(createConfig).toHaveBeenCalledWith(expect.objectContaining({ reasoning_effort: 'xhigh' }));
        expect(reasoningErrorText(fixture)).toContain(UNSUPPORTED_EFFORT_ERROR);
        expect(toastError).not.toHaveBeenCalled();
        expect(TestBed.inject(DialogRef).close).not.toHaveBeenCalled();

        setReasoningEffort(fixture, 'high');
        fixture.detectChanges();

        expect(reasoningErrorText(fixture)).toBe('');
        expect(fixture.componentInstance.llmForm.valid).toBe(true);
    });

    it('clears a rejected effort error when the model changes', async () => {
        const createConfig = vi.fn(() => unsupportedEffortResponse());
        const { fixture } = await render(getCachedModelById, createConfig);
        await pickModel(fixture, ALWAYS_REASONING_MODEL_ID);
        setReasoningEffort(fixture, 'xhigh');
        fixture.componentInstance.onSubmit();
        fixture.detectChanges();
        expect(reasoningErrorText(fixture)).toContain(UNSUPPORTED_EFFORT_ERROR);

        await pickModel(fixture, REASONING_MODEL_ID);

        expect(reasoningErrorText(fixture)).toBe('');
        expect(fixture.componentInstance.llmForm.get('reasoning_effort')!.value).toBe('xhigh');
        expect(fixture.componentInstance.llmForm.valid).toBe(true);
    });

    it('creates the config with the selected reasoning effort for a reasoning model', async () => {
        const { fixture, createConfig } = await render();
        await pickModel(fixture, REASONING_MODEL_ID);
        setReasoningEffort(fixture, 'medium');

        fixture.componentInstance.onSubmit();

        expect(createConfig).toHaveBeenCalledWith(
            expect.objectContaining({ model: REASONING_MODEL_ID, reasoning_effort: 'medium' })
        );
    });

    it('creates the config with reasoning_effort null while the select is hidden', async () => {
        const { fixture, createConfig } = await render();
        await pickModel(fixture, PLAIN_MODEL_ID);

        fixture.componentInstance.onSubmit();

        expect(createConfig).toHaveBeenCalledWith(
            expect.objectContaining({ model: PLAIN_MODEL_ID, reasoning_effort: null })
        );
    });

    it('blocks creating until a newly picked model is resolved, then sends the chosen reasoning effort', async () => {
        const pendingModel = new Subject<LLMModel>();
        const { fixture, createConfig } = await render((id) =>
            id === REASONING_MODEL_ID ? pendingModel : getCachedModelById(id)
        );
        fixture.componentInstance.llmForm.patchValue({ model: REASONING_MODEL_ID, custom_name: 'reasoning config' });
        // The lookup stays in flight, so do not wait for the fixture to become stable.
        fixture.detectChanges();
        fixture.detectChanges();
        setReasoningEffort(fixture, 'low');

        expect(fixture.componentInstance.isLlmModelResolving()).toBe(true);
        fixture.componentInstance.onSubmit();
        expect(createConfig).not.toHaveBeenCalled();

        pendingModel.next(MODELS.get(REASONING_MODEL_ID)!);
        await settle(fixture);
        fixture.componentInstance.onSubmit();

        expect(createConfig).toHaveBeenCalledWith(
            expect.objectContaining({ model: REASONING_MODEL_ID, reasoning_effort: 'low' })
        );
    });

    it("shows the backend's reason in the banner when a field other than the effort is rejected", async () => {
        const reason = 'An LLM configuration with this name already exists.';
        const createConfig = vi.fn(() => validationErrorResponse('custom_name', 'model-3', reason));
        const { fixture, toastError } = await render(getCachedModelById, createConfig);
        await pickModel(fixture, ALWAYS_REASONING_MODEL_ID);

        fixture.componentInstance.onSubmit();
        fixture.detectChanges();

        expect(bannerText(fixture)).toBe(reason);
        expect(toastError).not.toHaveBeenCalled();
        expect(reasoningErrorText(fixture)).toBe('');
    });

    it('shows a rejected effort in the banner when the select is hidden', async () => {
        const reason = "Model 'model-2' does not support reasoning.";
        const createConfig = vi.fn(() => validationErrorResponse('reasoning_effort', 'high', reason));
        const { fixture } = await render(getCachedModelById, createConfig);
        await pickModel(fixture, PLAIN_MODEL_ID);

        fixture.componentInstance.onSubmit();
        fixture.detectChanges();

        expect(bannerText(fixture)).toBe(reason);
    });

    it('shows a secret Use refusal in the banner and keeps the dialog open', async () => {
        const createConfig = vi.fn(() => throwError(() => SECRET_USE_REFUSAL));
        const { fixture } = await render(getCachedModelById, createConfig);
        await pickModel(fixture, PLAIN_MODEL_ID);

        fixture.componentInstance.onSubmit();
        fixture.detectChanges();

        expect(bannerText(fixture)).toBe(SHOWN_REFUSAL);
        expect(TestBed.inject(DialogRef).close).not.toHaveBeenCalled();
    });

    it('clears the banner when the form is submitted again', async () => {
        const createConfig = vi
            .fn()
            .mockReturnValueOnce(throwError(() => SECRET_USE_REFUSAL))
            .mockReturnValueOnce(new Subject<never>());
        const { fixture } = await render(getCachedModelById, createConfig);
        await pickModel(fixture, PLAIN_MODEL_ID);
        fixture.componentInstance.onSubmit();
        fixture.detectChanges();
        expect(bannerText(fixture)).not.toBe('');

        fixture.componentInstance.onSubmit();
        fixture.detectChanges();

        expect(bannerText(fixture)).toBe('');
    });
});

const SERVER_ERROR = new HttpErrorResponse({
    status: 500,
    error: { status_code: 500, code: 'Exception', message: 'Unpredictable error' },
});

describe('AddConfigurationDialogComponent embedding and realtime save errors', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    function embeddingStorage(error: HttpErrorResponse): object {
        return { configs: signal<EmbeddingConfig[]>([]), createConfig: () => throwError(() => error) };
    }

    async function submitEmbedding(
        error: HttpErrorResponse
    ): Promise<ComponentFixture<AddConfigurationDialogComponent>> {
        const { fixture } = await render(undefined, undefined, { embeddingConfigStorage: embeddingStorage(error) });
        fixture.componentInstance.setActiveTab('embedding');
        fixture.componentInstance.embeddingForm.patchValue({ model: 20, api_key_secret_id: 4, custom_name: 'search' });
        fixture.componentInstance.onSubmit();
        fixture.detectChanges();
        return fixture;
    }

    async function submitRealtime(
        error: HttpErrorResponse
    ): Promise<ComponentFixture<AddConfigurationDialogComponent>> {
        const { fixture } = await render(undefined, undefined, {
            openaiRealtimeStorage: { createConfig: () => throwError(() => error) },
        });
        fixture.componentInstance.setActiveTab('realtime');
        fixture.componentInstance.openaiForm.patchValue({ custom_name: 'support-voice' });
        fixture.componentInstance.onSubmit();
        fixture.detectChanges();
        return fixture;
    }

    it('shows a refused embedding configuration in the banner', async () => {
        const fixture = await submitEmbedding(SECRET_USE_REFUSAL);

        expect(bannerText(fixture)).toBe(SHOWN_REFUSAL);
    });

    it('reports a server error on the embedding tab in a toast', async () => {
        const fixture = await submitEmbedding(SERVER_ERROR);

        expect(TestBed.inject(ToastService).error).toHaveBeenCalledWith('Failed to create embedding configuration.');
        expect(bannerText(fixture)).toBe('');
    });

    it('shows a refused realtime configuration in the banner', async () => {
        const fixture = await submitRealtime(SECRET_USE_REFUSAL);

        expect(bannerText(fixture)).toBe(SHOWN_REFUSAL);
    });

    it('keeps the generic banner text for a server error on the realtime tab', async () => {
        const fixture = await submitRealtime(SERVER_ERROR);

        expect(bannerText(fixture)).toBe('Failed to save configuration.');
    });
});
