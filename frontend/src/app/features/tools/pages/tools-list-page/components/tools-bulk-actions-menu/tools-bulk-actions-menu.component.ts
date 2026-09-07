import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { AppSvgIconComponent, LabelDropdownComponent } from '@shared/components';

import { ToolsBulkActionKind } from '../../../../services/tools-view-storage.service';

export interface ToolsBulkAction {
    label: string;
    kind: ToolsBulkActionKind;
    hasSubmenu?: boolean;
    isPermitted: boolean;
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
    /** Renders a "Manage Labels" row that opens a label-dropdown as its picker. */
    public readonly showManageLabels = input<boolean>(false);
    /** Labels applied to every currently selected tool (render as checked). */
    public readonly commonLabelIds = input<number[]>([]);
    /** Labels applied to some but not all currently selected tools (render as indeterminate). */
    public readonly partialLabelIds = input<number[]>([]);

    public readonly actionSelected = output<ToolsBulkAction>();
    public readonly labelsApplied = output<{ addLabelIds: number[]; removeLabelIds: number[] }>();

    public onSelect(action: ToolsBulkAction): void {
        this.actionSelected.emit(action);
    }

    public onLabelsApplied(change: { addLabelIds: number[]; removeLabelIds: number[] }): void {
        this.labelsApplied.emit(change);
    }
}
