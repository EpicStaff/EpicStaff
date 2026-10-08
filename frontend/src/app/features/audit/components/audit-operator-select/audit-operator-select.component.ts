import { ChangeDetectionStrategy, Component, computed, input, model } from '@angular/core';

import { AuditEnumOption, AuditFilterOp } from '../../models/audit-filter.models';
import { OPERATOR_LABELS } from '../../models/audit-filter-options';
import { AuditSelectComponent } from '../audit-select/audit-select.component';

@Component({
    selector: 'app-audit-operator-select',
    standalone: true,
    imports: [AuditSelectComponent],
    templateUrl: './audit-operator-select.component.html',
    styleUrls: ['./audit-operator-select.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AuditOperatorSelectComponent {
    public operators = input<AuditFilterOp[]>([]);
    public selectedOperator = model.required<AuditFilterOp>();
    public labels = input<Record<string, string>>({});

    protected readonly options = computed<AuditEnumOption[]>(() =>
        this.operators().map((operator) => ({ value: operator, label: this.labelFor(operator) }))
    );

    public labelFor(operator: string): string {
        return this.labels()[operator] ?? OPERATOR_LABELS[operator] ?? operator;
    }

    protected onValueChange(value: string): void {
        this.selectedOperator.set(value as AuditFilterOp);
    }
}
