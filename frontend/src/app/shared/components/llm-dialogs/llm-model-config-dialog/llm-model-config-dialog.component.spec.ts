import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse, HttpRequest } from '@angular/common/http';
import { Component, forwardRef, input, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ControlValueAccessor, FormGroup, NG_VALUE_ACCESSOR } from '@angular/forms';
import { GetLlmConfigRequest, LLMModel, ReasoningEffort } from '@shared/models';
import {
    LlmConfigStorageService,
    LLMLibraryService,
    LlmModelsStorageService,
    LlmProvidersStorageService,
    SecretsApiService,
    SecretsStorageService,
} from '@shared/services';
import { EMPTY, Observable, of, Subject, throwError } from 'rxjs';

import { validationErrorsInterceptor } from '../../../../core/interceptors/validation-errors.interceptor';
import { ToastService } from '../../../../services/notifications';
import { JsonEditorFormFieldComponent } from '../../json-editor/json-editor-form-field.component';
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
    reasoning_effort: null,
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

const REASONING_MODEL_ID = 1;
const PLAIN_MODEL_ID = 2;
const ALWAYS_REASONING_MODEL_ID = 3;
const MISSING_MODEL_ID = 404;
const CONFIG_ID = 7;
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

function storedConfig(model: number, reasoningEffort: ReasoningEffort | null): GetLlmConfigRequest {
    return {
        id: CONFIG_ID,
        custom_name: 'reasoning config',
        model,
        api_key_secret_id: null,
        temperature: null,
        top_p: null,
        stop: null,
        max_tokens: 4096,
        presence_penalty: 0,
        frequency_penalty: 0,
        logit_bias: null,
        seed: null,
        timeout: 120,
        reasoning_effort: reasoningEffort,
        is_visible: true,
        input_cost_per_token: null,
        output_cost_per_token: null,
        tags: [],
        created_at: null,
        created_by: null,
        last_edited_by: null,
        last_edited_at: null,
    };
}

interface Rendered {
    fixture: ComponentFixture<LlmModelConfigDialogComponent>;
    createConfig: ReturnType<typeof vi.fn>;
    updateConfig: ReturnType<typeof vi.fn>;
}

function getCachedModelById(id: number): Observable<LLMModel> {
    const model = MODELS.get(id);
    return model ? of(model) : throwError(() => new Error('not found'));
}

async function render(
    config?: GetLlmConfigRequest,
    getModelById: (id: number) => Observable<LLMModel> = getCachedModelById,
    // An in-flight model lookup keeps the fixture unstable, so a test holding one open must not wait for it.
    waitForLookup = true
): Promise<Rendered> {
    const createConfig = vi.fn(() => EMPTY);
    const updateConfig = vi.fn(() => EMPTY);
    TestBed.configureTestingModule({
        providers: [
            {
                provide: DialogRef,
                useValue: { keydownEvents: new Subject<KeyboardEvent>(), close: vi.fn() } as unknown as DialogRef,
            },
            { provide: DIALOG_DATA, useValue: config ? { configId: config.id } : {} },
            {
                provide: LlmConfigStorageService,
                useValue: {
                    getConfigById: () => (config ? of(config) : EMPTY),
                    createConfig,
                    updateConfig,
                } as unknown as LlmConfigStorageService,
            },
            {
                provide: LlmModelsStorageService,
                useValue: { getModelById } as unknown as LlmModelsStorageService,
            },
            {
                provide: LlmProvidersStorageService,
                useValue: { getProvidersByType: () => of([]) } as unknown as LlmProvidersStorageService,
            },
            { provide: LLMLibraryService, useValue: { loadModels: () => of([]) } as unknown as LLMLibraryService },
            // The real SecretsStorageService over a fake API: a hand-written storage fake falls behind whenever
            // the dialog starts using another storage method.
            {
                provide: SecretsApiService,
                useValue: {
                    getSecrets: () => of([]),
                    getBinnedSecrets: () => of([]),
                } as unknown as SecretsApiService,
            },
            { provide: ToastService, useValue: { success: vi.fn(), error: vi.fn() } as unknown as ToastService },
        ],
    });
    TestBed.overrideComponent(LlmModelConfigDialogComponent, {
        remove: { imports: [JsonEditorFormFieldComponent] },
        add: { imports: [JsonEditorFormFieldStubComponent] },
    });
    const fixture = TestBed.createComponent(LlmModelConfigDialogComponent);
    if (waitForLookup) {
        await settle(fixture);
    } else {
        fixture.detectChanges();
        fixture.detectChanges();
    }
    return { fixture, createConfig, updateConfig };
}

async function settle(fixture: ComponentFixture<LlmModelConfigDialogComponent>): Promise<void> {
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
}

async function pickModel(fixture: ComponentFixture<LlmModelConfigDialogComponent>, modelId: number): Promise<void> {
    fixture.componentInstance.form.patchValue({ model: modelId, custom_name: 'reasoning config' });
    await settle(fixture);
}

function reasoningSelect(fixture: ComponentFixture<LlmModelConfigDialogComponent>): HTMLElement | null {
    return (fixture.nativeElement as HTMLElement).querySelector('app-llm-reasoning-effort-field app-select');
}

function reasoningErrorText(fixture: ComponentFixture<LlmModelConfigDialogComponent>): string {
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
    return validationErrorsInterceptor(new HttpRequest('PUT', '/api/llm-configs/7/', null), () =>
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
            'model: Changing where this sends its secrets requires the "Use" permission on Secrets. ' +
            'The existing value was left unchanged. Ask an organization admin to grant it.',
    },
});

const SERVER_ERROR = new HttpErrorResponse({
    status: 500,
    error: { status_code: 500, code: 'Exception', message: 'Unpredictable error' },
});

function bannerText(fixture: ComponentFixture<LlmModelConfigDialogComponent>): string {
    const banner = (fixture.nativeElement as HTMLElement).querySelector<HTMLElement>('app-error-banner');
    return banner && !banner.hidden ? (banner.textContent ?? '').trim() : '';
}

function unsupportedEffortResponse(): Observable<never> {
    return validationErrorResponse('reasoning_effort', 'xhigh', UNSUPPORTED_EFFORT_ERROR);
}

function reasoningControlValue(fixture: ComponentFixture<LlmModelConfigDialogComponent>): ReasoningEffort | null {
    return fixture.componentInstance.form.get('reasoning_effort')!.value;
}

describe('LlmModelConfigDialogComponent reasoning effort', () => {
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
        fixture.componentInstance.form.patchValue({ reasoning_effort: 'high' });

        await pickModel(fixture, PLAIN_MODEL_ID);

        expect(reasoningControlValue(fixture)).toBeNull();
        expect(reasoningSelect(fixture)).toBeNull();
    });

    it('keeps a stored effort the model does not list on open and sends it on save', async () => {
        const { fixture, updateConfig } = await render(storedConfig(ALWAYS_REASONING_MODEL_ID, 'xhigh'));

        expect(reasoningControlValue(fixture)).toBe('xhigh');
        expect(reasoningSelect(fixture)!.textContent).toContain('Extra high');
        fixture.componentInstance.onSave();

        expect(updateConfig).toHaveBeenCalledWith(
            expect.objectContaining({ id: CONFIG_ID, reasoning_effort: 'xhigh' })
        );
    });

    it('shows a rejected effort under the select, keeps the dialog open and clears it when the effort changes', async () => {
        const { fixture, updateConfig } = await render(storedConfig(ALWAYS_REASONING_MODEL_ID, 'xhigh'));
        updateConfig.mockReturnValueOnce(unsupportedEffortResponse());

        fixture.componentInstance.onSave();
        fixture.detectChanges();

        expect(reasoningErrorText(fixture)).toContain(UNSUPPORTED_EFFORT_ERROR);
        expect(bannerText(fixture)).toBe('');
        expect(TestBed.inject(DialogRef).close).not.toHaveBeenCalled();
        expect(saveButton(fixture).disabled).toBe(true);

        fixture.componentInstance.form.patchValue({ reasoning_effort: 'high' });
        fixture.detectChanges();

        expect(reasoningErrorText(fixture)).toBe('');
        expect(saveButton(fixture).disabled).toBe(false);
    });

    it('clears a rejected effort error when the model changes', async () => {
        const { fixture, updateConfig } = await render(storedConfig(ALWAYS_REASONING_MODEL_ID, 'xhigh'));
        updateConfig.mockReturnValueOnce(unsupportedEffortResponse());
        fixture.componentInstance.onSave();
        fixture.detectChanges();
        expect(reasoningErrorText(fixture)).toContain(UNSUPPORTED_EFFORT_ERROR);

        await pickModel(fixture, REASONING_MODEL_ID);

        expect(reasoningErrorText(fixture)).toBe('');
        expect(reasoningControlValue(fixture)).toBe('xhigh');
        expect(saveButton(fixture).disabled).toBe(false);
    });

    it('shows a 400 about another field in the banner, not under the reasoning effort select', async () => {
        const { fixture, updateConfig } = await render(storedConfig(ALWAYS_REASONING_MODEL_ID, 'high'));
        const reason = 'An LLM configuration with this name already exists.';
        updateConfig.mockReturnValueOnce(validationErrorResponse('custom_name', 'model-3', reason));

        fixture.componentInstance.onSave();
        fixture.detectChanges();

        expect(bannerText(fixture)).toBe(reason);
        expect(reasoningErrorText(fixture)).toBe('');
    });

    it('shows a secret Use refusal in the banner as a sentence, with the field label in words', async () => {
        const { fixture, updateConfig } = await render(storedConfig(ALWAYS_REASONING_MODEL_ID, 'high'));
        updateConfig.mockReturnValueOnce(throwError(() => SECRET_USE_REFUSAL));

        fixture.componentInstance.onSave();
        fixture.detectChanges();

        expect(bannerText(fixture)).toBe(
            'Model: Changing where this sends its secrets requires the "Use" permission on Secrets. ' +
                'The existing value was left unchanged. Ask an organization admin to grant it.'
        );
        expect(TestBed.inject(DialogRef).close).not.toHaveBeenCalled();
    });

    it('clears the banner when the form is submitted again', async () => {
        const { fixture, updateConfig } = await render(storedConfig(ALWAYS_REASONING_MODEL_ID, 'high'));
        updateConfig.mockReturnValueOnce(throwError(() => SECRET_USE_REFUSAL));
        fixture.componentInstance.onSave();
        fixture.detectChanges();
        expect(bannerText(fixture)).not.toBe('');

        fixture.componentInstance.onSave();
        fixture.detectChanges();

        expect(bannerText(fixture)).toBe('');
    });

    it('shows a server error in the banner too', async () => {
        const { fixture, updateConfig } = await render(storedConfig(ALWAYS_REASONING_MODEL_ID, 'high'));
        updateConfig.mockReturnValueOnce(throwError(() => SERVER_ERROR));

        fixture.componentInstance.onSave();
        fixture.detectChanges();

        expect(bannerText(fixture)).toBe('Unpredictable error');
    });

    it('resolves the stored model by id in edit mode and shows the stored reasoning effort', async () => {
        const { fixture } = await render(storedConfig(REASONING_MODEL_ID, 'medium'));

        expect(reasoningSelect(fixture)).not.toBeNull();
        expect(reasoningSelect(fixture)!.textContent).toContain('Medium');
    });

    it('sends the selected reasoning effort when the select is shown', async () => {
        const { fixture, updateConfig } = await render(storedConfig(REASONING_MODEL_ID, 'low'));

        fixture.componentInstance.onSave();

        expect(updateConfig).toHaveBeenCalledWith(expect.objectContaining({ id: CONFIG_ID, reasoning_effort: 'low' }));
    });

    it('sends reasoning_effort null when the stored model cannot be resolved and the select is hidden', async () => {
        const { fixture, updateConfig } = await render(storedConfig(MISSING_MODEL_ID, 'high'));

        expect(reasoningSelect(fixture)).toBeNull();
        fixture.componentInstance.onSave();

        expect(updateConfig).toHaveBeenCalledWith(expect.objectContaining({ id: CONFIG_ID, reasoning_effort: null }));
    });

    it('sends reasoning_effort null when creating a config on a model without reasoning support', async () => {
        const { fixture, createConfig } = await render();
        await pickModel(fixture, PLAIN_MODEL_ID);

        fixture.componentInstance.onSave();

        expect(createConfig).toHaveBeenCalledWith(expect.objectContaining({ reasoning_effort: null }));
    });

    it('blocks saving until the stored model is resolved, then sends the stored reasoning effort', async () => {
        const pendingModel = new Subject<LLMModel>();
        const { fixture, updateConfig } = await render(
            storedConfig(REASONING_MODEL_ID, 'high'),
            () => pendingModel,
            false
        );

        expect(fixture.componentInstance.isModelResolving()).toBe(true);
        expect(saveButton(fixture).disabled).toBe(true);
        fixture.componentInstance.onSave();
        expect(updateConfig).not.toHaveBeenCalled();

        pendingModel.next(MODELS.get(REASONING_MODEL_ID)!);
        await settle(fixture);

        expect(saveButton(fixture).disabled).toBe(false);
        fixture.componentInstance.onSave();
        expect(updateConfig).toHaveBeenCalledWith(expect.objectContaining({ id: CONFIG_ID, reasoning_effort: 'high' }));
    });
});

function saveButton(fixture: ComponentFixture<LlmModelConfigDialogComponent>): HTMLButtonElement {
    const buttons = (fixture.nativeElement as HTMLElement).querySelectorAll<HTMLButtonElement>(
        '.footer app-button button'
    );
    return buttons[buttons.length - 1];
}
