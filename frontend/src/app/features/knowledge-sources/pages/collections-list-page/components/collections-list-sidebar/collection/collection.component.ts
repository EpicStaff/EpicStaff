import { ChangeDetectionStrategy, Component, ElementRef, input, viewChild } from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';
import { AppSvgIconComponent } from '@shared/components';

import { RAG_STATUS_CONFIG, RAG_TYPE_CONFIG } from '../../../../../constants/constants';
import { CollectionDropTargetDirective } from '../../../../../directives/collection-drop-target.directive';
import { GetCollectionRequest } from '../../../../../models/collection.model';

@Component({
    selector: 'app-collection',
    templateUrl: './collection.component.html',
    styleUrls: ['./collection.component.scss'],
    imports: [MatTooltip, AppSvgIconComponent, CollectionDropTargetDirective],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CollectionComponent {
    collection = input.required<GetCollectionRequest>();
    selected = input<boolean>(false);

    private readonly nameButton = viewChild.required<ElementRef<HTMLButtonElement>>('nameButton');

    ragTypeConfig = RAG_TYPE_CONFIG;
    ragStatusConfig = RAG_STATUS_CONFIG;

    /** Focuses the card's name button, which opens the collection. */
    focus(): void {
        this.nameButton().nativeElement.focus();
    }
}
