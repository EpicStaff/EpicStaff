import { ChangeDetectionStrategy, Component, computed, effect, input, model, output } from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';

import { AuditCondition, AuditConditionJoin, AuditEnumOption, AuditFilterOp } from '../../models/audit-filter.models';
import { VALUE_FREE_OPS } from '../../models/audit-filter.models';
import { JOIN_OPTIONS } from '../../models/audit-filter-options';
import { AuditOperatorSelectComponent } from '../audit-operator-select/audit-operator-select.component';
import { AuditSelectComponent } from '../audit-select/audit-select.component';

@Component({
    selector: 'app-audit-condition-row',
    imports: [AuditOperatorSelectComponent, AuditSelectComponent, MatTooltip],
    templateUrl: './audit-condition-row.component.html',
    styleUrl: './audit-condition-row.component.scss',
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AuditConditionRowComponent {
    public condition = model.required<AuditCondition>();
    public operators = input<AuditFilterOp[]>([]);
    public showJoin = input<boolean>(true);
    public showKey = input<boolean>(true);
    public keyOptions = input<{ value: string; label: string }[]>([]);
    public readonly removed = output<void>();

    protected readonly hasKeyOptions = computed(() => this.keyOptions().length > 0);
    protected readonly keyItems = computed<AuditEnumOption[]>(() =>
        this.keyOptions().map((option) => ({ value: option.value, label: option.label }))
    );
    protected readonly joinOptions = JOIN_OPTIONS;
    protected needsValue = computed(() => !VALUE_FREE_OPS.includes(this.condition().op));

    private readonly autoSetKey = effect(() => {
        const options = this.keyOptions();
        const current = this.condition().key;
        if (options.length > 0 && (!current || !options.some((o) => o.value === current))) {
            this.condition.update((c) => ({ ...c, key: options[0].value }));
        }
    });

    protected setJoin(value: string): void {
        const join = value as AuditConditionJoin;
        this.condition.update((current) => ({ ...current, join }));
    }

    protected setKey(event: Event): void {
        const key = (event.target as HTMLInputElement).value;
        this.condition.update((current) => ({ ...current, key }));
    }

    protected setKeyFromSelect(value: string): void {
        this.condition.update((current) => ({ ...current, key: value }));
    }

    protected setOp(op: AuditFilterOp): void {
        this.condition.update((current) => ({ ...current, op }));
    }

    protected setValue(event: Event): void {
        const value = (event.target as HTMLInputElement).value;
        this.condition.update((current) => ({ ...current, value }));
    }
}
