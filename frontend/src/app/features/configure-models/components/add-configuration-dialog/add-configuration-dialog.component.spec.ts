import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
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

import { ToastService } from '../../../../services/notifications';
import { ElevenLabsRealtimeConfigStorageService } from '../../services/llms/elevenlabs-realtime-config-storage.service';
import { GeminiRealtimeConfigStorageService } from '../../services/llms/gemini-realtime-config-storage.service';
import { OpenAIRealtimeConfigStorageService } from '../../services/llms/openai-realtime-config-storage.service';
import { AddConfigurationDialogComponent } from './add-configuration-dialog.component';

const REASONING_MODEL_ID = 1;
const PLAIN_MODEL_ID = 2;

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

function llmModel(id: number, supportsReasoning: boolean): LLMModel {
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
        supports_reasoning: supportsReasoning,
        llm_provider: 1,
    };
}

const MODELS = new Map<number, LLMModel>([
    [REASONING_MODEL_ID, llmModel(REASONING_MODEL_ID, true)],
    [PLAIN_MODEL_ID, llmModel(PLAIN_MODEL_ID, false)],
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

    it("shows the backend's message when creating the config fails", async () => {
        const message = 'reasoning_effort: this model does not support reasoning.';
        const createConfig = vi.fn(() => throwError(() => new HttpErrorResponse({ status: 400, error: { message } })));
        const { fixture, toastError } = await render(getCachedModelById, createConfig);
        await pickModel(fixture, PLAIN_MODEL_ID);

        fixture.componentInstance.onSubmit();

        expect(toastError).toHaveBeenCalledWith(message);
    });
});
