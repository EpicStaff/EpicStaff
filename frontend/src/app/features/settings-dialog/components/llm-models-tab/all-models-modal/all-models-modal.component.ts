import {
    ChangeDetectionStrategy,
    Component,
    DestroyRef,
    inject,
    signal,
    computed,
    OnInit,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Dialog, DialogRef, DIALOG_DATA } from '@angular/cdk/dialog';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { AppIconComponent } from '../../../../../shared/components/app-icon/app-icon.component';
import { LLM_Provider } from '../../../models/LLM_provider.model';
import { LLM_Model } from '../../../models/llms/LLM.model';
import { LLM_Models_Service } from '../../../services/llms/LLM_models.service';
import { getProviderIconPath } from '../../../utils/get-provider-icon';
import { CreateLlmModelModalComponent } from '../create-llm-model-modal/create-llm-model-modal.component';

export interface AllModelsDialogData {
    provider: LLM_Provider;
    models: LLM_Model[];
}

export interface AllModelsResult {
    changed: boolean;
}

@Component({
    selector: 'app-all-models-modal',
    standalone: true,
    imports: [CommonModule, FormsModule, AppIconComponent],
    templateUrl: './all-models-modal.component.html',
    styleUrls: ['./all-models-modal.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AllModelsModalComponent implements OnInit {
    private dialogRef = inject(DialogRef);
    private dialog = inject(Dialog);
    private dialogData = inject<AllModelsDialogData>(DIALOG_DATA);
    private modelsService = inject(LLM_Models_Service);
    private destroyRef = inject(DestroyRef);

    searchQuery = signal('');
    models = signal<LLM_Model[]>([]);
    hasChanges = signal(false);

    provider = computed(() => this.dialogData.provider);

    filteredModels = computed(() => {
        const query = this.searchQuery().toLowerCase().trim();
        const allModels = this.models();

        if (!query) {
            return allModels;
        }

        return allModels.filter(m => m.name.toLowerCase().includes(query));
    });

    visibleCount = computed(() => {
        return this.models().filter(m => m.is_visible).length;
    });

    ngOnInit(): void {
        this.models.set([...this.dialogData.models]);
    }

    getProviderIcon(providerName: string): string {
        return getProviderIconPath(providerName);
    }

    onSearchChange(event: Event): void {
        const target = event.target as HTMLInputElement;
        this.searchQuery.set(target.value);
    }

    isModelVisible(model: LLM_Model): boolean {
        return model.is_visible;
    }

    toggleVisibility(model: LLM_Model): void {
        const newVisibility = !model.is_visible;
        
        this.modelsService.patchModel(model.id, { is_visible: newVisibility }).subscribe({
            next: (updatedModel) => {
                this.models.update(models => 
                    models.map(m => m.id === model.id ? updatedModel : m)
                );
                this.hasChanges.set(true);
            },
            error: (err) => console.error('Error updating model visibility:', err)
        });
    }

    openCreateModelModal(): void {
        const createDialogRef = this.dialog.open(CreateLlmModelModalComponent, {
            data: {
                provider: this.provider(),
            },
        });

        createDialogRef.closed
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((createdModel) => {
                if (!createdModel) {
                    return;
                }

                const created = createdModel as LLM_Model;
                this.models.update((current) =>
                    [...current, created].sort((a, b) => a.name.localeCompare(b.name))
                );
                this.hasChanges.set(true);
            });
    }

    onClose(): void {
        const result: AllModelsResult = { changed: this.hasChanges() };
        this.dialogRef.close(result);
    }
}
