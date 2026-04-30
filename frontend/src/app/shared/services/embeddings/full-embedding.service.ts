import { Injectable } from '@angular/core';
import { EmbeddingModel, GetEmbeddingConfigRequest, LLMProvider, ModelTypes } from '@shared/models';
import { forkJoin, Observable } from 'rxjs';
import { map } from 'rxjs/operators';

import { LlmProvidersStorageService } from '../llms/llm-providers-storage.service';
import { EmbeddingConfigStorageService } from './embedding-config-storage.service';
import { EmbeddingModelsStorageService } from './embedding-models-storage.service';

export interface FullEmbeddingConfig extends GetEmbeddingConfigRequest {
    modelDetails: EmbeddingModel | null;
    providerDetails: LLMProvider | null;
}

@Injectable({
    providedIn: 'root',
})
export class FullEmbeddingConfigService {
    constructor(
        private embeddingConfigStorage: EmbeddingConfigStorageService,
        private embeddingModelsStorage: EmbeddingModelsStorageService,
        private llmProvidersStorage: LlmProvidersStorageService
    ) {}

    getFullEmbeddingConfigs(): Observable<FullEmbeddingConfig[]> {
        return forkJoin({
            configs: this.embeddingConfigStorage.getAllConfigs(),
            models: this.embeddingModelsStorage.getModels(),
            providers: this.llmProvidersStorage.getProvidersByType(ModelTypes.EMBEDDING),
        }).pipe(
            map(({ configs, models, providers }) => {
                // Create lookup tables for models and providers
                const modelMap: Record<number, EmbeddingModel> = {};
                models.forEach((model) => {
                    modelMap[model.id] = model;
                });

                const providerMap: Record<number, LLMProvider> = {};
                providers.forEach((provider) => {
                    providerMap[provider.id] = provider;
                });

                const visibleConfigs = configs.filter((config) => config);

                return visibleConfigs.map((config) => {
                    const modelDetails = modelMap[config.model] || null;
                    const providerDetails = modelDetails?.embedding_provider
                        ? providerMap[modelDetails.embedding_provider]
                        : null;

                    return {
                        ...config,
                        modelDetails,
                        providerDetails,
                    };
                });
            })
        );
    }
}
