import { TestBed } from '@angular/core/testing';
import { AuthorshipDetailsDialogService } from '@shared/components';

import { CollectionDetailsSummaryComponent } from '../components/collection-details-summary/collection-details-summary.component';
import { buildCollectionStats } from '../helpers/collection-stats.util';
import { CollectionStatus, CreateCollectionDtoResponse } from '../models/collection.model';
import { DisplayedListDocument } from '../models/document.model';
import { COLLECTION_DETAILS_TITLE, CollectionDetailsDialogService } from './collection-details-dialog.service';

const COLLECTION: CreateCollectionDtoResponse = {
    collection_id: 42,
    collection_name: 'CoreStack',
    description: null,
    status: CollectionStatus.COMPLETED,
    document_count: 2,
    rag_configurations: [],
    created_at: '2026-03-12T13:28:23Z',
    updated_at: '2026-03-13T09:00:00Z',
    created_by: { id: 1, display_name: 'Ivan Bohun', avatar_url: null },
    last_edited_by: null,
    last_edited_at: null,
};

const DOCUMENTS: DisplayedListDocument[] = [
    {
        document_id: 1,
        file_name: 'a.pdf',
        file_type: 'pdf',
        file_size: 10240,
        source_collection: 42,
        isValidType: true,
        isValidSize: true,
    },
    { file_name: 'b.txt', file_size: 5, source_collection: 42, isValidType: true, isValidSize: true },
];

describe('CollectionDetailsDialogService', () => {
    it('opens "Collection Details" with the authorship, the stats, the collection id and the trigger to restore focus to', () => {
        const authorshipDetailsDialog = { open: vi.fn() };
        TestBed.configureTestingModule({
            providers: [{ provide: AuthorshipDetailsDialogService, useValue: authorshipDetailsDialog }],
        });
        const trigger = document.createElement('button');

        TestBed.inject(CollectionDetailsDialogService).open(COLLECTION, DOCUMENTS, trigger);

        expect(COLLECTION_DETAILS_TITLE).toBe('Collection Details');
        expect(authorshipDetailsDialog.open).toHaveBeenCalledExactlyOnceWith(
            COLLECTION_DETAILS_TITLE,
            COLLECTION,
            trigger,
            {
                component: CollectionDetailsSummaryComponent,
                inputs: { stats: buildCollectionStats(DOCUMENTS) },
            }
        );
    });
});
