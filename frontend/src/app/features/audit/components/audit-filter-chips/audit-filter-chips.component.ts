import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

import { AuditFilterChip } from '../../utils/describe-audit-filter.util';

@Component({
    selector: 'app-audit-filter-chips',
    standalone: true,
    imports: [],
    templateUrl: './audit-filter-chips.component.html',
    styleUrls: ['./audit-filter-chips.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AuditFilterChipsComponent {
    public chips = input<AuditFilterChip[]>([]);
    public readonly removed = output<string>();
    public readonly cleared = output<void>();
}
