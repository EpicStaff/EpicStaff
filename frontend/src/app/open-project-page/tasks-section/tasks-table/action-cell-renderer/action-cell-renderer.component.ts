import { ChangeDetectionStrategy, Component } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ICellRendererAngularComp } from 'ag-grid-angular';

@Component({
    selector: 'app-action-cell-renderer',
    standalone: true,
    imports: [MatTooltipModule],
    template: `<i
        class="ti ti-settings action-icon"
        matTooltip="Task settings"
        matTooltipPosition="left"
    ></i>`,
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ActionCellRendererComponent implements ICellRendererAngularComp {
    agInit(): void {}

    refresh(): boolean {
        return false;
    }
}
