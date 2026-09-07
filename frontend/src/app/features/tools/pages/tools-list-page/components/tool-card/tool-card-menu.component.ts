import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { LabelDropdownComponent } from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';

import { ToolCardMenuAction } from './tool-card.model';

@Component({
    selector: 'app-tool-card-menu',
    imports: [LabelDropdownComponent, HasPermissionDirective],
    templateUrl: './tool-card-menu.component.html',
    styleUrls: ['./tool-card-menu.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ToolCardMenuComponent {
    /** Labels currently assigned to the tool this menu belongs to. */
    public readonly toolLabelIds = input<number[]>([]);

    public readonly actionSelected = output<ToolCardMenuAction>();
    public readonly labelsChanged = output<number[]>();

    public onSelect(action: ToolCardMenuAction): void {
        this.actionSelected.emit(action);
    }

    public onLabelsChanged(ids: number[]): void {
        this.labelsChanged.emit(ids);
    }

    protected readonly ActionCode = ActionCode;
    protected readonly ResourceCode = ResourceCode;
}
