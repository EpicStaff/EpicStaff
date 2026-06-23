import { inject, Injectable } from '@angular/core';

import { DefaultModelsStorageService } from '../../features/configure-models/services/default-models-storage.service';
import { FlowsStorageService } from '../../features/flows/services/flows-storage.service';
import { LabelsStorageService } from '../../features/flows/services/labels-storage.service';
import { CollectionsStorageService } from '../../features/knowledge-sources/services/collections-storage.service';
import { DocumentsStorageService } from '../../features/knowledge-sources/services/documents-storage.service';
import { NaiveRagDocumentsStorageService } from '../../features/knowledge-sources/services/naive-rag-documents-storage.service';
import { ProjectTagsStorageService } from '../../features/projects/services/project-tags-storage.service';
import { ProjectsStorageService } from '../../features/projects/services/projects-storage.service';
import { OrganizationsStorageService } from '../../features/role-base-access/services/admin/organizations-storage.service';
import { RolesService } from '../../features/role-base-access/services/admin/roles.service';
import { ActiveOrgService } from '../../services/auth/active-org.service';
import { PermissionsService } from '../../services/auth/permissions.service';
import {
    EmbeddingConfigStorageService,
    EmbeddingModelsStorageService,
    LlmConfigStorageService,
    LlmModelsStorageService,
    LlmProvidersStorageService,
    NgrokConfigStorageService,
    RealtimeConfigStorageService,
    RealtimeModelsStorageService,
    TranscriptionConfigStorageService,
    TranscriptionModelsStorageService,
} from './index';

export interface StorageService {
    clear(): void;
}

@Injectable({ providedIn: 'root' })
export class AppStorageService {
    private readonly storages: StorageService[] = [
        inject(ActiveOrgService),
        inject(PermissionsService),
        inject(RolesService),
        inject(OrganizationsStorageService),
        inject(DefaultModelsStorageService),
        inject(LabelsStorageService),
        inject(FlowsStorageService),
        inject(CollectionsStorageService),
        inject(DocumentsStorageService),
        inject(NaiveRagDocumentsStorageService),
        inject(ProjectTagsStorageService),
        inject(ProjectsStorageService),
        inject(EmbeddingConfigStorageService),
        inject(EmbeddingModelsStorageService),
        inject(LlmConfigStorageService),
        inject(LlmModelsStorageService),
        inject(LlmProvidersStorageService),
        inject(NgrokConfigStorageService),
        inject(RealtimeConfigStorageService),
        inject(RealtimeModelsStorageService),
        inject(TranscriptionConfigStorageService),
        inject(TranscriptionModelsStorageService),
    ];

    clearAll(): void {
        this.storages.forEach((s) => s.clear());
    }

    /** Clears each given storage once (duplicates are ignored). */
    invalidate(storages: Iterable<StorageService>): void {
        new Set(storages).forEach((s) => s.clear());
    }
}
