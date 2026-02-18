import {
    ChangeDetectionStrategy,
    Component,
    DestroyRef,
    OnInit,
    inject,
    signal,
    computed,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Dialog, DialogRef, DIALOG_DATA } from '@angular/cdk/dialog';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { forkJoin } from 'rxjs';
import { finalize } from 'rxjs/operators';

import { AppIconComponent } from '../../../../../shared/components/app-icon/app-icon.component';
import { LLM_Provider, ModelTypes } from '../../../models/LLM_provider.model';
import { LLM_Model } from '../../../models/llms/LLM.model';
import { LLM_Providers_Service } from '../../../services/LLM_providers.service';
import { LLM_Models_Service } from '../../../services/llms/LLM_models.service';
import { getProviderIconPath } from '../../../utils/get-provider-icon';
import { AllModelsModalComponent, AllModelsResult } from '../all-models-modal/all-models-modal.component';

export interface ModelSelectorDialogData {
    selectedModelId?: number | null;
}

export interface ModelSelectorResult {
    provider: LLM_Provider;
    model: LLM_Model;
}

interface ProviderWithModels {
    provider: LLM_Provider;
    models: LLM_Model[];
    visibleModels: LLM_Model[];
}

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

@Component({
    selector: 'app-model-selector-modal',
    standalone: true,
    imports: [CommonModule, FormsModule, AppIconComponent],
    templateUrl: './model-selector-modal.component.html',
    styleUrls: ['./model-selector-modal.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ModelSelectorModalComponent implements OnInit {
    private dialogRef = inject(DialogRef);
    private dialog = inject(Dialog);
    private dialogData = inject<ModelSelectorDialogData | null>(DIALOG_DATA, { optional: true });
    private providersService = inject(LLM_Providers_Service);
    private modelsService = inject(LLM_Models_Service);
    private destroyRef = inject(DestroyRef);

    isLoading = signal(true);
    searchQuery = signal('');
    providersWithModels = signal<ProviderWithModels[]>([]);
    selectedModelId = signal<number | null>(null);
    selectedModel = signal<LLM_Model | null>(null);
    selectedProvider = signal<LLM_Provider | null>(null);

    filteredProviders = computed(() => {
        const query = this.searchQuery().toLowerCase().trim();
        const providers = this.providersWithModels();

        if (!query) {
            return providers;
        }

        return providers
            .map(p => {
                const providerMatches = p.provider.name.toLowerCase().includes(query);
                const matchingModels = p.visibleModels.filter(m =>
                    m.name.toLowerCase().includes(query)
                );

                if (providerMatches) {
                    return p;
                }

                if (matchingModels.length > 0) {
                    return {
                        ...p,
                        visibleModels: matchingModels,
                    };
                }

                return null;
            })
            .filter((p): p is ProviderWithModels => p !== null);
    });

    ngOnInit(): void {
        if (this.dialogData?.selectedModelId) {
            this.selectedModelId.set(this.dialogData.selectedModelId);
        }
        this.loadProvidersAndModels();

        this.dialogRef.backdropClick.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => {
            this.onClose();
        });
    }

    private sortProviders(providers: LLM_Provider[]): LLM_Provider[] {
        return [...providers].sort((a, b) => {
            const aIndex = TOP_PROVIDERS.indexOf(a.name.toLowerCase());
            const bIndex = TOP_PROVIDERS.indexOf(b.name.toLowerCase());

            if (aIndex !== -1 && bIndex !== -1) {
                return aIndex - bIndex;
            }
            if (aIndex !== -1) return -1;
            if (bIndex !== -1) return 1;
            return a.name.localeCompare(b.name);
        });
    }

    private loadProvidersAndModels(): void {
        this.isLoading.set(true);

        this.providersService
            .getProvidersByQuery(ModelTypes.LLM)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (providers) => {
                    const sortedProviders = this.sortProviders(providers);

                    const modelRequests = sortedProviders.map(provider =>
                        this.modelsService.getLLMModels(provider.id, true)
                    );

                    if (modelRequests.length === 0) {
                        this.providersWithModels.set([]);
                        this.isLoading.set(false);
                        return;
                    }

                    forkJoin(modelRequests)
                        .pipe(
                            takeUntilDestroyed(this.destroyRef),
                            finalize(() => this.isLoading.set(false))
                        )
                        .subscribe({
                            next: (modelsArrays) => {
                                const providersWithModels: ProviderWithModels[] = sortedProviders.map((provider, index) => {
                                    const visibleModels = modelsArrays[index] || [];

                                    const selectedId = this.selectedModelId();
                                    if (selectedId) {
                                        const selectedInProvider = visibleModels.find(m => m.id === selectedId);
                                        if (selectedInProvider) {
                                            this.selectedModel.set(selectedInProvider);
                                            this.selectedProvider.set(provider);
                                        }
                                    }

                                    return {
                                        provider,
                                        models: visibleModels,
                                        visibleModels,
                                    };
                                });

                                this.providersWithModels.set(providersWithModels);
                            },
                            error: (err) => {
                                console.error('Error loading models:', err);
                                this.isLoading.set(false);
                            },
                        });
                },
                error: (err) => {
                    console.error('Error loading providers:', err);
                    this.isLoading.set(false);
                },
            });
    }

    getProviderIcon(providerName: string): string {
        return getProviderIconPath(providerName);
    }

    onSearchChange(event: Event): void {
        const target = event.target as HTMLInputElement;
        this.searchQuery.set(target.value);
    }

    toggleModelSelection(provider: LLM_Provider, model: LLM_Model): void {
        const currentId = this.selectedModelId();
        if (currentId === model.id) {
            this.selectedModelId.set(null);
            this.selectedModel.set(null);
            this.selectedProvider.set(null);
        } else {
            this.selectedModelId.set(model.id);
            this.selectedModel.set(model);
            this.selectedProvider.set(provider);
        }
    }

    isModelSelected(modelId: number): boolean {
        return this.selectedModelId() === modelId;
    }

    openAllModelsModal(provider: LLM_Provider, providerData: ProviderWithModels): void {
        this.modelsService.getLLMModels(provider.id).pipe(
            takeUntilDestroyed(this.destroyRef)
        ).subscribe({
            next: (allModels) => {
                const dialogRef = this.dialog.open(AllModelsModalComponent, {
                    data: {
                        provider,
                        models: allModels,
                    },
                });

                dialogRef.closed.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => {
                    this.reloadProviderModels(provider.id);
                });
            }
        });
    }

    private reloadProviderModels(providerId: number): void {
        this.modelsService.getLLMModels(providerId, true).pipe(
            takeUntilDestroyed(this.destroyRef)
        ).subscribe({
            next: (visibleModels) => {
                this.providersWithModels.update(providers => {
                    return providers.map(p => {
                        if (p.provider.id !== providerId) return p;
                        return {
                            ...p,
                            models: visibleModels,
                            visibleModels,
                        };
                    });
                });
            }
        });
    }

    onClose(): void {
        const model = this.selectedModel();
        const provider = this.selectedProvider();
        
        if (model && provider) {
            const result: ModelSelectorResult = { provider, model };
            this.dialogRef.close(result);
        } else {
            this.dialogRef.close(null);
        }
    }
}
