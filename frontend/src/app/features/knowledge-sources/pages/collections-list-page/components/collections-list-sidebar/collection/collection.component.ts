import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { AppSvgIconComponent } from '@shared/components';

import { RAG_STATUS_CONFIG, RAG_TYPE_CONFIG } from '../../../../../constants/constants';
import { CollectionDropTargetDirective } from '../../../../../directives/collection-drop-target.directive';
import { GetCollectionRequest } from '../../../../../models/collection.model';

@Component({
    selector: 'app-collection',
    templateUrl: './collection.component.html',
    styleUrls: ['./collection.component.scss'],
    imports: [AppSvgIconComponent, CollectionDropTargetDirective],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CollectionComponent {
    collection = input.required<GetCollectionRequest>();
    selected = input<boolean>(false);

    ragTypeConfig = RAG_TYPE_CONFIG;
    ragStatusConfig = RAG_STATUS_CONFIG;
}
