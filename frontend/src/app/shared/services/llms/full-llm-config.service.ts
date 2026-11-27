import { computed, inject, Injectable, Signal } from '@angular/core';
import { GetLlmConfigRequest, LLMProvider } from '@shared/models';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';

import { GetLlmModelRequest } from '../../models/llms/llm.model';
import { LlmConfigStorageService } from './llm-config-storage.service';

export interface FullLLMConfig extends GetLlmConfigRequest {
    modelDetails: Pick<GetLlmModelRequest, 'name'> | null;
    providerDetails: Pick<LLMProvider, 'name'> | null;
}

@Injectable({
    providedIn: 'root',
})
export class FullLLMConfigService {
    private readonly llmConfigStorage = inject(LlmConfigStorageService);

    /**
     * Reactive view over LLM configs with their model and provider names, which every config carries itself (the
     * model list is too long to load for a lookup). Recomputes whenever the stored configs change.
     */
    public readonly fullLLMConfigs: Signal<FullLLMConfig[]> = computed(() =>
        this.llmConfigStorage.configs().map((config) => ({
            ...config,
            modelDetails: config.model_name === null ? null : { name: config.model_name },
            providerDetails: config.provider === null ? null : { name: config.provider },
        }))
    );

    /**
     * Backwards-compatible alias consumed by the agent-definitions feature.
     * Points at the same reactive signal as `fullLLMConfigs`.
     */
    public readonly fullConfigs: Signal<FullLLMConfig[]> = this.fullLLMConfigs;

    /**
     * Ensures the configs are loaded and returns the combined list.
     * After the load completes, the `fullLLMConfigs` signal will reflect the same data
     * and continue to track subsequent storage updates.
     */
    getFullLLMConfigs(): Observable<FullLLMConfig[]> {
        return this.llmConfigStorage.getAllConfigs().pipe(map(() => this.fullLLMConfigs()));
    }
}
