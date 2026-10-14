import { Component, computed, effect, inject, input, untracked } from '@angular/core';
import { rxResource, toObservable, toSignal } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { LLMModel, ModelTypes, REASONING_EFFORT_LABELS, ReasoningEffort } from '@shared/models';
import { LlmModelsStorageService, LlmProvidersStorageService } from '@shared/services';
import { map, startWith, switchMap } from 'rxjs';

import { ValidationErrorsComponent } from '../../app-validation-errors/validation-errors.component';
import { HintMessageComponent } from '../../hint-message/hint-message.component';
import { SelectComponent, SelectItem } from '../../select/select.component';

const REASONING_EFFORT_ITEMS: SelectItem<ReasoningEffort | null>[] = [
    { name: 'Provider default', value: null },
    ...(Object.entries(REASONING_EFFORT_LABELS) as [ReasoningEffort, string][]).map(([value, name]) => ({
        name,
        value,
    })),
];

/** Providers whose reasoning models ignore sampling settings depending on the effort. */
const OPENAI_API_PROVIDERS = new Set(['openai', 'azure']);

const OPENAI_HINT_WITH_NONE =
    'None keeps Temperature and Top P. Any other level makes OpenAI ignore Temperature (unless 1), Top P and the presence/frequency penalties.';
const OPENAI_HINT_ALWAYS_REASONS =
    'This model always reasons: OpenAI ignores Temperature (unless 1), Top P and the presence/frequency penalties.';

/** Key the backend's rejection of the effort is stored under on the control; `app-validation-errors` renders it. */
const SERVER_ERROR_KEY = 'server';

/**
 * Reasoning-effort select for an LLM config form. Shown only when the selected model supports reasoning; the
 * backend rejects a non-null value on any other model, so the value is cleared when the model turns out not to
 * support reasoning, and `submittedValue()` is null whenever the select is hidden. Every level is offered: which
 * ones a model accepts is decided by the backend, whose rejection the host passes to `showServerErrors()`. While
 * the model is still being looked up `resolving()` is true: the host must not save then, or a stored value would
 * be sent as null.
 */
@Component({
    selector: 'app-llm-reasoning-effort-field',
    templateUrl: './llm-reasoning-effort-field.component.html',
    styles: [':host { display: contents; }'],
    imports: [ReactiveFormsModule, SelectComponent, HintMessageComponent, ValidationErrorsComponent],
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
    private readonly supportedEfforts = computed<ReasoningEffort[]>(
        () => this.selectedModel()?.reasoning_efforts ?? []
    );
    protected readonly supportedEffortsHint = computed<string | null>(() => {
        const efforts = this.supportedEfforts();
        if (!efforts.length) return null;
        return `Supported by this model: ${efforts.map((effort) => REASONING_EFFORT_LABELS[effort] ?? effort).join(', ')}.`;
    });
    protected readonly usesOpenAiApi = computed(() => {
        const model = this.selectedModel();
        if (!model || !this.providersResource.hasValue()) return false;
        const provider = this.providersResource.value().find((candidate) => candidate.id === model.llm_provider);
        return !!provider && OPENAI_API_PROVIDERS.has(provider.name.toLowerCase());
    });
    /** Which sampling settings OpenAI drops for this model; null for other providers. */
    protected readonly openAiHint = computed<string | null>(() => {
        if (!this.usesOpenAiApi()) return null;
        return this.supportedEfforts().includes('none') ? OPENAI_HINT_WITH_NONE : OPENAI_HINT_ALWAYS_REASONS;
    });
    // The server error is set from outside on save; a signal of it lets this OnPush view render and drop it.
    protected readonly hasServerErrors = toSignal(
        toObservable(this.control).pipe(
            switchMap((control) =>
                control.statusChanges.pipe(
                    startWith(control.status),
                    map(() => control.hasError(SERVER_ERROR_KEY))
                )
            )
        ),
        { initialValue: false }
    );

    private readonly clearWhenUnsupported = effect(() => {
        const model = this.selectedModel();
        if (model && !model.supports_reasoning) {
            untracked(() => this.control().setValue(null));
        }
    });
    // The rejection was about the effort on the previous model, so drop it on model change or field re-creation (the
    // first run is intentional: it drops a stale error after the add dialog switches tabs). A new effort value
    // clears it on its own, as the control has no validators.
    private readonly clearServerErrorsOnModelChange = effect(() => {
        this.modelId();
        untracked(() => {
            const control = this.control();
            if (control.hasError(SERVER_ERROR_KEY)) control.updateValueAndValidity();
        });
    });

    protected readonly items = REASONING_EFFORT_ITEMS;

    private readonly llmModelsStorage = inject(LlmModelsStorageService);
    private readonly llmProvidersStorage = inject(LlmProvidersStorageService);

    /** The value to send to the API: the selected effort, or null while the select is hidden. */
    submittedValue(): ReasoningEffort | null {
        return this.supportsReasoning() ? this.control().value : null;
    }

    /**
     * Shows the backend's rejection of the effort under the select until the effort or the model changes. Returns
     * false, showing nothing, while the select is hidden: the host must then show the messages itself.
     */
    showServerErrors(messages: string[]): boolean {
        if (!this.supportsReasoning()) return false;
        const control = this.control();
        control.markAsTouched();
        control.setErrors({ [SERVER_ERROR_KEY]: messages });
        return true;
    }
}
