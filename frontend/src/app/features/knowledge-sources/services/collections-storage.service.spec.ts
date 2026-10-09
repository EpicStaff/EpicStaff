import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { CollectionStatus, CreateCollectionDtoResponse } from '../models/collection.model';
import { CollectionsApiService } from './collections-api.service';
import { CollectionsStorageService } from './collections-storage.service';

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
