import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { Component, DestroyRef, inject, OnDestroy } from '@angular/core';

import { ToastService } from '../../../../services/notifications';
import { CollectionIndexingSSEService } from '../../services/collection-indexing-sse.service';

@Component({
    template: '',
})
export abstract class RagConfigurationDialogComponent implements OnDestroy {
    protected data: { ragId: number; collectionId: number } = inject(DIALOG_DATA);
    protected destroyRef = inject(DestroyRef);
    protected dialogRef = inject(DialogRef);
    protected toast = inject(ToastService);

    private readonly indexingSSEService = inject(CollectionIndexingSSEService);
    /** Whether this dialog instance currently holds a ref for `data.collectionId`. */
    private isWatchingIndexing = false;

    ngOnDestroy(): void {
        this.releaseIndexingWatch();
    }

    protected abstract onClose(): void;
    protected abstract runIndexing(): void;

    /**
     * Registers this dialog as an owner of the collection's indexing stream. Idempotent
     * per dialog instance — re-triggering indexing while already watching does not
     * inflate the refcount. Paired with `releaseIndexingWatch()` in `ngOnDestroy`.
     */
    protected startWatchingIndexing(): void {
        if (this.isWatchingIndexing) return;
        this.isWatchingIndexing = true;
        this.indexingSSEService.subscribe(this.data.collectionId);
    }

    private releaseIndexingWatch(): void {
        if (!this.isWatchingIndexing) return;
        this.isWatchingIndexing = false;
        this.indexingSSEService.unsubscribe(this.data.collectionId);
    }
}
