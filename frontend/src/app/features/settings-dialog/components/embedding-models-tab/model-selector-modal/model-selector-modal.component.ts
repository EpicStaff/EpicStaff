import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Dialog, DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { finalize, forkJoin } from 'rxjs';

import { AppIconComponent } from '../../../../../shared/components/app-icon/app-icon.component';
import { LLM_Provider, ModelTypes } from '../../../models/LLM_provider.model';
import { EmbeddingModel } from '../../../models/embeddings/embedding.model';
import { LLM_Providers_Service } from '../../../services/LLM_providers.service';
import { EmbeddingModelsService } from '../../../services/embeddings/embeddings.service';
import { getProviderIconPath } from '../../../utils/get-provider-icon';
import { AllModelsModalComponent } from '../all-models-modal/all-models-modal.component';

export interface ModelSelectorDialogData {
  selectedModelId?: number | null;
}

export interface ModelSelectorResult {
  provider: LLM_Provider;
  model: EmbeddingModel;
}

interface ProviderWithModels {
  provider: LLM_Provider;
  models: EmbeddingModel[];
  visibleModels: EmbeddingModel[];
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
  selector: 'app-embedding-model-selector-modal',
  standalone: true,
  imports: [CommonModule, FormsModule, AppIconComponent],
  templateUrl: './model-selector-modal.component.html',
  styleUrls: ['./model-selector-modal.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ModelSelectorModalComponent implements OnInit {
  private readonly dialogRef = inject(DialogRef);
  private readonly dialog = inject(Dialog);
  private readonly dialogData = inject<ModelSelectorDialogData | null>(DIALOG_DATA, {
    optional: true,
  });
  private readonly providersService = inject(LLM_Providers_Service);
  private readonly modelsService = inject(EmbeddingModelsService);
  private readonly destroyRef = inject(DestroyRef);

  public readonly isLoading = signal(true);
  public readonly searchQuery = signal('');
  public readonly providersWithModels = signal<ProviderWithModels[]>([]);
  public readonly selectedModelId = signal<number | null>(null);
  public readonly selectedModel = signal<EmbeddingModel | null>(null);
  public readonly selectedProvider = signal<LLM_Provider | null>(null);

  public readonly filteredProviders = computed(() => {
    const query = this.searchQuery().toLowerCase().trim();
    const providers = this.providersWithModels();

    if (!query) {
      return providers;
    }

    return providers
      .map((providerData) => {
        const providerMatches = providerData.provider.name.toLowerCase().includes(query);
        const matchingModels = providerData.visibleModels.filter((model) =>
          model.name.toLowerCase().includes(query)
        );

        if (providerMatches) {
          return providerData;
        }

        if (matchingModels.length > 0) {
          return {
            ...providerData,
            visibleModels: matchingModels,
          };
        }

        return null;
      })
      .filter((providerData): providerData is ProviderWithModels => providerData !== null);
  });

  public ngOnInit(): void {
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
      if (aIndex !== -1) {
        return -1;
      }
      if (bIndex !== -1) {
        return 1;
      }
      return a.name.localeCompare(b.name);
    });
  }

  private loadProvidersAndModels(): void {
    this.isLoading.set(true);

    this.providersService
      .getProvidersByQuery(ModelTypes.EMBEDDING)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (providers) => {
          const sortedProviders = this.sortProviders(providers);
          const modelRequests = sortedProviders.map((provider) =>
            this.modelsService.getEmbeddingModels(provider.id)
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
                const providersWithModels = sortedProviders.map((provider, index) => {
                  const allModels = modelsArrays[index] || [];
                  const visibleModels = allModels.filter((model) => model.is_visible);
                  const selectedId = this.selectedModelId();

                  if (selectedId) {
                    const selectedInProvider = allModels.find((model) => model.id === selectedId);
                    if (selectedInProvider) {
                      this.selectedModel.set(selectedInProvider);
                      this.selectedProvider.set(provider);
                    }
                  }

                  return {
                    provider,
                    models: allModels,
                    visibleModels,
                  };
                });

                this.providersWithModels.set(providersWithModels);
              },
              error: () => {
                this.isLoading.set(false);
              },
            });
        },
        error: () => {
          this.isLoading.set(false);
        },
      });
  }

  private reloadProviderModels(providerId: number): void {
    this.modelsService
      .getEmbeddingModels(providerId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (models) => {
          const visibleModels = models.filter((model) => model.is_visible);
          this.providersWithModels.update((providers) =>
            providers.map((providerData) => {
              if (providerData.provider.id !== providerId) {
                return providerData;
              }
              return {
                ...providerData,
                models,
                visibleModels,
              };
            })
          );
        },
      });
  }

  public getProviderIcon(providerName: string): string {
    return getProviderIconPath(providerName);
  }

  public onSearchChange(event: Event): void {
    const target = event.target as HTMLInputElement;
    this.searchQuery.set(target.value);
  }

  public isModelSelected(modelId: number): boolean {
    return this.selectedModelId() === modelId;
  }

  public toggleModelSelection(provider: LLM_Provider, model: EmbeddingModel): void {
    if (this.selectedModelId() === model.id) {
      this.selectedModelId.set(null);
      this.selectedModel.set(null);
      this.selectedProvider.set(null);
      return;
    }

    this.selectedModelId.set(model.id);
    this.selectedModel.set(model);
    this.selectedProvider.set(provider);
  }

  public openAllModelsModal(provider: LLM_Provider): void {
    this.modelsService
      .getEmbeddingModels(provider.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (allModels) => {
          const modalRef = this.dialog.open(AllModelsModalComponent, {
            data: {
              provider,
              models: allModels,
            },
          });

          modalRef.closed.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => {
            this.reloadProviderModels(provider.id);
          });
        },
      });
  }

  public onClose(): void {
    const model = this.selectedModel();
    const provider = this.selectedProvider();

    if (model && provider) {
      this.dialogRef.close({ provider, model } as ModelSelectorResult);
      return;
    }

    this.dialogRef.close(null);
  }
}

