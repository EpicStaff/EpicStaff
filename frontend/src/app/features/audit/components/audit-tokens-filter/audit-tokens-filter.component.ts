import { ChangeDetectionStrategy, Component, computed, input, model } from '@angular/core';
import { NumberStepperComponent } from '@shared/components';

import { AuditFilterOp, AuditNumberFilter, VALUE_FREE_OPS } from '../../models/audit-filter.models';
import { TOKEN_OPERATOR_LABELS, TOKEN_OPERATORS, TOKEN_STEP } from '../../models/audit-filter-options';
import { AuditOperatorSelectComponent } from '../audit-operator-select/audit-operator-select.component';

@Component({
    selector: 'app-audit-tokens-filter',
    standalone: true,
    imports: [AuditOperatorSelectComponent, NumberStepperComponent],
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
    // an empty string means "no tokens filter", so it maps to an empty stepper rather than 0
    protected readonly numericValue = computed(() => (this.filter().value === '' ? null : Number(this.filter().value)));

    protected setOp(op: AuditFilterOp): void {
        this.filter.update((current) => ({ ...current, op }));
    }

    protected setValue(value: number | null): void {
        this.filter.update((current) => ({ ...current, value: value === null ? '' : String(value) }));
    }
}
