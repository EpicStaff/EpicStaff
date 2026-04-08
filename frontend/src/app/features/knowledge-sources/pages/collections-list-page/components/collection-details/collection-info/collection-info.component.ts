import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { CreateCollectionDtoResponse } from '../../../../../models/collection.model';
import { DisplayedListDocument } from '../../../../../models/document.model';

@Component({
    selector: 'app-collection-details-info',
    templateUrl: './collection-info.component.html',
    styleUrls: ['./collection-info.component.scss'],
    imports: [DatePipe],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CollectionInfoComponent {
    collection = input.required<CreateCollectionDtoResponse>();
    documents = input<DisplayedListDocument[]>([]);

    documentTypes = computed(() => {
        const types = new Set<string>();

        this.documents().forEach((doc) => {
            doc.file_type && types.add(doc.file_type);
        });
        return Array.from(types);
    });
}
