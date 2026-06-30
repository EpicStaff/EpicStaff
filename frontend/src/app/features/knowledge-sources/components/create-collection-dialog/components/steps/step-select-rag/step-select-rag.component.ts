import { ChangeDetectionStrategy, Component, DestroyRef, inject, input, model, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HelpTooltipComponent, SelectComponent, SelectItem } from '@shared/components';
import { EmbeddingConfig } from '@shared/models';
import { EmbeddingConfigsService, LLMConfigService } from '@shared/services';
import { map } from 'rxjs/operators';

import { ToastService } from '../../../../../../../services/notifications';
import { RAG_TYPES } from '../../../../../constants/constants';
import { Rag, RagType } from '../../../../../models/base-rag.model';
import { CreateCollectionDtoResponse } from '../../../../../models/collection.model';
import { RagTypeComponent } from './rag-type/rag-type.component';

@Component({
    selector: 'app-step-select-rag',
    templateUrl: './step-select-rag.component.html',
    styleUrls: ['./step-select-rag.component.scss'],
    imports: [RagTypeComponent, SelectComponent, HelpTooltipComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StepSelectRagComponent implements OnInit {
    collection = input.required<CreateCollectionDtoResponse>();

    embeddingConfigs = signal<SelectItem[]>([]);
    llmModels = signal<SelectItem[]>([]);

    selectedRag = model<RagType | null>(null);
    selectedEmbedder = model<number | null>(null);
    selectedLLM = model<number | null>(null);

    private destroyRef = inject(DestroyRef);
    private embeddingConfigService = inject(EmbeddingConfigsService);
    private toastService = inject(ToastService);
    private llmConfigService = inject(LLMConfigService);

    ngOnInit() {
        this.getEmbeddingConfigs();
        this.getLLMConfigs();
    }

    private getEmbeddingConfigs() {
        this.embeddingConfigService
            .getEmbeddingConfigs()
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                map((configs) => {
                    return configs.map((embedConfig: EmbeddingConfig) => ({
                        name: embedConfig.custom_name,
                        value: embedConfig.id,
                    }));
                })
            )
            .subscribe({
                next: (configs: SelectItem[]) => {
                    this.embeddingConfigs.set(configs);
                },
                error: (error) => {
                    this.toastService.error('Failed to load embedding configs.');
                    console.error('Error loading embedding configs:', error);
                },
            });
    }

    private getLLMConfigs() {
        this.llmConfigService
            .getAllConfigsLLM()
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                map((configs) => {
                    return configs.map((config) => ({
                        name: config.custom_name,
                        value: config.id,
                    }));
                })
            )
            .subscribe({
                next: (models: SelectItem[]) => {
                    this.llmModels.set(models);
                },
                error: (error) => {
                    this.toastService.error('Failed to load LLM Models.');
                    console.error('Error loading LLM Models:', error);
                },
            });
    }

    public onSelectRag(rag: Rag): void {
        if (rag.disabled) return;

        this.selectedRag.set(rag.value);
    }

    protected readonly RAG_TYPES = RAG_TYPES;
}
