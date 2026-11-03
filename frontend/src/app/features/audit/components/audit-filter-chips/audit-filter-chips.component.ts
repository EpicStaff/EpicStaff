import { ChangeDetectionStrategy, Component, ElementRef, input, output, viewChildren } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';

import { AuditFilterChip } from '../../utils/describe-audit-filter.util';

const CONDITION_CHIP_KEYS: ReadonlySet<string> = new Set([
    'error',
    'input',
    'output',
    'details',
    'task',
    'prompt',
    'messageText',
]);

@Component({
    selector: 'app-audit-filter-chips',
    standalone: true,
    imports: [MatTooltipModule],
    templateUrl: './audit-filter-chips.component.html',
    styleUrls: ['./audit-filter-chips.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AuditFilterChipsComponent {
    public chips = input<AuditFilterChip[]>([]);
    public readonly removed = output<string>();
    public readonly cleared = output<void>();

    private readonly removeButtons = viewChildren<ElementRef<HTMLButtonElement>>('removeButton');

    /** Focuses the remove button of the chip at `index`, or of the last chip when fewer are left. */
    public focusChip(index: number): void {
        const buttons = this.removeButtons();
        buttons[Math.min(index, buttons.length - 1)]?.nativeElement.focus();
    }

    protected isConditionChip(key: string): boolean {
        return CONDITION_CHIP_KEYS.has(key);
    }
}
