import { ChangeDetectionStrategy, Component } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ICellRendererAngularComp } from 'ag-grid-angular';

@Component({
    selector: 'app-agent-settings-cell-renderer',
    standalone: true,
    imports: [MatTooltipModule],
    template: `<i
        class="ti ti-settings action-icon"
        matTooltip="Agent settings"
        matTooltipPosition="left"
    ></i>`,
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AgentSettingsCellRendererComponent implements ICellRendererAngularComp {
    agInit(): void {}

    refresh(): boolean {
        return false;
    }
}
