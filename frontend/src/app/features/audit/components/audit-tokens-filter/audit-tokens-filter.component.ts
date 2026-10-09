import { ChangeDetectionStrategy, Component, computed, input, model } from '@angular/core';

import { AuditFilterOp, AuditNumberFilter, VALUE_FREE_OPS } from '../../models/audit-filter.models';
import { TOKEN_OPERATOR_LABELS, TOKEN_OPERATORS, TOKEN_STEP } from '../../models/audit-filter-options';
import { AuditOperatorSelectComponent } from '../audit-operator-select/audit-operator-select.component';

@Component({
    selector: 'app-audit-tokens-filter',
    standalone: true,
    imports: [AuditOperatorSelectComponent],
    templateUrl: './audit-tokens-filter.component.html',
    styleUrl: './audit-tokens-filter.component.scss',
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AuditTokensFilterComponent {
    public filter = model.required<AuditNumberFilter>();
    public stepSize = input<number>(TOKEN_STEP);

    protected readonly operators = TOKEN_OPERATORS;
    protected readonly operatorLabels = TOKEN_OPERATOR_LABELS;
    protected readonly needsValue = computed(() => !VALUE_FREE_OPS.includes(this.filter().op));

    protected setOp(op: AuditFilterOp): void {
        this.filter.update((current) => ({ ...current, op }));
    }

    protected setValue(event: Event): void {
        const input = event.target as HTMLInputElement;
        const digits = input.value.replace(/\D/g, '');
        if (input.value !== digits) {
            input.value = digits;
        }
        this.filter.update((current) => ({ ...current, value: digits }));
    }

    protected stepBy(delta: number): void {
        this.filter.update((current) => {
            const next = Math.max(0, (Number(current.value) || 0) + delta);
            return { ...current, value: String(next) };
        });
    }
}
