import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { AppSvgIconComponent, LabelDropdownComponent } from '@shared/components';

import { ToolsBulkActionKind } from '../../../../services/tools-view-storage.service';

export interface ToolsBulkAction {
    label: string;
    kind: ToolsBulkActionKind;
    hasSubmenu?: boolean;
}

@Component({
    selector: 'app-tools-bulk-actions-menu',
    imports: [AppSvgIconComponent, LabelDropdownComponent],
    templateUrl: './tools-bulk-actions-menu.component.html',
    styleUrls: ['./tools-bulk-actions-menu.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ToolsBulkActionsMenuComponent {
    public readonly actions = input<ToolsBulkAction[]>([]);
    /** Renders an "Add Label" row that opens a label-dropdown as its picker. */
    public readonly showAddLabel = input<boolean>(false);
    /** Preselected label ids for the label dropdown. */
    public readonly initialLabelIds = input<number[]>([]);

    public readonly actionSelected = output<ToolsBulkAction>();
    public readonly labelsChanged = output<number[]>();

    public onSelect(action: ToolsBulkAction): void {
        this.actionSelected.emit(action);
    }

    public onLabelsChanged(ids: number[]): void {
        this.labelsChanged.emit(ids);
    }
}
