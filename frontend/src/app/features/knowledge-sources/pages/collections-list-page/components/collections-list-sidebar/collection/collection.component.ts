import { NgClass } from '@angular/common';
import { ChangeDetectionStrategy, Component, input } from '@angular/core';

import { AppSvgIconComponent } from '../../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { CollectionStatus, GetCollectionRequest } from '../../../../../models/collection.model';

@Component({
    selector: 'app-collection',
    templateUrl: './collection.component.html',
    styleUrls: ['./collection.component.scss'],
    imports: [NgClass, AppSvgIconComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CollectionComponent {
    collection = input<GetCollectionRequest>();
    selected = input<boolean>(false);

    statusMap: Record<CollectionStatus, { text: string; icon: string }> = {
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
    } as const;

    get statusData() {
        return this.statusMap[this.collection()?.status || 'empty'];
    }
}
