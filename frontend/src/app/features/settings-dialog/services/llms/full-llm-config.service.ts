import { Injectable } from '@angular/core';
import { forkJoin, Observable } from 'rxjs';
import { map } from 'rxjs/operators';

import { LLM_Provider, ModelTypes } from '../../models/llm-provider.model';
import { GetLlmModelRequest } from '../../models/llms/LLM.model';
import { GetLlmConfigRequest } from '../../models/llms/LLM_config.model';
import { LLM_Providers_Service } from '../llm-providers.service';
import { LLM_Config_Service } from './llm-config.service';
import { LLM_Models_Service } from './llm-models.service';

export interface FullLLMConfig extends GetLlmConfigRequest {
    modelDetails: GetLlmModelRequest | null;
    providerDetails: LLM_Provider | null;
}

@Injectable({
    providedIn: 'root',
})
export class FullLLMConfigService {
    constructor(
        private llmConfigService: LLM_Config_Service,
        private llmModelsService: LLM_Models_Service,
        private llmProvidersService: LLM_Providers_Service
    ) {}

    getFullLLMConfigs(): Observable<FullLLMConfig[]> {
        return forkJoin({
            configs: this.llmConfigService.getAllConfigsLLM(),
            models: this.llmModelsService.getLLMModels(),
            providers: this.llmProvidersService.getProvidersByQuery(ModelTypes.LLM),
        }).pipe(
            map(({ configs, models, providers }) => {
                const modelMap: Record<number, GetLlmModelRequest> = {};
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
                    const providerDetails = modelDetails?.llm_provider ? providerMap[modelDetails.llm_provider] : null;

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
