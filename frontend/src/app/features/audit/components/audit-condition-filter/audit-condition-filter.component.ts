import { ChangeDetectionStrategy, Component, input, model } from '@angular/core';

import { AuditCondition, AuditFilterOp, createAuditCondition } from '../../models/audit-filter.models';
import { AuditConditionRowComponent } from '../audit-condition-row/audit-condition-row.component';

@Component({
    selector: 'app-audit-condition-filter',
    standalone: true,
    imports: [AuditConditionRowComponent],
    templateUrl: './audit-condition-filter.component.html',
    styleUrl: './audit-condition-filter.component.scss',
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AuditConditionFilterComponent {
    public conditions = model.required<AuditCondition[]>();
    public operators = input<AuditFilterOp[]>([]);
    public showKey = input<boolean>(true);

    protected addCondition(): void {
        this.conditions.update((current) => [...current, createAuditCondition()]);
    }

    protected updateCondition(next: AuditCondition): void {
        this.conditions.update((current) => current.map((item) => (item.id === next.id ? next : item)));
    }

    protected removeCondition(id: string): void {
        this.conditions.update((current) => current.filter((item) => item.id !== id));
    }
}
