import { Injectable } from '@angular/core';
import { forkJoin, Observable } from 'rxjs';
import { map } from 'rxjs/operators';

import { EmbeddingModel } from '../../models/embeddings/embedding.model';
import { GetEmbeddingConfigRequest } from '../../models/embeddings/embedding-config.model';
import { LLM_Provider, ModelTypes } from '../../models/llm-provider.model';
import { LLM_Providers_Service } from '../llm-providers.service';
import { EmbeddingConfigsService } from './embedding_configs.service';
import { EmbeddingModelsService } from './embeddings.service';

export interface FullEmbeddingConfig extends GetEmbeddingConfigRequest {
    modelDetails: EmbeddingModel | null;
    providerDetails: LLM_Provider | null;
}

@Injectable({
    providedIn: 'root',
})
export class FullEmbeddingConfigService {
    constructor(
        private embeddingConfigService: EmbeddingConfigsService,
        private embeddingModelsService: EmbeddingModelsService,
        private providersService: LLM_Providers_Service
    ) {}

    getFullEmbeddingConfigs(): Observable<FullEmbeddingConfig[]> {
        return forkJoin({
            configs: this.embeddingConfigService.getEmbeddingConfigs(),
            models: this.embeddingModelsService.getEmbeddingModels(),
            providers: this.providersService.getProvidersByQuery(ModelTypes.EMBEDDING),
        }).pipe(
            map(({ configs, models, providers }) => {
                // Create lookup tables for models and providers
                const modelMap: Record<number, EmbeddingModel> = {};
                models.forEach((model) => {
                    modelMap[model.id] = model;
                });

                const providerMap: Record<number, LLM_Provider> = {};
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
