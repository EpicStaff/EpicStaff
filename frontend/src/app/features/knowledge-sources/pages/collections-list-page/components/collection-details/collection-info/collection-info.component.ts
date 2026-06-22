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

    totalSize = computed(() => {
        const bytes = this.documents().reduce((sum, doc) => sum + (doc.file_size ?? 0), 0);
        return this.formatBytes(bytes);
    });

    largestFile = computed(() => {
        const docs = this.documents();
        if (!docs.length) return '0 B';
        const max = docs.reduce((a, b) => ((b.file_size ?? 0) > (a.file_size ?? 0) ? b : a));
        return this.formatBytes(max.file_size ?? 0);
    });

    smallestFile = computed(() => {
        const docs = this.documents();
        if (!docs.length) return '0 B';
        const min = docs.reduce((a, b) => ((b.file_size ?? 0) < (a.file_size ?? 0) ? b : a));
        return this.formatBytes(min.file_size ?? 0);
    });

    private formatBytes(bytes: number): string {
        if (bytes === 0) return '0 B';
        const units = ['B', 'KB', 'MB'];
        const i = Math.floor(Math.log(bytes) / Math.log(1024));
        const value = bytes / Math.pow(1024, i);
        return `${value % 1 === 0 ? value : value.toFixed(1)} ${units[i]}`;
    }
}
