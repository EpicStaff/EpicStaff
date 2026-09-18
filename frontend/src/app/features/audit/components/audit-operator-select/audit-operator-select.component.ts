import { ChangeDetectionStrategy, Component, input, model } from '@angular/core';

import { AuditFilterOp } from '../../models/audit-filter.models';
import { OPERATOR_LABELS } from '../../models/audit-filter-options';

@Component({
    selector: 'app-audit-operator-select',
    standalone: true,
    imports: [],
    templateUrl: './audit-operator-select.component.html',
    styleUrls: ['./audit-operator-select.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AuditOperatorSelectComponent {
    public operators = input<AuditFilterOp[]>([]);
    public selectedOperator = model.required<AuditFilterOp>();

    public labelFor(operator: string): string {
        return OPERATOR_LABELS[operator] ?? operator;
    }

    public onSelect(event: Event): void {
        this.selectedOperator.set((event.target as HTMLSelectElement).value as AuditFilterOp);
    }
}
