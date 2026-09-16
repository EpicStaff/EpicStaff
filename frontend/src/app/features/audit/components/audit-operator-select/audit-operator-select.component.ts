import { ChangeDetectionStrategy, Component, input, model } from '@angular/core';

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
    public operators = input<string[]>([]);
    public selectedOperator = model.required<string>();

    public labelFor(operator: string): string {
        return OPERATOR_LABELS[operator] ?? operator;
    }

    public onSelect(event: Event): void {
        this.selectedOperator.set((event.target as HTMLSelectElement).value);
    }
}
