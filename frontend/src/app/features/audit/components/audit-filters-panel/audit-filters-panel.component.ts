import { ChangeDetectionStrategy, Component, model, output, signal } from '@angular/core';

import { AuditFilterState, EMPTY_AUDIT_FILTER } from '../../models/audit-filter.models';
import { AuditEventStatus } from '../../models/audit-session.models';
import { AuditStatusFilterComponent } from '../audit-status-filter/audit-status-filter.component';

export type AuditFilterTab = 'builder' | 'query' | 'presets';

@Component({
    selector: 'app-audit-filters-panel',
    standalone: true,
    imports: [AuditStatusFilterComponent],
    templateUrl: './audit-filters-panel.component.html',
    styleUrls: ['./audit-filters-panel.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AuditFiltersPanelComponent {
    public readonly closed = output<void>();
    public readonly applied = output<void>();
    public readonly cleared = output<void>();

    public activeTab = signal<AuditFilterTab>('builder');
    public filter = model<AuditFilterState>(EMPTY_AUDIT_FILTER);
    public setStatuses(statuses: AuditEventStatus[]): void {
        this.filter.update((current) => ({ ...current, statuses }));
    }

    public setActiveTab(tab: AuditFilterTab): void {
        this.activeTab.set(tab);
    }
}
