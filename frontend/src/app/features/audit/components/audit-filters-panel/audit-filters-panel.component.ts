import { ChangeDetectionStrategy, Component, computed, model, output, signal } from '@angular/core';

import { AuditFilterState, EMPTY_AUDIT_FILTER } from '../../models/audit-filter.models';
import { AuditEventKind, AuditEventStatus, AuditNodeType, AuditRunBucket } from '../../models/audit-session.models';
import { allowedKinds, isFieldEnabled } from '../../utils/audit-filter-compatibility.util';
import { AuditCheckboxEnumComponent, AuditEnumOption } from '../audit-checkbox-enum/audit-checkbox-enum.component';
import { AuditFilterGroupComponent } from '../audit-filter-group/audit-filter-group.component';

export type AuditFilterTab = 'builder' | 'query' | 'presets';

@Component({
    selector: 'app-audit-filters-panel',
    standalone: true,
    imports: [AuditCheckboxEnumComponent, AuditFilterGroupComponent],
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

    public readonly runTypeOptions: AuditEnumOption[] = [
        { value: 'manual', label: 'Manual' },
        { value: 'api', label: 'API' },
    ];

    public readonly nodeTypeOptions: AuditEnumOption[] = [
        { value: 'AGENT', label: 'Agent' },
        { value: 'TASK', label: 'Task' },
        { value: 'PYTHON', label: 'Python' },
        { value: 'KNOWLEDGE', label: 'Knowledge' },
        { value: 'FILE_EXTRACTOR', label: 'File Extractor' },
        { value: 'AUDIO_TRANSCRIPTION', label: 'Audio Transcription' },
        { value: 'DECISION_TABLE', label: 'Decision Table' },
        { value: 'CLASSIFICATION_DECISION_TABLE', label: 'Classification Decision Table' },
        { value: 'END', label: 'End' },
        { value: 'SCHEDULE_TRIGGER', label: 'Schedule Trigger' },
        { value: 'WEBHOOK_TRIGGER', label: 'Webhook Trigger' },
        { value: 'TELEGRAM_TRIGGER', label: 'Telegram Trigger' },
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
    public isNodeTypeEnabled = computed(() => isFieldEnabled('nodeType', this.filter()));
    public isRunTypeEnabled = computed(() => isFieldEnabled('run', this.filter()));

    public disabledStatuses = computed(() =>
        this.isStatusEnabled() ? [] : this.statusOptions.map((option) => option.value)
    );

    public disabledNodeTypes = computed(() =>
        this.isNodeTypeEnabled() ? [] : this.nodeTypeOptions.map((option) => option.value)
    );

    public disabledRunTypes = computed(() =>
        this.isRunTypeEnabled() ? [] : this.runTypeOptions.map((option) => option.value)
    );

    public setKinds(kinds: string[]): void {
        this.filter.update((current) => ({ ...current, kinds: kinds as AuditEventKind[] }));
    }

    public setStatuses(statuses: string[]): void {
        this.filter.update((current) => ({ ...current, statuses: statuses as AuditEventStatus[] }));
    }

    public setRunTypes(values: string[]): void {
        this.filter.update((current) => ({ ...current, runTypes: values as AuditRunBucket[] }));
    }

    public setNodeTypes(values: string[]): void {
        this.filter.update((current) => ({ ...current, nodeTypes: values as AuditNodeType[] }));
    }
}
