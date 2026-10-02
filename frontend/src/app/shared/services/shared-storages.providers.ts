import { Provider } from '@angular/core';

import { APP_STORAGE } from './app-storage.token';
import { EmbeddingConfigStorageService } from './embeddings/embedding-config-storage.service';
import { EmbeddingModelsStorageService } from './embeddings/embedding-models-storage.service';
import { LlmConfigStorageService } from './llms/llm-config-storage.service';
import { LlmModelsStorageService } from './llms/llm-models-storage.service';
import { LlmProvidersStorageService } from './llms/llm-providers-storage.service';
import { RealtimeConfigStorageService } from './realtime-llms/realtime-config-storage.service';
import { RealtimeModelsStorageService } from './realtime-llms/realtime-models-storage.service';
import { SecretsStorageService } from './secrets/secrets-storage.service';
import { TranscriptionConfigStorageService } from './transcription-llms/transcription-config-storage.service';
import { TranscriptionModelsStorageService } from './transcription-llms/transcription-models-storage.service';

export function provideSharedStorages(): Provider[] {
    return [
        { provide: APP_STORAGE, useExisting: EmbeddingConfigStorageService, multi: true },
        { provide: APP_STORAGE, useExisting: EmbeddingModelsStorageService, multi: true },
        { provide: APP_STORAGE, useExisting: LlmConfigStorageService, multi: true },
        { provide: APP_STORAGE, useExisting: LlmModelsStorageService, multi: true },
        { provide: APP_STORAGE, useExisting: LlmProvidersStorageService, multi: true },
        { provide: APP_STORAGE, useExisting: RealtimeConfigStorageService, multi: true },
        { provide: APP_STORAGE, useExisting: RealtimeModelsStorageService, multi: true },
        { provide: APP_STORAGE, useExisting: SecretsStorageService, multi: true },
        { provide: APP_STORAGE, useExisting: TranscriptionConfigStorageService, multi: true },
        { provide: APP_STORAGE, useExisting: TranscriptionModelsStorageService, multi: true },
    ];
}
