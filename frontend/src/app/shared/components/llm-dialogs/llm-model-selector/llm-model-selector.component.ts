import { Dialog } from '@angular/cdk/dialog';
import { ComponentType } from '@angular/cdk/portal';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    forwardRef,
    inject,
    input,
    model,
    output,
    signal,
} from '@angular/core';
import { rxResource, takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ControlValueAccessor, NG_VALUE_ACCESSOR } from '@angular/forms';
import { LLMModel, LLMProvider, ModelTypes } from '@shared/models';
import { LLMLibraryService, ProviderWithModels } from '@shared/services';
import { getProviderIconPath } from '@shared/utils';

import { AppSvgIconComponent } from '../../app-svg-icon/app-svg-icon.component';
import { ButtonComponent, IconButtonComponent } from '../../buttons';
import {
    GroupedPickerComponent,
    GroupedPickerGroup,
    GroupedPickerItem,
    GroupedPickerKey,
} from '../../grouped-picker/grouped-picker.component';
import { CreateEmbeddingModelModalComponent } from '../create-embedding-model-modal/create-embedding-model-modal.component';
import { CreateLlmModelModalComponent } from '../create-llm-model-modal/create-llm-model-modal.component';
import { CreateRealtimeModelModalComponent } from '../create-realtime-model-modal/create-realtime-model-modal.component';
import { CreateTranscriptionModelModalComponent } from '../create-transcription-model-modal/create-transcription-model-modal.component';

const TOP_PROVIDERS = [
    'openai',
    'anthropic',
    'google_ai',
    'azure',
    'groq',
    'mistral',
    'deepseek',
    'ollama',
    'bedrock',
    'huggingface',
];

interface ModelItem extends GroupedPickerItem {
    model: LLMModel;
    provider: LLMProvider;
}

interface ModelGroup extends GroupedPickerGroup<ModelItem> {
    provider: LLMProvider;
}

@Component({
    selector: 'app-llm-model-selector',
    imports: [AppSvgIconComponent, ButtonComponent, IconButtonComponent, GroupedPickerComponent],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => LlmModelSelectorComponent),
            multi: true,
        },
    ],
    templateUrl: './llm-model-selector.component.html',
    styleUrls: ['./llm-model-selector.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LlmModelSelectorComponent implements ControlValueAccessor {
    private llmLibraryService = inject(LLMLibraryService);
    private dialog = inject(Dialog);
    private readonly destroyRef = inject(DestroyRef);

    placeholder = input<string>('Select LLM model');
    icon = input<string>('help_outline');
    label = input<string>('');
    required = input<boolean>(false);
    tooltipText = input<string>('');
    provider = input.required<ModelTypes>();

    selectedValue = model<number | null>(null);
    modelChanged = output<{ model: LLMModel; provider: LLMProvider }>();

    isDisabled = signal(false);

    modelsResource = rxResource({
        params: () => ({
            provider: this.provider(),
        }),

        stream: ({ params }) => {
            return this.llmLibraryService.loadModels(params.provider);
        },
    });

    sortedProvidersWithModels = computed<ProviderWithModels<LLMModel>[]>(() => {
        const providers = (this.modelsResource.value() ?? []) as ProviderWithModels<LLMModel>[];

        return [...providers].sort((a, b) => {
            const aIndex = TOP_PROVIDERS.indexOf(a.provider.name.toLowerCase());
            const bIndex = TOP_PROVIDERS.indexOf(b.provider.name.toLowerCase());

            if (aIndex !== -1 && bIndex !== -1) return aIndex - bIndex;
            if (aIndex !== -1) return -1;
            if (bIndex !== -1) return 1;

            return a.provider.name.localeCompare(b.provider.name);
        });
    });

    selectedModelInfo = computed<{ model: LLMModel; provider: ProviderWithModels<LLMModel>['provider'] } | null>(() => {
        const id = this.selectedValue();
        if (id === null || id === undefined) return null;
        for (const group of this.sortedProvidersWithModels()) {
            const model = group.models.find((m) => m.id === id);
            if (model) return { model, provider: group.provider };
        }
        return null;
    });

    isSelectedModelDeprecated = computed<boolean>(() => {
        const model = this.selectedModelInfo()?.model;
        return !!model?.predefined && !model?.is_visible;
    });

    protected readonly groups = computed<ModelGroup[]>(() =>
        this.sortedProvidersWithModels().map(({ provider, models }) => ({
            id: provider.id,
            name: provider.name,
            icon: getProviderIconPath(provider.name),
            provider,
            items: models.map((model) => ({
                id: model.id,
                name: model.name,
                disabled: model.predefined && !model.is_visible,
                dimmed: model.is_visible === false,
                model,
                provider,
            })),
        }))
    );

    protected readonly selectedKey = computed<GroupedPickerKey | null>(() => {
        const info = this.selectedModelInfo();
        return info ? { groupId: info.provider.id, itemId: info.model.id } : null;
    });

    private onChange: (value: number | null) => void = () => {};
    protected onTouched: () => void = () => {};

    selectModel(model: LLMModel, provider: LLMProvider): void {
        this.selectedValue.set(model.id);
        this.onChange(model.id);
        this.modelChanged.emit({ model, provider });
    }

    openEditModal(model: LLMModel, provider: LLMProvider): void {
        const dialogRef = this.dialog.open(this.createModelModals[this.provider()], {
            data: { provider, model },
            width: '600px',
        });

        dialogRef.closed.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((result) => {
            if (result) {
                this.modelsResource.reload();
            }
        });
    }

    private readonly createModelModals: Record<ModelTypes, ComponentType<unknown>> = {
        [ModelTypes.LLM]: CreateLlmModelModalComponent,
        [ModelTypes.EMBEDDING]: CreateEmbeddingModelModalComponent,
        [ModelTypes.REALTIME]: CreateRealtimeModelModalComponent,
        [ModelTypes.TRANSCRIPTION]: CreateTranscriptionModelModalComponent,
    };

    openAllModelsModal(provider: ProviderWithModels['provider']): void {
        const dialogRef = this.dialog.open(this.createModelModals[this.provider()], {
            data: { provider },
            width: '600px',
        });

        dialogRef.closed.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((result) => {
            if (result) {
                this.modelsResource.reload();
            }
        });
    }

    writeValue(value: number | null): void {
        this.selectedValue.set(value ?? null);
    }

    registerOnChange(fn: (value: number | null) => void): void {
        this.onChange = fn;
    }

    registerOnTouched(fn: () => void): void {
        this.onTouched = fn;
    }

    setDisabledState(isDisabled: boolean): void {
        this.isDisabled.set(isDisabled);
    }
}
