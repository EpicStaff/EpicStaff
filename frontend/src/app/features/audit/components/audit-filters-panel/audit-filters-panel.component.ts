import { ChangeDetectionStrategy, Component, computed, model, output, signal } from '@angular/core';

import { AuditFilterState, EMPTY_AUDIT_FILTER } from '../../models/audit-filter.models';
import { AuditEventKind, AuditEventStatus } from '../../models/audit-session.models';
import { allowedKinds, isFieldEnabled } from '../../utils/audit-filter-compatibility.util';
import { AuditCheckboxEnumComponent, AuditEnumOption } from '../audit-checkbox-enum/audit-checkbox-enum.component';

export type AuditFilterTab = 'builder' | 'query' | 'presets';

@Component({
    selector: 'app-audit-filters-panel',
    standalone: true,
    imports: [AuditCheckboxEnumComponent],
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

    public readonly kindOptions: AuditEnumOption[] = [
        { value: 'session', label: 'Session' },
        { value: 'node', label: 'Node' },
        { value: 'event', label: 'Event' },
    ];

    public readonly statusOptions: AuditEnumOption[] = [
        { value: 'completed', label: 'Completed' },
        { value: 'failed', label: 'Failed' },
    ];

    public setActiveTab(tab: AuditFilterTab): void {
        this.activeTab.set(tab);
    }

    public disabledKinds = computed(() => {
        const allowed = allowedKinds(this.filter());
        return this.kindOptions
            .map((option) => option.value)
            .filter((kind) => !allowed.includes(kind as AuditEventKind));
    });

    public isStatusEnabled = computed(() => isFieldEnabled('status', this.filter()));

    public setKinds(kinds: string[]): void {
        this.filter.update((current) => ({ ...current, kinds: kinds as AuditEventKind[] }));
    }

    public setStatuses(statuses: string[]): void {
        this.filter.update((current) => ({ ...current, statuses: statuses as AuditEventStatus[] }));
    }
}
