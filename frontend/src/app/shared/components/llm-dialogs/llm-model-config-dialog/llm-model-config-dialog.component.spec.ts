import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { Component, forwardRef, input, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ControlValueAccessor, NG_VALUE_ACCESSOR } from '@angular/forms';
import { GetLlmConfigRequest, LLMModel, ReasoningEffort } from '@shared/models';
import {
    LlmConfigStorageService,
    LLMLibraryService,
    LlmModelsStorageService,
    LlmProvidersStorageService,
    SecretsStorageService,
} from '@shared/services';
import { EMPTY, Observable, of, Subject, throwError } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { JsonEditorFormFieldComponent } from '../../json-editor/json-editor-form-field.component';
import { LlmModelConfigDialogComponent } from './llm-model-config-dialog.component';

const REASONING_MODEL_ID = 1;
const PLAIN_MODEL_ID = 2;
const MISSING_MODEL_ID = 404;
const CONFIG_ID = 7;

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
            {
                provide: SecretsStorageService,
                useValue: {
                    secrets: signal([]),
                    getSecrets: () => of([]),
                    maskTail: () => '',
                } as unknown as SecretsStorageService,
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
