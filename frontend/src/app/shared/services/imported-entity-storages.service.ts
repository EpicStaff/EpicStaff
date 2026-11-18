import { inject, Injectable } from '@angular/core';

import { ImportResult } from '../../core/models/import-result.model';
import { AppStorageService } from './app-storage.service';
import { EmbeddingConfigStorageService } from './embeddings/embedding-config-storage.service';
import { EmbeddingModelsStorageService } from './embeddings/embedding-models-storage.service';
import { LlmConfigStorageService } from './llms/llm-config-storage.service';
import { LlmModelsStorageService } from './llms/llm-models-storage.service';
import { LlmProvidersStorageService } from './llms/llm-providers-storage.service';
import { RealtimeConfigStorageService } from './realtime-llms/realtime-config-storage.service';
import { RealtimeModelsStorageService } from './realtime-llms/realtime-models-storage.service';
import { StorageService } from './storage-service.interface';
import { TranscriptionConfigStorageService } from './transcription-llms/transcription-config-storage.service';
import { TranscriptionModelsStorageService } from './transcription-llms/transcription-models-storage.service';

/**
 * Drops the cached model and config lists an import brought new rows into, so the pages showing them
 * reload. An import of flows or of knowledge collections can bring the models and configs they use.
 */
@Injectable({ providedIn: 'root' })
export class ImportedEntityStoragesService {
    private readonly appStorage = inject(AppStorageService);
    private readonly storagesByEntityType: Record<string, StorageService[]> = {
        LLMModel: [inject(LlmModelsStorageService), inject(LlmProvidersStorageService)],
        LLMConfig: [inject(LlmConfigStorageService)],
        EmbeddingModel: [inject(EmbeddingModelsStorageService), inject(LlmProvidersStorageService)],
        EmbeddingConfig: [inject(EmbeddingConfigStorageService)],
        RealtimeModel: [inject(RealtimeModelsStorageService), inject(LlmProvidersStorageService)],
        RealtimeConfig: [inject(RealtimeConfigStorageService)],
        RealtimeTranscriptionModel: [inject(TranscriptionModelsStorageService), inject(LlmProvidersStorageService)],
        RealtimeTranscriptionConfig: [inject(TranscriptionConfigStorageService)],
    };

    invalidateImported(result: ImportResult): void {
        const storages = Object.entries(this.storagesByEntityType)
            .filter(([entityType]) => (result[entityType]?.total ?? 0) > 0)
            .flatMap(([, entityStorages]) => entityStorages);
        this.appStorage.invalidate(storages);
    }
}
