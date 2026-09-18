import { computed, inject, Injectable, Signal } from '@angular/core';
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
    private readonly llmConfigStorage = inject(LlmConfigStorageService);
    private readonly llmModelsStorage = inject(LlmModelsStorageService);
    private readonly llmProvidersStorage = inject(LlmProvidersStorageService);

    /**
     * Reactive view over LLM configs joined with their model and provider details.
     * Recomputes automatically whenever the underlying storage signals
     * (configs / models / providersByType) change.
     */
    public readonly fullLLMConfigs: Signal<FullLLMConfig[]> = computed(() => {
        const configs = this.llmConfigStorage.configs();
        const models = this.llmModelsStorage.models();
        const providers = this.llmProvidersStorage.providersByType().get(ModelTypes.LLM) ?? [];

        const modelMap = new Map<number, GetLlmModelRequest>(models.map((m) => [m.id, m]));
        const providerMap = new Map<number, LLMProvider>(providers.map((p) => [p.id, p]));

        return configs.map((config) => {
            const modelDetails = modelMap.get(config.model) ?? null;
            const providerDetails =
                modelDetails?.llm_provider != null ? (providerMap.get(modelDetails.llm_provider) ?? null) : null;

            return {
                ...config,
                modelDetails,
                providerDetails,
            };
        });
    });

    /**
     * Backwards-compatible alias consumed by the agent-definitions feature (EST-2914).
     * Points at the same reactive signal as `fullLLMConfigs`.
     */
    public readonly fullConfigs: Signal<FullLLMConfig[]> = this.fullLLMConfigs;

    /**
     * Ensures configs, models and providers are loaded and returns the combined list.
     * After the load completes, the `fullLLMConfigs` signal will reflect the same data
     * and continue to track subsequent storage updates.
     */
    getFullLLMConfigs(): Observable<FullLLMConfig[]> {
        return forkJoin({
            configs: this.llmConfigStorage.getAllConfigs(),
            models: this.llmModelsStorage.getModels(),
            providers: this.llmProvidersStorage.getProvidersByType(ModelTypes.LLM),
        }).pipe(map(() => this.fullLLMConfigs()));
    }
}
