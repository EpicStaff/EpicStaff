import { computed, inject, Injectable } from '@angular/core';
import { PROVIDER_ICON_PATHS } from '@shared/constants';
import {
    EmbeddingModel,
    GetRealtimeTranscriptionModelRequest,
    LLMModel,
    LLMProvider,
    ModelTypes,
    RealtimeModel,
    Tag,
} from '@shared/models';
import {
    EmbeddingConfigStorageService,
    EmbeddingModelsStorageService,
    LlmConfigStorageService,
    LlmModelsStorageService,
    LlmProvidersStorageService,
    RealtimeConfigStorageService,
    RealtimeModelsStorageService,
    TranscriptionConfigStorageService,
    TranscriptionModelsStorageService,
} from '@shared/services';
import { forkJoin, Observable } from 'rxjs';
import { map } from 'rxjs/operators';

import { LlmLibraryProviderGroup } from '../../interfaces/llm-library-provider-group.interface';

type AnyModel = LLMModel | EmbeddingModel | RealtimeModel | GetRealtimeTranscriptionModelRequest;

export interface ProviderWithModels<T extends { id: number; name: string } = AnyModel> {
    provider: LLMProvider;
    models: T[];
}

@Injectable({
    providedIn: 'root',
})
export class LLMLibraryService {
    private readonly configStorage = inject(LlmConfigStorageService);
    private readonly llmModelsStorage = inject(LlmModelsStorageService);
    private readonly providersStorage = inject(LlmProvidersStorageService);
    private readonly embeddingConfigStorage = inject(EmbeddingConfigStorageService);
    private readonly embeddingModelsStorage = inject(EmbeddingModelsStorageService);
    private readonly realtimeConfigStorage = inject(RealtimeConfigStorageService);
    private readonly realtimeModelsStorage = inject(RealtimeModelsStorageService);
    private readonly transcriptionConfigStorage = inject(TranscriptionConfigStorageService);
    private readonly transcriptionModelsStorage = inject(TranscriptionModelsStorageService);

    private providerIdExtractors: Record<ModelTypes, (model: AnyModel) => number> = {
        [ModelTypes.LLM]: (m) => (m as LLMModel).llm_provider,
        [ModelTypes.TRANSCRIPTION]: (m) => (m as GetRealtimeTranscriptionModelRequest).provider,
        [ModelTypes.REALTIME]: (m) => (m as RealtimeModel).provider,
        [ModelTypes.EMBEDDING]: (m) => (m as EmbeddingModel).embedding_provider!,
    };

    private sortKeyExtractors: Record<ModelTypes, (model: AnyModel) => number> = {
        [ModelTypes.LLM]: (m) => {
            const llm = m as LLMModel;
            if (!llm.is_visible) return 2;
            return llm.predefined ? 1 : 0;
        },
        [ModelTypes.EMBEDDING]: (m) => {
            const em = m as EmbeddingModel;
            if (!em.is_visible) return 2;
            return em.is_custom ? 0 : 1;
        },
        [ModelTypes.REALTIME]: (m) => ((m as RealtimeModel).is_custom ? 0 : 1),
        [ModelTypes.TRANSCRIPTION]: (m) => ((m as GetRealtimeTranscriptionModelRequest).is_custom ? 0 : 1),
    };

    private buildProviderGroups<
        TConfig extends { id: number; custom_name: string },
        TModel extends { id: number; name: string },
    >(
        configs: TConfig[],
        models: TModel[],
        providers: LLMProvider[],
        type: ModelTypes,
        getModelId: (config: TConfig) => number,
        getProviderId: (model: TModel) => number,
        getTemperature: (config: TConfig) => number,
        getTags: (config: TConfig) => Tag[]
    ): LlmLibraryProviderGroup[] {
        const modelMap = new Map(models.map((m) => [m.id, m]));
        const providerMap = new Map(providers.map((p) => [p.id, p]));
        const groupsMap = new Map<string, LlmLibraryProviderGroup>();

        for (const config of configs) {
            const model = modelMap.get(getModelId(config));
            if (!model) continue;
            const provider = providerMap.get(getProviderId(model));
            if (!provider) continue;
            const groupKey = `${type}-${provider.id}`;
            if (!groupsMap.has(groupKey)) {
                const iconKey = provider.name.toLowerCase();
                groupsMap.set(groupKey, {
                    id: groupKey,
                    providerName: provider.name,
                    providerIconPath: PROVIDER_ICON_PATHS[iconKey] ?? PROVIDER_ICON_PATHS['default'],
                    models: [],
                    configType: type,
                });
            }
            groupsMap.get(groupKey)!.models.push({
                id: config.id,
                customName: config.custom_name,
                modelName: model.name,
                tags: getTags(config),
                temperature: getTemperature(config),
                usedByCount: null,
                configType: type,
            });
        }

        return Array.from(groupsMap.values());
    }

    public readonly providerGroups = computed<LlmLibraryProviderGroup[]>(() => {
        const providersByType = this.providersStorage.providersByType();

        return [
            ...this.buildProviderGroups(
                this.configStorage.configs(),
                this.llmModelsStorage.models(),
                providersByType.get(ModelTypes.LLM) ?? [],
                ModelTypes.LLM,
                (c) => c.model,
                (m) => m.llm_provider,
                (c) => c.temperature ?? 0,
                (c) => c.tags
            ),
            ...this.buildProviderGroups(
                this.embeddingConfigStorage.configs(),
                this.embeddingModelsStorage.models(),
                providersByType.get(ModelTypes.EMBEDDING) ?? [],
                ModelTypes.EMBEDDING,
                (c) => c.model,
                (m) => m.embedding_provider!,
                () => 0,
                () => []
            ),
            ...this.buildProviderGroups(
                this.realtimeConfigStorage.configs(),
                this.realtimeModelsStorage.models(),
                providersByType.get(ModelTypes.REALTIME) ?? [],
                ModelTypes.REALTIME,
                (c) => c.realtime_model,
                (m) => m.provider,
                () => 0,
                () => []
            ),
            ...this.buildProviderGroups(
                this.transcriptionConfigStorage.configs(),
                this.transcriptionModelsStorage.models(),
                providersByType.get(ModelTypes.TRANSCRIPTION) ?? [],
                ModelTypes.TRANSCRIPTION,
                (c) => c.realtime_transcription_model,
                (m) => m.provider,
                () => 0,
                () => []
            ),
        ];
    });

    loadConfigs(): Observable<void> {
        return forkJoin({
            configs: this.configStorage.getAllConfigs(),
            models: this.llmModelsStorage.getModels(),
            llmProviders: this.providersStorage.getProvidersByType(ModelTypes.LLM),
            embeddingConfigs: this.embeddingConfigStorage.getAllConfigs(),
            embeddingModels: this.embeddingModelsStorage.getModels(),
            embeddingProviders: this.providersStorage.getProvidersByType(ModelTypes.EMBEDDING),
            realtimeConfigs: this.realtimeConfigStorage.getAllConfigs(),
            realtimeModels: this.realtimeModelsStorage.getModels(),
            realtimeProviders: this.providersStorage.getProvidersByType(ModelTypes.REALTIME),
            transcriptionConfigs: this.transcriptionConfigStorage.getAllConfigs(),
            transcriptionModels: this.transcriptionModelsStorage.getModels(),
            transcriptionProviders: this.providersStorage.getProvidersByType(ModelTypes.TRANSCRIPTION),
        }).pipe(map(() => void 0));
    }

    loadModels(type: ModelTypes): Observable<ProviderWithModels[]> {
        return forkJoin({
            models: this.getModelsByType(type),
            providers: this.providersStorage.getProvidersByType(type),
        }).pipe(
            map(({ models, providers }) => {
                const getProviderId = this.providerIdExtractors[type];
                const getSortKey = this.sortKeyExtractors[type];
                const modelsMap = this.groupModelsByProvider(models, getProviderId);
                return this.mapToProviderWithModels(providers, modelsMap, getSortKey);
            })
        );
    }

    private getModelsByType(type: ModelTypes): Observable<AnyModel[]> {
        switch (type) {
            case ModelTypes.LLM:
                return this.llmModelsStorage.getModels();

            case ModelTypes.TRANSCRIPTION:
                return this.transcriptionModelsStorage.getModels();

            case ModelTypes.REALTIME:
                return this.realtimeModelsStorage.getModels();

            case ModelTypes.EMBEDDING:
                return this.embeddingModelsStorage.getModels();

            default:
                return this.llmModelsStorage.getModels();
        }
    }

    private groupModelsByProvider<T>(models: T[], getProviderId: (model: T) => number): Map<number, T[]> {
        const map = new Map<number, T[]>();

        for (const model of models) {
            const providerId = getProviderId(model);
            const list = map.get(providerId) ?? [];

            list.push(model);
            map.set(providerId, list);
        }

        return map;
    }

    private mapToProviderWithModels<T extends { id: number; name: string }>(
        providers: LLMProvider[],
        modelsMap: Map<number, T[]>,
        getSortKey: (model: T) => number
    ): ProviderWithModels<T>[] {
        return providers.map((provider) => {
            const allModels = modelsMap.get(provider.id) ?? [];
            const models = [...allModels].sort((a, b) => getSortKey(a) - getSortKey(b));

            return { provider, models };
        });
    }
}
