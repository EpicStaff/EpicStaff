import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
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

    protected isConditionChip(key: string): boolean {
        return CONDITION_CHIP_KEYS.has(key);
    }
}
