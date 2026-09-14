import { ChangeDetectionStrategy, Component, model } from '@angular/core';

import { AuditEventStatus } from '../../models/audit-session.models';

const STATUS_OPTIONS: { value: AuditEventStatus; label: string }[] = [
    { value: 'completed', label: 'Completed' },
    { value: 'failed', label: 'Failed' },
];

@Component({
    selector: 'app-audit-status-filter',
    standalone: true,
    imports: [],
    templateUrl: './audit-status-filter.component.html',
    styleUrls: ['./audit-status-filter.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AuditStatusFilterComponent {
    public readonly options = STATUS_OPTIONS;
    public value = model<AuditEventStatus[]>([]);
    public isSelected(status: AuditEventStatus): boolean {
        return this.value().includes(status);
    }

    public toggle(status: AuditEventStatus): void {
        this.value.update((current) =>
            current.includes(status) ? current.filter((item) => item !== status) : [...current, status]
        );
    }
}
