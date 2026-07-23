import { NgClass } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, effect, inject, input, OnDestroy } from '@angular/core';
import { AppSvgIconComponent } from '@shared/components';

import { CollectionStatus, GetCollectionRequest } from '../../../../../models/collection.model';
import { CollectionIndexingSSEService } from '../../../../../services/collection-indexing-sse.service';

const STATUS_MAP: Record<CollectionStatus, { text: string; icon: string }> = {
    completed: {
        text: 'Completed',
        icon: 'check',
    },
    empty: {
        text: 'New',
        icon: 'circle',
    },
    warning: {
        text: 'Warning',
        icon: 'warning',
    },
    uploading: {
        text: 'Processing',
        icon: 'processing',
    },
    failed: {
        text: 'Failed',
        icon: 'x',
    },
};

@Component({
    selector: 'app-collection',
    templateUrl: './collection.component.html',
    styleUrls: ['./collection.component.scss'],
    imports: [NgClass, AppSvgIconComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CollectionComponent implements OnDestroy {
    collection = input<GetCollectionRequest>();
    selected = input<boolean>(false);

    statusData = computed(() => STATUS_MAP[this.collection()?.status ?? CollectionStatus.EMPTY]);

    indexingProgress = computed(() => {
        const currentCollection = this.collection();
        if (!currentCollection || currentCollection.status !== CollectionStatus.UPLOADING) return null;
        return this.indexingSSEService.progress().get(currentCollection.collection_id) ?? null;
    });

    /**
     * Owns exactly one ref in CollectionIndexingSSEService for `subscribedCollectionId`,
     * paired 1:1 with a subscribe()/unsubscribe() call. The effect body re-runs on every
     * `collection()` change (including ones triggered by SSE progress updates while still
     * 'uploading'), so it must diff against the last id it actually subscribed to instead
     * of blindly calling subscribe()/unsubscribe() every run — otherwise it would either
     * over-increment the refcount (repeated subscribe() while staying 'uploading') or
     * release a ref it never held (unsubscribe() while status was never 'uploading',
     * e.g. re-indexing an already-'completed' collection from a config dialog).
     */
    private readonly syncIndexingSubscriptionEffect = effect(() => {
        const currentCollection = this.collection();
        const nextId =
            currentCollection && currentCollection.status === CollectionStatus.UPLOADING
                ? currentCollection.collection_id
                : null;

        if (nextId === this.subscribedCollectionId) return;

        if (this.subscribedCollectionId !== null) {
            this.indexingSSEService.unsubscribe(this.subscribedCollectionId);
        }
        if (nextId !== null) {
            this.indexingSSEService.subscribe(nextId);
        }
        this.subscribedCollectionId = nextId;
    });

    private readonly indexingSSEService = inject(CollectionIndexingSSEService);
    private subscribedCollectionId: number | null = null;

    ngOnDestroy(): void {
        if (this.subscribedCollectionId !== null) {
            this.indexingSSEService.unsubscribe(this.subscribedCollectionId);
            this.subscribedCollectionId = null;
        }
    }
}
