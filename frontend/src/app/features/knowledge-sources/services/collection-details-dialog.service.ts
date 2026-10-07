import { DialogRef } from '@angular/cdk/dialog';
import { inject, Injectable } from '@angular/core';
import { AuthorshipDetailsDialogComponent, AuthorshipDetailsDialogService } from '@shared/components';

import { CollectionDetailsSummaryComponent } from '../components/collection-details-summary/collection-details-summary.component';
import { buildCollectionStats, CollectionStatsDocument } from '../helpers/collection-stats.util';
import { CreateCollectionDtoResponse } from '../models/collection.model';

export const COLLECTION_DETAILS_TITLE = 'Collection Details';

/** Opens the read-only "Collection Details" dialog: authorship, file statistics and the collection id. */
@Injectable({
    providedIn: 'root',
})
export class CollectionDetailsDialogService {
    private readonly authorshipDetailsDialog = inject(AuthorshipDetailsDialogService);

    /**
     * `documents` are the collection's files as listed; the stats count only the stored ones. They are a
     * snapshot taken on open. Pass the menu trigger as `restoreFocusTo` so focus returns to it on close.
     */
    open(
        collection: CreateCollectionDtoResponse,
        documents: CollectionStatsDocument[],
        restoreFocusTo?: HTMLElement
    ): DialogRef<void, AuthorshipDetailsDialogComponent> {
        return this.authorshipDetailsDialog.open(COLLECTION_DETAILS_TITLE, collection, restoreFocusTo, {
            component: CollectionDetailsSummaryComponent,
            inputs: { stats: buildCollectionStats(documents) },
        });
    }
}
