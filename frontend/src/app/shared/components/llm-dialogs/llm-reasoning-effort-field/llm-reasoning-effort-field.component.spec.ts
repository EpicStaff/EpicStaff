import { OverlayContainer } from '@angular/cdk/overlay';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormControl } from '@angular/forms';
import { LLMModel, LLMProvider, ReasoningEffort } from '@shared/models';
import { LlmModelsStorageService, LlmProvidersStorageService } from '@shared/services';
import { Observable, of, Subject, throwError } from 'rxjs';

import { LlmReasoningEffortFieldComponent } from './llm-reasoning-effort-field.component';

const OPENAI_PROVIDER_ID = 1;
const ANTHROPIC_PROVIDER_ID = 2;
const AZURE_PROVIDER_ID = 3;

const REASONING_MODEL_ID = 1;
const PLAIN_MODEL_ID = 2;
const ANTHROPIC_REASONING_MODEL_ID = 3;
const AZURE_REASONING_MODEL_ID = 4;
const MISSING_MODEL_ID = 404;

const PROVIDERS: LLMProvider[] = [
    { id: OPENAI_PROVIDER_ID, name: 'openai' },
    { id: ANTHROPIC_PROVIDER_ID, name: 'anthropic' },
    { id: AZURE_PROVIDER_ID, name: 'azure' },
];

const GENERIC_HINT = 'Higher effort is slower and costs more';
const OPENAI_HINT = 'keeps tool calls on Chat Completions';

function llmModel(id: number, supportsReasoning: boolean, provider = OPENAI_PROVIDER_ID): LLMModel {
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
        llm_provider: provider,
    };
}

const MODELS = new Map<number, LLMModel>([
    [REASONING_MODEL_ID, llmModel(REASONING_MODEL_ID, true)],
    [PLAIN_MODEL_ID, llmModel(PLAIN_MODEL_ID, false)],
    [ANTHROPIC_REASONING_MODEL_ID, llmModel(ANTHROPIC_REASONING_MODEL_ID, true, ANTHROPIC_PROVIDER_ID)],
    [AZURE_REASONING_MODEL_ID, llmModel(AZURE_REASONING_MODEL_ID, true, AZURE_PROVIDER_ID)],
]);

function getCachedModelById(id: number): Observable<LLMModel> {
    const model = MODELS.get(id);
    return model ? of(model) : throwError(() => new Error('not found'));
}

async function render(
    modelId: number | null,
    value: ReasoningEffort | null = null,
    getModelById: (id: number) => Observable<LLMModel> = getCachedModelById,
    waitForLookup = true
): Promise<{
    fixture: ComponentFixture<LlmReasoningEffortFieldComponent>;
    control: FormControl<ReasoningEffort | null>;
}> {
    TestBed.configureTestingModule({
        providers: [
            { provide: LlmModelsStorageService, useValue: { getModelById } },
            { provide: LlmProvidersStorageService, useValue: { getProvidersByType: () => of(PROVIDERS) } },
        ],
    });
    const control = new FormControl<ReasoningEffort | null>(value);
    const fixture = TestBed.createComponent(LlmReasoningEffortFieldComponent);
    fixture.componentRef.setInput('control', control);
    fixture.componentRef.setInput('modelId', modelId);
    if (waitForLookup) {
        await settle(fixture);
    } else {
        refresh(fixture);
    }
    return { fixture, control };
}

/** Runs change detection without waiting for stability, which an in-flight model lookup would hold off. */
function refresh(fixture: ComponentFixture<LlmReasoningEffortFieldComponent>): void {
    fixture.detectChanges();
    fixture.detectChanges();
}

async function settle(fixture: ComponentFixture<LlmReasoningEffortFieldComponent>): Promise<void> {
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
}

function select(fixture: ComponentFixture<LlmReasoningEffortFieldComponent>): HTMLElement | null {
    return (fixture.nativeElement as HTMLElement).querySelector('app-select');
}

function hintText(fixture: ComponentFixture<LlmReasoningEffortFieldComponent>): string {
    return (fixture.nativeElement as HTMLElement).querySelector('app-hint-message')?.textContent ?? '';
}

describe('LlmReasoningEffortFieldComponent', () => {
    it('stays hidden and submits null for a model without reasoning support', async () => {
        const { fixture } = await render(PLAIN_MODEL_ID);

        expect(select(fixture)).toBeNull();
        expect(fixture.componentInstance.submittedValue()).toBeNull();
    });

    it('shows the select for a reasoning model and offers provider default plus every effort', async () => {
        const { fixture } = await render(REASONING_MODEL_ID);

        expect(select(fixture)).not.toBeNull();
        select(fixture)!.querySelector<HTMLButtonElement>('button')!.click();
        fixture.detectChanges();
        const options = Array.from(
            TestBed.inject(OverlayContainer).getContainerElement().querySelectorAll('.selector__option .selector__text')
        ).map((option) => option.textContent?.trim());

        expect(options).toEqual(['Provider default', 'None', 'Low', 'Medium', 'High']);
    });

    it('keeps a stored value for a reasoning model and submits it', async () => {
        const { fixture, control } = await render(REASONING_MODEL_ID, 'high');

        expect(control.value).toBe('high');
        expect(fixture.componentInstance.submittedValue()).toBe('high');
    });

    it('clears the value when the model is swapped to one without reasoning support', async () => {
        const { fixture, control } = await render(REASONING_MODEL_ID, 'medium');

        fixture.componentRef.setInput('modelId', PLAIN_MODEL_ID);
        await settle(fixture);

        expect(control.value).toBeNull();
        expect(select(fixture)).toBeNull();
    });

    it('hides the select and submits null while the model cannot be resolved, without discarding the value', async () => {
        const { fixture, control } = await render(MISSING_MODEL_ID, 'low');

        expect(select(fixture)).toBeNull();
        expect(fixture.componentInstance.submittedValue()).toBeNull();
        expect(fixture.componentInstance.resolving()).toBe(false);
        expect(control.value).toBe('low');
    });

    it('submits null and is not resolving when no model is selected', async () => {
        const { fixture } = await render(null, 'low');

        expect(fixture.componentInstance.submittedValue()).toBeNull();
        expect(fixture.componentInstance.resolving()).toBe(false);
    });

    it('reports resolving until the selected model arrives, then shows the stored value', async () => {
        const pending = new Subject<LLMModel>();
        const { fixture, control } = await render(REASONING_MODEL_ID, 'high', () => pending, false);

        expect(fixture.componentInstance.resolving()).toBe(true);
        expect(select(fixture)).toBeNull();

        pending.next(MODELS.get(REASONING_MODEL_ID)!);
        await settle(fixture);

        expect(fixture.componentInstance.resolving()).toBe(false);
        expect(select(fixture)).not.toBeNull();
        expect(control.value).toBe('high');
    });

    it('hides the select at once when swapped to a plain model whose lookup is still in flight', async () => {
        const lookups = new Map<number, Subject<LLMModel>>();
        const deferred = (id: number): Observable<LLMModel> => {
            const lookup = lookups.get(id) ?? new Subject<LLMModel>();
            lookups.set(id, lookup);
            return lookup;
        };
        const { fixture, control } = await render(REASONING_MODEL_ID, 'medium', deferred, false);
        lookups.get(REASONING_MODEL_ID)!.next(MODELS.get(REASONING_MODEL_ID)!);
        await settle(fixture);
        expect(select(fixture)).not.toBeNull();

        fixture.componentRef.setInput('modelId', PLAIN_MODEL_ID);
        refresh(fixture);

        expect(select(fixture)).toBeNull();
        expect(fixture.componentInstance.submittedValue()).toBeNull();
        expect(fixture.componentInstance.resolving()).toBe(true);
        expect(control.value).toBe('medium');

        lookups.get(PLAIN_MODEL_ID)!.next(MODELS.get(PLAIN_MODEL_ID)!);
        await settle(fixture);

        expect(fixture.componentInstance.resolving()).toBe(false);
        expect(control.value).toBeNull();
    });

    it('shows the generic hint and the OpenAI API hint for an OpenAI reasoning model', async () => {
        const { fixture } = await render(REASONING_MODEL_ID);

        expect(hintText(fixture)).toContain(GENERIC_HINT);
        expect(hintText(fixture)).toContain(OPENAI_HINT);
    });

    it('shows the OpenAI API hint for an Azure reasoning model', async () => {
        const { fixture } = await render(AZURE_REASONING_MODEL_ID);

        expect(hintText(fixture)).toContain(OPENAI_HINT);
    });

    it('shows only the generic hint for a reasoning model of another provider', async () => {
        const { fixture } = await render(ANTHROPIC_REASONING_MODEL_ID);

        expect(hintText(fixture)).toContain(GENERIC_HINT);
        expect(hintText(fixture)).not.toContain(OPENAI_HINT);
    });
});
