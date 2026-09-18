import { ChangeDetectionStrategy, Component, computed, input, model, output } from '@angular/core';

import { AuditCondition, AuditConditionJoin, AuditFilterOp } from '../../models/audit-filter.models';
import { VALUE_FREE_OPS } from '../../models/audit-filter.models';
import { JOIN_OPTIONS } from '../../models/audit-filter-options';
import { AuditOperatorSelectComponent } from '../audit-operator-select/audit-operator-select.component';

@Component({
    selector: 'app-audit-condition-row',
    standalone: true,
    imports: [AuditOperatorSelectComponent],
    templateUrl: './audit-condition-row.component.html',
    styleUrl: './audit-condition-row.component.scss',
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AuditConditionRowComponent {
    public condition = model.required<AuditCondition>();
    public operators = input<AuditFilterOp[]>([]);
    public showJoin = input<boolean>(true);
    public showKey = input<boolean>(true);
    public readonly removed = output<void>();

    protected readonly joinOptions = JOIN_OPTIONS;
    protected needsValue = computed(() => !VALUE_FREE_OPS.includes(this.condition().op));

    protected setJoin(event: Event): void {
        const join = (event.target as HTMLSelectElement).value as AuditConditionJoin;
        this.condition.update((current) => ({ ...current, join }));
    }

    protected setKey(event: Event): void {
        const key = (event.target as HTMLInputElement).value;
        this.condition.update((current) => ({ ...current, key }));
    }

    protected setOp(op: AuditFilterOp): void {
        this.condition.update((current) => ({ ...current, op }));
    }

    protected setValue(event: Event): void {
        const value = (event.target as HTMLInputElement).value;
        this.condition.update((current) => ({ ...current, value }));
    }
}
