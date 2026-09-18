import { computed, inject, Injectable, Signal } from '@angular/core';
import { LLMProvider, ModelTypes, RealtimeModel, RealtimeModelConfig } from '@shared/models';
import { forkJoin, Observable } from 'rxjs';
import { map } from 'rxjs/operators';

import { LlmProvidersStorageService } from '../llms/llm-providers-storage.service';
import { RealtimeConfigStorageService } from './realtime-config-storage.service';
import { RealtimeModelsStorageService } from './realtime-models-storage.service';

export interface FullRealtimeConfig extends RealtimeModelConfig {
    modelDetails: RealtimeModel | null;
    providerDetails: LLMProvider | null;
}

@Injectable({
    providedIn: 'root',
})
export class FullRealtimeConfigService {
    private readonly realtimeConfigStorage = inject(RealtimeConfigStorageService);
    private readonly realtimeModelsStorage = inject(RealtimeModelsStorageService);
    private readonly llmProvidersStorage = inject(LlmProvidersStorageService);

    /**
     * Reactive view over Realtime configs joined with their model and provider details.
     * Recomputes automatically whenever the underlying storage signals
     * (configs / models / providersByType) change.
     */
    public readonly fullRealtimeConfigs: Signal<FullRealtimeConfig[]> = computed(() => {
        const configs = this.realtimeConfigStorage.configs();
        const models = this.realtimeModelsStorage.models();
        const providers = this.llmProvidersStorage.providersByType().get(ModelTypes.REALTIME) ?? [];

        const modelMap = new Map<number, RealtimeModel>(models.map((m) => [m.id, m]));
        const providerMap = new Map<number, LLMProvider>(providers.map((p) => [p.id, p]));

        return configs.map((config) => {
            const modelDetails = modelMap.get(config.realtime_model) ?? null;
            const providerDetails =
                modelDetails?.provider != null ? (providerMap.get(modelDetails.provider) ?? null) : null;

            return {
                ...config,
                modelDetails,
                providerDetails,
            };
        });
    });

    /**
     * Ensures configs, models and providers are loaded and returns the combined list.
     * After the load completes, the `fullRealtimeConfigs` signal will reflect the same data
     * and continue to track subsequent storage updates.
     */
    getFullRealtimeConfigs(): Observable<FullRealtimeConfig[]> {
        return forkJoin({
            configs: this.realtimeConfigStorage.getAllConfigs(),
            models: this.realtimeModelsStorage.getModels(),
            providers: this.llmProvidersStorage.getProvidersByType(ModelTypes.REALTIME),
        }).pipe(map(() => this.fullRealtimeConfigs()));
    }
}
