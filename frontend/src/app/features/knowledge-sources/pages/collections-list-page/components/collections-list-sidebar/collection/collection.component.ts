import { CdkMenu, CdkMenuItem, CdkMenuTrigger } from '@angular/cdk/menu';
import { ConnectedPosition } from '@angular/cdk/overlay';
import { ChangeDetectionStrategy, Component, ElementRef, input, output, viewChild } from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';
import { AppSvgIconComponent, CheckboxComponent } from '@shared/components';
import { HasPermissionDirective, TooltipOnOverflowDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';

import { RAG_STATUS_CONFIG, RAG_TYPE_CONFIG } from '../../../../../constants/constants';
import { CollectionDropTargetDirective } from '../../../../../directives/collection-drop-target.directive';
import { GetCollectionRequest } from '../../../../../models/collection.model';

@Component({
    selector: 'app-collection',
    templateUrl: './collection.component.html',
    styleUrls: ['./collection.component.scss'],
    imports: [
        MatTooltip,
        TooltipOnOverflowDirective,
        AppSvgIconComponent,
        CollectionDropTargetDirective,
        CheckboxComponent,
        HasPermissionDirective,
        CdkMenuTrigger,
        CdkMenu,
        CdkMenuItem,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CollectionComponent {
    collection = input.required<GetCollectionRequest>();
    selected = input<boolean>(false);
    /** The list is picking collections for a bulk action: the card shows a checkbox instead of its ⋮ menu. */
    selectMode = input<boolean>(false);
    /** Picked for the bulk action; only shown in select mode. */
    checked = input<boolean>(false);
    /** Its export has not finished yet: the menu's Export is disabled until it has, so no second job starts. */
    exporting = input<boolean>(false);

    readonly checkedChange = output<boolean>();
    readonly exportRequested = output<void>();

    private readonly nameButton = viewChild.required<ElementRef<HTMLButtonElement>>('nameButton');

    ragTypeConfig = RAG_TYPE_CONFIG;
    ragStatusConfig = RAG_STATUS_CONFIG;

    // Below the ⋮, right edges aligned: the card sits at the sidebar's right edge.
    protected readonly menuPositions: ConnectedPosition[] = [
        { originX: 'end', originY: 'bottom', overlayX: 'end', overlayY: 'top', offsetY: 4 },
        { originX: 'end', originY: 'top', overlayX: 'end', overlayY: 'bottom', offsetY: -4 },
    ];

    protected readonly ActionCode = ActionCode;
    protected readonly ResourceCode = ResourceCode;

    /** Focuses the card's name button, which opens the collection. */
    focus(): void {
        this.nameButton().nativeElement.focus();
    }
}
