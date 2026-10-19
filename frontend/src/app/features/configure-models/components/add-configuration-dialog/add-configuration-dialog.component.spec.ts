import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse, HttpRequest } from '@angular/common/http';
import { Component, forwardRef, input, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ControlValueAccessor, NG_VALUE_ACCESSOR } from '@angular/forms';
import { JsonEditorFormFieldComponent } from '@shared/components';
import { LLMModel, ReasoningEffort } from '@shared/models';
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

async function render(
    getModelById: (id: number) => Observable<LLMModel> = getCachedModelById,
    createConfig: ReturnType<typeof vi.fn> = vi.fn(() => EMPTY)
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
            { provide: EmbeddingConfigStorageService, useValue: {} },
            { provide: OpenAIRealtimeConfigStorageService, useValue: {} },
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

function unsupportedEffortResponse(): Observable<never> {
    return validationErrorResponse('reasoning_effort', 'xhigh', UNSUPPORTED_EFFORT_ERROR);
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

    it("shows the backend's reason in a toast when a field other than the effort is rejected", async () => {
        const reason = 'An LLM configuration with this name already exists.';
        const createConfig = vi.fn(() => validationErrorResponse('custom_name', 'model-3', reason));
        const { fixture, toastError } = await render(getCachedModelById, createConfig);
        await pickModel(fixture, ALWAYS_REASONING_MODEL_ID);

        fixture.componentInstance.onSubmit();
        fixture.detectChanges();

        expect(toastError).toHaveBeenCalledWith(reason);
        expect(reasoningErrorText(fixture)).toBe('');
    });

    it('shows a rejected effort in a toast when the select is hidden', async () => {
        const reason = "Model 'model-2' does not support reasoning.";
        const createConfig = vi.fn(() => validationErrorResponse('reasoning_effort', 'high', reason));
        const { fixture, toastError } = await render(getCachedModelById, createConfig);
        await pickModel(fixture, PLAIN_MODEL_ID);

        fixture.componentInstance.onSubmit();

        expect(toastError).toHaveBeenCalledWith(reason);
    });
});
