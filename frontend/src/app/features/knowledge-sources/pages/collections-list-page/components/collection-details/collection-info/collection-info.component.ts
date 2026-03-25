import {ChangeDetectionStrategy, Component, computed, input} from "@angular/core";
import {ButtonComponent} from "../../../../../../../shared/components/buttons/button/button.component";
import {CreateCollectionDtoResponse} from "../../../../../models/collection.model";
import {DatePipe} from "@angular/common";
import {DisplayedListDocument} from "../../../../../models/document.model";

@Component({
    selector: 'app-collection-details-info',
    templateUrl: './collection-info.component.html',
    styleUrls: ['./collection-info.component.scss'],
    imports: [
        ButtonComponent,
        DatePipe
    ],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class CollectionInfoComponent {
    collection = input.required<CreateCollectionDtoResponse>();
    documents = input<DisplayedListDocument[]>([]);

    documentTypes = computed(() => {
        const types = new Set<string>();

        this.documents().forEach(doc => {
            doc.file_type && types.add(doc.file_type);
        })
        return Array.from(types);
    });
}
