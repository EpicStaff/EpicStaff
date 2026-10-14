import { Component, computed, effect, inject, input, untracked } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { LLMModel, ModelTypes, REASONING_EFFORT_LABELS, ReasoningEffort } from '@shared/models';
import { LlmModelsStorageService, LlmProvidersStorageService } from '@shared/services';

import { HintMessageComponent } from '../../hint-message/hint-message.component';
import { SelectComponent, SelectItem } from '../../select/select.component';

const REASONING_EFFORT_ITEMS: SelectItem<ReasoningEffort | null>[] = [
    { name: 'Provider default', value: null },
    ...(Object.entries(REASONING_EFFORT_LABELS) as [ReasoningEffort, string][]).map(([value, name]) => ({
        name,
        value,
    })),
];

/** Providers whose reasoning models switch between Chat Completions and the Responses API by effort. */
const OPENAI_API_PROVIDERS = new Set(['openai', 'azure']);

/**
 * Reasoning-effort select for an LLM config form. Shown only when the selected model supports reasoning; the
 * backend rejects a non-null value on any other model, so the value is cleared when the model turns out not to
 * support it, and `submittedValue()` is null whenever the select is hidden. While the model is still being looked
 * up `resolving()` is true: the host must not save then, or a stored value would be sent as null.
 */
@Component({
    selector: 'app-llm-reasoning-effort-field',
    templateUrl: './llm-reasoning-effort-field.component.html',
    styles: [':host { display: contents; }'],
    imports: [ReactiveFormsModule, SelectComponent, HintMessageComponent],
})
export class LlmReasoningEffortFieldComponent {
    readonly control = input.required<FormControl<ReasoningEffort | null>>();
    readonly modelId = input<number | null>(null);

    private readonly modelResource = rxResource({
        params: () => this.modelId() ?? undefined,
        stream: ({ params }) => this.llmModelsStorage.getModelById(params),
    });
    private readonly providersResource = rxResource({
        stream: () => this.llmProvidersStorage.getProvidersByType(ModelTypes.LLM),
    });
    // The resource can still hold the previous model while the new one loads; only trust the one asked for.
    private readonly selectedModel = computed<LLMModel | null>(() => {
        if (!this.modelResource.hasValue()) return null;
        const model = this.modelResource.value();
        return model.id === this.modelId() ? model : null;
    });
    readonly supportsReasoning = computed(() => this.selectedModel()?.supports_reasoning === true);
    /** A model is selected but not known yet. A failed lookup is not resolving: the select stays hidden. */
    readonly resolving = computed(
        () => this.modelId() !== null && this.selectedModel() === null && this.modelResource.status() !== 'error'
    );
    protected readonly usesOpenAiApi = computed(() => {
        const model = this.selectedModel();
        if (!model || !this.providersResource.hasValue()) return false;
        const provider = this.providersResource.value().find((candidate) => candidate.id === model.llm_provider);
        return !!provider && OPENAI_API_PROVIDERS.has(provider.name.toLowerCase());
    });

    private readonly clearWhenUnsupported = effect(() => {
        const model = this.selectedModel();
        if (model && !model.supports_reasoning) {
            untracked(() => this.control().setValue(null));
        }
    });

    protected readonly items = REASONING_EFFORT_ITEMS;

    private readonly llmModelsStorage = inject(LlmModelsStorageService);
    private readonly llmProvidersStorage = inject(LlmProvidersStorageService);

    /** The value to send to the API: the selected effort, or null while the select is hidden. */
    submittedValue(): ReasoningEffort | null {
        return this.supportsReasoning() ? this.control().value : null;
    }
}
