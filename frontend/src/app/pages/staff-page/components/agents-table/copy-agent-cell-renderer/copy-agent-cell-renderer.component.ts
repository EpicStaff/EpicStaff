import { ChangeDetectionStrategy, Component } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ICellRendererAngularComp } from 'ag-grid-angular';

@Component({
    selector: 'app-copy-agent-cell-renderer',
    standalone: true,
    imports: [MatTooltipModule],
    template: `<i
        class="ti ti-copy action-icon"
        matTooltip="Duplicate agent"
        matTooltipPosition="left"
    ></i>`,
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CopyAgentCellRendererComponent implements ICellRendererAngularComp {
    agInit(): void {}

    refresh(): boolean {
        return false;
    }
}
