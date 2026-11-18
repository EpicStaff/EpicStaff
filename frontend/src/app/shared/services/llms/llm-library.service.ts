import { computed, inject, Injectable } from '@angular/core';
import { PROVIDER_ICON_PATHS } from '@shared/constants';
import {
    CatalogConfigFields,
    EmbeddingModel,
    GetRealtimeTranscriptionModelRequest,
    LlmLibraryProviderGroup,
    LLMModel,
    LLMProvider,
    ModelTypes,
    RealtimeModel,
    Tag,
} from '@shared/models';
import { forkJoin, Observable } from 'rxjs';
import { map } from 'rxjs/operators';

import { EmbeddingConfigStorageService } from '../embeddings/embedding-config-storage.service';
import { EmbeddingModelsStorageService } from '../embeddings/embedding-models-storage.service';
import { RealtimeConfigStorageService } from '../realtime-llms/realtime-config-storage.service';
import { RealtimeModelsStorageService } from '../realtime-llms/realtime-models-storage.service';
import { TranscriptionConfigStorageService } from '../transcription-llms/transcription-config-storage.service';
import { TranscriptionModelsStorageService } from '../transcription-llms/transcription-models-storage.service';
import { LlmConfigStorageService } from './llm-config-storage.service';
import { LlmModelsStorageService } from './llm-models-storage.service';
import { LlmProvidersStorageService } from './llm-providers-storage.service';

type AnyModel = LLMModel | EmbeddingModel | RealtimeModel | GetRealtimeTranscriptionModelRequest;

export interface ProviderWithModels<T extends { id: number; name: string } = AnyModel> {
    provider: LLMProvider;
    models: T[];
}

/** How a library card names its config's provider and model. */
interface ModelNames {
    providerName: string;
    modelName: string;
}

/** Groups the cards of configs that have no model. */
const UNKNOWN_PROVIDER = 'unknown';
/** The model line of a card whose config has no model. */
const NO_MODEL = 'No model';

/** An LLM or embedding config names its own model; one with no model goes under an "Unknown" provider. */
function ownModelNames(config: CatalogConfigFields): ModelNames {
    return { providerName: config.provider ?? UNKNOWN_PROVIDER, modelName: config.model_name ?? NO_MODEL };
}

/**
 * Names a realtime or transcription config's model by its id in the model and provider lists, which are small for
 * these types; null leaves out a config whose model or provider is not listed.
 */
function joinedModelNames<TModel extends { id: number; name: string }>(
    models: TModel[],
    providers: LLMProvider[],
    getProviderId: (model: TModel) => number
): (modelId: number) => ModelNames | null {
    const modelMap = new Map(models.map((m) => [m.id, m]));
    const providerMap = new Map(providers.map((p) => [p.id, p]));
    return (modelId) => {
        const model = modelMap.get(modelId);
        const provider = model && providerMap.get(getProviderId(model));
        return model && provider ? { providerName: provider.name, modelName: model.name } : null;
    };
}

/** The config's temperature setting; null when it has none, so its card shows none. */
function temperatureOf(config: { parameters: Record<string, unknown> }): number | null {
    const temperature = config.parameters['temperature'];
    return typeof temperature === 'number' ? temperature : null;
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

    private buildProviderGroups<TConfig extends { id: number; custom_name: string }>(
        configs: TConfig[],
        type: ModelTypes,
        getModelNames: (config: TConfig) => ModelNames | null,
        getTemperature: (config: TConfig) => number | null,
        getTags: (config: TConfig) => Tag[],
        getReview: (config: TConfig) => { needs_review: boolean; review_reasons: string[] } = () => ({
            needs_review: false,
            review_reasons: [],
        })
    ): LlmLibraryProviderGroup[] {
        const groupsMap = new Map<string, LlmLibraryProviderGroup>();

        for (const config of configs) {
            const names = getModelNames(config);
            if (!names) continue;
            const groupKey = `${type}-${names.providerName}`;
            if (!groupsMap.has(groupKey)) {
                const iconKey = names.providerName.toLowerCase();
                groupsMap.set(groupKey, {
                    id: groupKey,
                    providerName: names.providerName,
                    providerIconPath: PROVIDER_ICON_PATHS[iconKey] ?? PROVIDER_ICON_PATHS['default'],
                    models: [],
                    configType: type,
                });
            }
            groupsMap.get(groupKey)!.models.push({
                id: config.id,
                customName: config.custom_name,
                modelName: names.modelName,
                tags: getTags(config),
                temperature: getTemperature(config),
                usedByCount: null,
                configType: type,
                needsReview: getReview(config).needs_review,
                reviewReasons: getReview(config).review_reasons,
            });
        }

        return Array.from(groupsMap.values());
    }

    public readonly providerGroups = computed<LlmLibraryProviderGroup[]>(() => {
        const providersByType = this.providersStorage.providersByType();
        const realtimeModelNames = joinedModelNames(
            this.realtimeModelsStorage.models(),
            providersByType.get(ModelTypes.REALTIME) ?? [],
            (m) => m.provider
        );
        const transcriptionModelNames = joinedModelNames(
            this.transcriptionModelsStorage.models(),
            providersByType.get(ModelTypes.TRANSCRIPTION) ?? [],
            (m) => m.provider
        );

        return [
            ...this.buildProviderGroups(
                this.configStorage.configs(),
                ModelTypes.LLM,
                ownModelNames,
                temperatureOf,
                (c) => c.tags,
                (c) => c
            ),
            ...this.buildProviderGroups(
                this.embeddingConfigStorage.configs(),
                ModelTypes.EMBEDDING,
                ownModelNames,
                temperatureOf,
                () => [],
                (c) => c
            ),
            ...this.buildProviderGroups(
                this.realtimeConfigStorage.configs(),
                ModelTypes.REALTIME,
                (c) => realtimeModelNames(c.realtime_model),
                () => 0,
                () => []
            ),
            ...this.buildProviderGroups(
                this.transcriptionConfigStorage.configs(),
                ModelTypes.TRANSCRIPTION,
                (c) => transcriptionModelNames(c.realtime_transcription_model),
                () => 0,
                () => []
            ),
        ];
    });

    loadLlmData(): Observable<void> {
        return this.configStorage.getAllConfigs().pipe(map(() => void 0));
    }

    loadEmbeddingData(): Observable<void> {
        return this.embeddingConfigStorage.getAllConfigs().pipe(map(() => void 0));
    }

    loadRealtimeData(): Observable<void> {
        return forkJoin({
            configs: this.realtimeConfigStorage.getAllConfigs(),
            models: this.realtimeModelsStorage.getModels(),
            providers: this.providersStorage.getProvidersByType(ModelTypes.REALTIME),
        }).pipe(map(() => void 0));
    }

    loadTranscriptionData(): Observable<void> {
        return forkJoin({
            configs: this.transcriptionConfigStorage.getAllConfigs(),
            models: this.transcriptionModelsStorage.getModels(),
            providers: this.providersStorage.getProvidersByType(ModelTypes.TRANSCRIPTION),
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
