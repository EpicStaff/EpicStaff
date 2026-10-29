import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';

import { ActionItem } from '../../models/flow-assistant.model';

@Component({
    selector: 'app-flow-assistant-actions',
    imports: [MatTooltip],
    templateUrl: './flow-assistant-actions.component.html',
    styleUrls: ['./flow-assistant-actions.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowAssistantActionsComponent {
    readonly actions = input.required<ActionItem[]>();
    readonly executed = output<ActionItem>();
}
