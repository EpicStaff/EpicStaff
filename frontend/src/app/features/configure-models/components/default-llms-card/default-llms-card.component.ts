import { Dialog } from '@angular/cdk/dialog';
import { ComponentType } from '@angular/cdk/portal';
import { CommonModule } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    inject,
    input,
    OnInit,
    output,
    Signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AppSvgIconComponent, SelectComponent, SelectItem } from '@shared/components';
import { ModelTypes } from '@shared/models';
import {
    EmbeddingConfigStorageService,
    LlmConfigStorageService,
    RealtimeConfigStorageService,
    TranscriptionConfigStorageService,
} from '@shared/services';
import { Observable } from 'rxjs';

import { DefaultLlmsCard } from '../../interfaces/default-llms-card.interface';
import { EmbeddingModelConfigDialogComponent } from '../embedding-model-config-dialog/embedding-model-config-dialog.component';
import { LlmModelConfigDialogComponent } from '../llm-model-config-dialog/llm-model-config-dialog.component';
import { TranscriptionModelConfigDialogComponent } from '../transcription-model-config-dialog/transcription-model-config-dialog.component';
import { VoiceModelConfigDialogComponent } from '../voice-config-model/voice-model-config-dialog.component';

type DialogComponentType =
    | EmbeddingModelConfigDialogComponent
    | LlmModelConfigDialogComponent
    | VoiceModelConfigDialogComponent
    | TranscriptionModelConfigDialogComponent;

@Component({
    selector: 'app-default-llms-card',
    imports: [CommonModule, AppSvgIconComponent, SelectComponent],
    templateUrl: './default-llms-card.component.html',
    styleUrls: ['./default-llms-card.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DefaultLlmsCardComponent implements OnInit {
    private readonly llmConfigStorageService = inject(LlmConfigStorageService);
    private readonly embeddingConfigStorage = inject(EmbeddingConfigStorageService);
    private readonly realtimeConfigStorage = inject(RealtimeConfigStorageService);
    private readonly transcriptionConfigStorage = inject(TranscriptionConfigStorageService);

    private readonly destroyRef = inject(DestroyRef);
    private dialog = inject(Dialog);

    public readonly card = input.required<DefaultLlmsCard>();
    public readonly selectedConfigId = input<number | null>(null);
    public readonly modelSelected = output<{ cardId: string; configId: number | null }>();

    private readonly configSignals: Record<ModelTypes, Signal<{ id: number; custom_name: string }[]>> = {
        [ModelTypes.LLM]: this.llmConfigStorageService.configs,
        [ModelTypes.EMBEDDING]: this.embeddingConfigStorage.configs,
        [ModelTypes.REALTIME]: this.realtimeConfigStorage.configs,
        [ModelTypes.TRANSCRIPTION]: this.transcriptionConfigStorage.configs,
    };

    private readonly configLoaders: Record<ModelTypes, () => Observable<unknown>> = {
        [ModelTypes.LLM]: () => this.llmConfigStorageService.getAllConfigs(),
        [ModelTypes.EMBEDDING]: () => this.embeddingConfigStorage.getAllConfigs(),
        [ModelTypes.REALTIME]: () => this.realtimeConfigStorage.getAllConfigs(),
        [ModelTypes.TRANSCRIPTION]: () => this.transcriptionConfigStorage.getAllConfigs(),
    };

    private readonly dialogComponents: Record<ModelTypes, ComponentType<DialogComponentType>> = {
        [ModelTypes.LLM]: LlmModelConfigDialogComponent,
        [ModelTypes.EMBEDDING]: EmbeddingModelConfigDialogComponent,
        [ModelTypes.REALTIME]: VoiceModelConfigDialogComponent,
        [ModelTypes.TRANSCRIPTION]: TranscriptionModelConfigDialogComponent,
    };

    public readonly selectItems = computed<SelectItem[]>(() =>
        this.configSignals[this.card().configType]().map((item) => ({
            value: item.id,
            name: item.custom_name,
        }))
    );

    public ngOnInit(): void {
        this.configLoaders[this.card().configType]().pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
    }

    public selectConfig(configId: unknown): void {
        this.modelSelected.emit({ cardId: this.card().id, configId: configId as number });
    }

    public onResetConfig(): void {
        this.modelSelected.emit({ cardId: this.card().id, configId: null });
    }

    public onAddModel(): void {
        const component = this.getDialogComponent();
        this.dialog.open(component, {
            height: '90vh',
            width: '600px',
        });
    }

    private getDialogComponent(): ComponentType<DialogComponentType> {
        return this.dialogComponents[this.card().configType];
    }
}
