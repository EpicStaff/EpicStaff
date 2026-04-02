import { NgClass } from '@angular/common';
import { ChangeDetectionStrategy, Component, input } from '@angular/core';

import { AppIconComponent } from '../../../../../../../shared/components/app-icon/app-icon.component';
import { CollectionStatus, GetCollectionRequest } from '../../../../../models/collection.model';

@Component({
    selector: 'app-collection',
    templateUrl: './collection.component.html',
    styleUrls: ['./collection.component.scss'],
    imports: [NgClass, AppIconComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CollectionComponent {
    collection = input<GetCollectionRequest>();
    selected = input<boolean>(false);

    statusMap: Record<CollectionStatus, { text: string; icon: string }> = {
        completed: {
            text: 'Completed',
            icon: 'ui/check',
        },
        empty: {
            text: 'New',
            icon: 'ui/circle',
        },
        warning: {
            text: 'Warning',
            icon: 'ui/warning',
        },
        uploading: {
            text: 'Processing',
            icon: 'ui/processing',
        },
        failed: {
            text: 'Failed',
            icon: 'ui/close',
        },
    } as const;

    get statusData() {
        return this.statusMap[this.collection()?.status || 'empty'];
    }
}
