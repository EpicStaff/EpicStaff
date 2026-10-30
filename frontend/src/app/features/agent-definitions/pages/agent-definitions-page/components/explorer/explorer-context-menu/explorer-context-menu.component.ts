import { CdkTrapFocus } from '@angular/cdk/a11y';
import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';

import { ExplorerMenuItem, ExplorerMenuPosition } from './explorer-menu.model';

@Component({
    selector: 'app-explorer-context-menu',
    imports: [CdkTrapFocus, MatTooltip],
    templateUrl: './explorer-context-menu.component.html',
    styleUrls: ['./explorer-context-menu.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ExplorerContextMenuComponent {
    open = input.required<boolean>();
    position = input.required<ExplorerMenuPosition>();
    items = input.required<ExplorerMenuItem[]>();

    action = output<string>();
    close = output<void>();

    onAction(id: string, disabled: boolean | undefined): void {
        if (disabled) return;
        this.action.emit(id);
    }

    /** Escape closes the menu only, not a dialog around it; the focus trap returns the focus to the ⋮ button. */
    onEscape(event: Event): void {
        event.stopPropagation();
        this.close.emit();
    }
}
