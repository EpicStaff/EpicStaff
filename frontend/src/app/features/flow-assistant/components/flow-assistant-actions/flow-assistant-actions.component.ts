import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

import { ActionItem } from '../../models/flow-assistant.model';

@Component({
    selector: 'app-flow-assistant-actions',
    standalone: true,
    imports: [],
    templateUrl: './flow-assistant-actions.component.html',
    styleUrls: ['./flow-assistant-actions.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowAssistantActionsComponent {
    readonly actions = input.required<ActionItem[]>();
    readonly executed = output<ActionItem>();
}
