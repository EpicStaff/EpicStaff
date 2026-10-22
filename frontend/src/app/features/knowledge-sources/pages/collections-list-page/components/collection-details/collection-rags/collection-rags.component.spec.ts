import { Dialog } from '@angular/cdk/dialog';
import { TestBed } from '@angular/core/testing';
import { ConfirmationDialogService } from '@shared/components';

import { PermissionsService } from '../../../../../../../services/auth/permissions.service';
import { ToastService } from '../../../../../../../services/notifications';
import { IndexingUsage } from '../../../../../models/base-rag.model';
import { CollectionStatus, CreateCollectionDtoResponse } from '../../../../../models/collection.model';
import { CollectionDetailsNaiveRag } from '../../../../../models/naive-rag.model';
import { CollectionsStorageService } from '../../../../../services/collections-storage.service';
import { GraphRagDocumentsStorageService } from '../../../../../services/graph-rag-documents-storage.service';
import { NaiveRagDocumentsStorageService } from '../../../../../services/naive-rag-documents-storage.service';
import { RagDeleteRegistryService } from '../../../../../services/rag-delete-registry.service';
import { CollectionRagsComponent } from './collection-rags.component';

const TOTALS = { embedding_tokens: 1000, llm_input_tokens: null, llm_output_tokens: null, cost_usd: 0.5 };

function naiveRag(indexingUsage: IndexingUsage): CollectionDetailsNaiveRag {
    return {
        chunks_count: 0,
        document_configs_count: 0,
        embedder_id: 1,
        embedder_name: 'embedder',
        embeddings_count: 0,
        indexing_document_config_ids: [],
        is_ready_for_indexing: true,
        message: null,
        rag_id: 1,
        rag_type: 'naive',
        status: 'completed',
        indexing_usage: indexingUsage,
        created_at: '2026-03-12T13:28:23Z',
        updated_at: '2026-03-12T13:28:23Z',
    };
}

function collectionWith(configurations: CollectionDetailsNaiveRag[]): CreateCollectionDtoResponse {
    return {
        collection_id: 1,
        collection_name: 'Docs',
        description: '',
        status: CollectionStatus.COMPLETED,
        document_count: 0,
        rag_configurations: configurations,
        created_at: '2026-03-12T13:28:23Z',
        updated_at: '2026-03-12T13:28:23Z',
        created_by: null,
        last_edited_by: null,
        last_edited_at: null,
    };
}

function renderUsage(indexingUsage: IndexingUsage): string[] {
    TestBed.configureTestingModule({
        providers: [
            { provide: PermissionsService, useValue: { can: () => false } },
            { provide: Dialog, useValue: {} },
            { provide: ToastService, useValue: {} },
            { provide: CollectionsStorageService, useValue: {} },
            { provide: ConfirmationDialogService, useValue: {} },
            { provide: RagDeleteRegistryService, useValue: {} },
            { provide: NaiveRagDocumentsStorageService, useValue: {} },
            { provide: GraphRagDocumentsStorageService, useValue: {} },
        ],
    });
    const fixture = TestBed.createComponent(CollectionRagsComponent);
    fixture.componentRef.setInput('collection', collectionWith([naiveRag(indexingUsage)]));
    fixture.detectChanges();
    const host = fixture.nativeElement as HTMLElement;
    return Array.from(host.querySelectorAll('.usage')).map((element) => element.textContent?.trim() ?? '');
}

describe('CollectionRagsComponent usage lines', () => {
    it('renders no usage block for an empty usage object', () => {
        expect(renderUsage({})).toEqual([]);
    });

    it('renders the last indexing and total lines for populated usage', () => {
        const lines = renderUsage({
            last_run: { ...TOTALS, completed_at: '2026-01-01T00:00:00Z' },
            total: TOTALS,
        });
        expect(lines).toHaveLength(2);
        expect(lines[0]).toContain('Last indexing: 1,000 embedding tokens');
        expect(lines[1]).toContain('Total: 1,000 embedding tokens');
    });
});
