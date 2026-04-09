import { Dialog, DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';

import { AppSvgIconComponent } from '../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { EmbeddingModel } from '../../../models/embeddings/embedding.model';
import { LLM_Provider } from '../../../models/llm-provider.model';
import { EmbeddingModelsService } from '../../../services/embeddings/embeddings.service';
import { getProviderIconPath } from '../../../utils/get-provider-icon';
import { CreateEmbeddingModelModalComponent } from '../create-embedding-model-modal/create-embedding-model-modal.component';

export interface AllEmbeddingModelsDialogData {
    provider: LLM_Provider;
    models: EmbeddingModel[];
}

@Component({
    selector: 'app-all-embedding-models-modal',
    standalone: true,
    imports: [CommonModule, FormsModule, AppSvgIconComponent],
    templateUrl: './all-models-modal.component.html',
    styleUrls: ['./all-models-modal.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AllModelsModalComponent implements OnInit {
    private readonly dialogRef = inject(DialogRef);
    private readonly dialog = inject(Dialog);
    private readonly dialogData = inject<AllEmbeddingModelsDialogData>(DIALOG_DATA);
    private readonly modelsService = inject(EmbeddingModelsService);
    private readonly destroyRef = inject(DestroyRef);

    public readonly searchQuery = signal('');
    public readonly models = signal<EmbeddingModel[]>([]);

    public readonly provider = computed(() => this.dialogData.provider);

    public readonly filteredModels = computed(() => {
        const query = this.searchQuery().toLowerCase().trim();
        const allModels = this.models();

        if (!query) {
            return allModels;
        }

        return allModels.filter((model) => model.name.toLowerCase().includes(query));
    });

    public readonly visibleCount = computed(() => this.models().filter((model) => model.is_visible).length);

    public ngOnInit(): void {
        this.models.set([...this.dialogData.models]);

        this.dialogRef.keydownEvents.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((event) => {
            if ((event.ctrlKey || event.metaKey) && event.code === 'KeyS') {
                event.preventDefault();
                this.onClose();
            }
        });
    }

    public getProviderIcon(providerName: string): string {
        return getProviderIconPath(providerName);
    }

    public onSearchChange(event: Event): void {
        const target = event.target as HTMLInputElement;
        this.searchQuery.set(target.value);
    }

    public isModelVisible(model: EmbeddingModel): boolean {
        return model.is_visible;
    }

    public toggleVisibility(model: EmbeddingModel): void {
        this.modelsService.patchModel(model.id, { is_visible: !model.is_visible }).subscribe({
            next: (updatedModel) => {
                this.models.update((currentModels) =>
                    currentModels.map((currentModel) => (currentModel.id === model.id ? updatedModel : currentModel))
                );
            },
        });
    }

    public openCreateModelModal(): void {
        const createDialogRef = this.dialog.open(CreateEmbeddingModelModalComponent, {
            data: {
                provider: this.provider(),
            },
        });

        createDialogRef.closed.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((createdModel) => {
            if (!createdModel) {
                return;
            }

            const created = createdModel as EmbeddingModel;
            this.models.update((currentModels) =>
                [...currentModels, created].sort((a, b) => a.name.localeCompare(b.name))
            );
        });
    }

    public onClose(): void {
        this.dialogRef.close(true);
    }
}
