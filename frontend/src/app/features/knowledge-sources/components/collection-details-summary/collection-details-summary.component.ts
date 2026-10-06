import { Component, computed, input } from '@angular/core';
import { CopyButtonComponent } from '@shared/components';

import { CollectionStats, formatFileTypes } from '../../helpers/collection-stats.util';

/**
 * The collection-specific part of the "Collection Details" dialog: file statistics and the collection id that
 * flows, surfaces and the API use to refer to the collection ("Knowledge source path" in the design). Shown below the shared authorship block.
 */
@Component({
    selector: 'app-collection-details-summary',
    imports: [CopyButtonComponent],
    templateUrl: './collection-details-summary.component.html',
    styleUrls: ['./collection-details-summary.component.scss'],
})
export class CollectionDetailsSummaryComponent {
    readonly stats = input.required<CollectionStats>();
    readonly collectionId = input.required<number>();

    protected readonly fileTypes = computed(() => formatFileTypes(this.stats().fileTypes));
    protected readonly collectionIdText = computed(() => String(this.collectionId()));
}
