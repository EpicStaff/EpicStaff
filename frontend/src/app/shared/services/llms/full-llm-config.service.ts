import { computed, Injectable, Signal } from '@angular/core';
import { GetLlmConfigRequest } from '@shared/models';
import { LLMProvider, ModelTypes } from '@shared/models';
import { forkJoin, Observable } from 'rxjs';
import { map } from 'rxjs/operators';

import { GetLlmModelRequest } from '../../models/llms/llm.model';
import { LlmConfigStorageService } from './llm-config-storage.service';
import { LlmModelsStorageService } from './llm-models-storage.service';
import { LlmProvidersStorageService } from './llm-providers-storage.service';

export interface FullLLMConfig extends GetLlmConfigRequest {
    modelDetails: GetLlmModelRequest | null;
    providerDetails: LLMProvider | null;
}

@Injectable({
    providedIn: 'root',
})
export class FullLLMConfigService {
    constructor(
        private llmConfigStorage: LlmConfigStorageService,
        private llmModelsStorage: LlmModelsStorageService,
        private llmProvidersStorage: LlmProvidersStorageService
    ) {}

    readonly fullConfigs: Signal<FullLLMConfig[]> = computed(() =>
        this.combine(
            this.llmConfigStorage.configs(),
            this.llmModelsStorage.models(),
            this.llmProvidersStorage.providersByType().get(ModelTypes.LLM) ?? []
        )
    );

    private combine(
        configs: GetLlmConfigRequest[],
        models: GetLlmModelRequest[],
        providers: LLMProvider[]
    ): FullLLMConfig[] {
        const modelMap: Record<number, GetLlmModelRequest> = {};
        models.forEach((model) => {
            modelMap[model.id] = model;
        });

        const providerMap: Record<number, LLMProvider> = {};
        providers.forEach((provider) => {
            providerMap[provider.id] = provider;
        });

        return configs
            .filter((config) => config)
            .map((config) => {
                const modelDetails = modelMap[config.model] || null;
                const providerDetails = modelDetails?.llm_provider ? providerMap[modelDetails.llm_provider] : null;
                return { ...config, modelDetails, providerDetails };
            });
    }

    getFullLLMConfigs(): Observable<FullLLMConfig[]> {
        return forkJoin({
            configs: this.llmConfigStorage.getAllConfigs(),
            models: this.llmModelsStorage.getModels(),
            providers: this.llmProvidersStorage.getProvidersByType(ModelTypes.LLM),
        }).pipe(map(({ configs, models, providers }) => this.combine(configs, models, providers)));
    }
}
