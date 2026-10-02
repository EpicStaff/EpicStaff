import { Provider } from '@angular/core';
import { APP_STORAGE } from '@shared/services';

import { CollectionsStorageService } from './services/collections-storage.service';
import { DocumentsStorageService } from './services/documents-storage.service';
import { NaiveRagDocumentsStorageService } from './services/naive-rag-documents-storage.service';

export function provideKnowledgeSourcesStorages(): Provider[] {
    return [
        { provide: APP_STORAGE, useExisting: CollectionsStorageService, multi: true },
        { provide: APP_STORAGE, useExisting: DocumentsStorageService, multi: true },
        { provide: APP_STORAGE, useExisting: NaiveRagDocumentsStorageService, multi: true },
    ];
}
