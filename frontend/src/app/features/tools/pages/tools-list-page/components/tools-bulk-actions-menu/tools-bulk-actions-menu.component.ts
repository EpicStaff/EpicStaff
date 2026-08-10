import { ChangeDetectionStrategy, Component, output } from '@angular/core';

// TODO: fill in actions once bulk-actions behavior is defined.
export type ToolsBulkAction = never;

@Component({
    selector: 'app-tools-bulk-actions-menu',
    standalone: true,
    templateUrl: './tools-bulk-actions-menu.component.html',
    styleUrls: ['./tools-bulk-actions-menu.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ToolsBulkActionsMenuComponent {
    public readonly actionSelected = output<ToolsBulkAction>();
}
