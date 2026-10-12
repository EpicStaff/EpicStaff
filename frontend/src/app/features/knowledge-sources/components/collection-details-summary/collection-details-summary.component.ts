import { Component, computed, input } from '@angular/core';

import { CollectionStats, formatFileTypes } from '../../helpers/collection-stats.util';

/**
 * The collection-specific part of the "Collection Details" dialog: file statistics, shown below the shared
 * authorship block.
 */
@Component({
    selector: 'app-collection-details-summary',
    templateUrl: './collection-details-summary.component.html',
    styleUrls: ['./collection-details-summary.component.scss'],
})
export class CollectionDetailsSummaryComponent {
    readonly stats = input.required<CollectionStats>();

    protected readonly fileTypes = computed(() => formatFileTypes(this.stats().fileTypes));
}
