import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { RagType } from '../models/base-rag.model';
import { CollectionStatus, CreateCollectionDtoResponse } from '../models/collection.model';
import { CollectionDetailsGraphRag } from '../models/graph-rag.model';
import { CollectionDetailsNaiveRag } from '../models/naive-rag.model';
import { CollectionsApiService } from './collections-api.service';
import { CollectionsStorageService, RagModelNames } from './collections-storage.service';

const CACHED: CreateCollectionDtoResponse = {
    collection_id: 7,
    collection_name: 'CoreStack',
    description: 'New guidance',
    status: CollectionStatus.COMPLETED,
    document_count: 0,
    rag_configurations: [],
    created_at: '2026-03-12T13:28:23Z',
    updated_at: '2026-03-13T09:00:00Z',
    created_by: null,
    last_edited_by: null,
    last_edited_at: '2026-03-13T09:00:00Z',
};

describe('CollectionsStorageService.updateCollectionById', () => {
    it('takes only the saved fields and the edit metadata from the response into the cache', () => {
        const editor = { id: 3, display_name: 'Olga Mageria', avatar_url: null };
        // A name save answered after a guidance save it overlapped with: its description is the older one.
        const response: CreateCollectionDtoResponse = {
            ...CACHED,
            collection_name: 'CoreStack v2',
            description: 'Old guidance',
            updated_at: '2026-03-13T09:00:01Z',
            last_edited_by: editor,
            last_edited_at: '2026-03-13T09:00:01Z',
        };
        TestBed.configureTestingModule({
            providers: [
                { provide: CollectionsApiService, useValue: { updateCollectionById: vi.fn(() => of(response)) } },
            ],
        });
        const storage = TestBed.inject(CollectionsStorageService);
        storage.updateOrCreateCollectionInCache(CACHED);

        storage.updateCollectionById(7, { collection_name: 'CoreStack v2' }).subscribe();

        expect(storage.fullCollections()).toEqual([
            {
                ...CACHED,
                collection_name: 'CoreStack v2',
                updated_at: '2026-03-13T09:00:01Z',
                last_edited_by: editor,
                last_edited_at: '2026-03-13T09:00:01Z',
            },
        ]);
        expect(storage.collections()[0].description).toBe('New guidance');
    });

    it('caches the whole response for a collection not cached yet', () => {
        TestBed.configureTestingModule({
            providers: [
                { provide: CollectionsApiService, useValue: { updateCollectionById: vi.fn(() => of(CACHED)) } },
            ],
        });
        const storage = TestBed.inject(CollectionsStorageService);

        storage.updateCollectionById(7, { collection_name: 'CoreStack' }).subscribe();

        expect(storage.fullCollections()).toEqual([CACHED]);
    });
});

describe('CollectionsStorageService.getRagModelNames', () => {
    const TIMESTAMPS = { created_at: '2026-03-12T13:28:23Z', updated_at: '2026-03-12T13:28:23Z' };
    // Naive and graph ids come from separate tables, so both RAGs here have id 5.
    const NAIVE: CollectionDetailsNaiveRag = {
        ...TIMESTAMPS,
        chunks_count: 0,
        document_configs_count: 0,
        embedder_id: 1,
        embedder_name: 'Small embedder',
        embeddings_count: 0,
        indexing_document_config_ids: [],
        is_ready_for_indexing: true,
        message: null,
        rag_id: 5,
        rag_type: 'naive',
        status: 'completed',
        indexing_usage: {},
    };
    const GRAPH: CollectionDetailsGraphRag = {
        ...TIMESTAMPS,
        embedder_id: '2',
        embedder_name: 'Large embedder',
        llm_name: 'GPT config',
        is_ready_for_indexing: true,
        message: null,
        rag_id: 5,
        rag_type: 'graph',
        require_reindexing: false,
        reindex_reason: {},
        status: 'completed',
        processing_document_ids: [],
        indexing_usage: {},
    };

    function storageWith(collection: CreateCollectionDtoResponse): CollectionsStorageService {
        TestBed.configureTestingModule({ providers: [{ provide: CollectionsApiService, useValue: {} }] });
        const storage = TestBed.inject(CollectionsStorageService);
        storage.updateOrCreateCollectionInCache(collection);
        return storage;
    }

    it.each<[string, number, number, RagType, RagModelNames]>([
        ['the naive RAG', 7, 5, 'naive', { embedderName: 'Small embedder', llmName: null }],
        ['the graph RAG with the same id', 7, 5, 'graph', { embedderName: 'Large embedder', llmName: 'GPT config' }],
        ['a RAG that is not cached', 7, 6, 'naive', { embedderName: null, llmName: null }],
        ['a collection that is not cached', 8, 5, 'naive', { embedderName: null, llmName: null }],
    ])('names %s', (_case, collectionId, ragId, ragType, expected) => {
        const storage = storageWith({ ...CACHED, rag_configurations: [NAIVE, GRAPH] });

        expect(storage.getRagModelNames(collectionId, ragId, ragType)).toEqual(expected);
    });

    it('gives no LLM name for a graph RAG without an LLM', () => {
        const storage = storageWith({ ...CACHED, rag_configurations: [{ ...GRAPH, llm_name: null }] });

        expect(storage.getRagModelNames(7, 5, 'graph')).toEqual({ embedderName: 'Large embedder', llmName: null });
    });
});
