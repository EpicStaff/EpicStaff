import { ChangeDetectionStrategy, Component, computed, input, model, output, signal } from '@angular/core';

import {
    AuditCondition,
    AuditFilterState,
    AuditIdFilter,
    AuditValuesFilter,
    EMPTY_AUDIT_FILTER,
} from '../../models/audit-filter.models';
import {
    ERROR_OPERATORS,
    JSON_OPERATORS,
    KIND_OPTIONS,
    NODE_TYPE_OPTIONS,
    RUN_TYPE_OPTIONS,
    STATUS_OPTIONS,
} from '../../models/audit-filter-options';
import { AuditEventKind, AuditEventStatus, AuditNodeType, AuditRunBucket } from '../../models/audit-session.models';
import { allowedKinds, isFieldEnabled } from '../../utils/audit-filter-compatibility.util';
import { AuditCheckboxEnumComponent } from '../audit-checkbox-enum/audit-checkbox-enum.component';
import { AuditConditionFilterComponent } from '../audit-condition-filter/audit-condition-filter.component';
import { AuditFilterGroupComponent } from '../audit-filter-group/audit-filter-group.component';
import { AuditFlowFilterComponent } from '../audit-flow-filter/audit-flow-filter.component';
import { AuditIdFilterComponent } from '../audit-id-filter/audit-id-filter.component';

export type AuditFilterTab = 'builder' | 'query' | 'presets';

@Component({
    selector: 'app-audit-filters-panel',
    standalone: true,
    imports: [
        AuditCheckboxEnumComponent,
        AuditFilterGroupComponent,
        AuditFlowFilterComponent,
        AuditIdFilterComponent,
        AuditConditionFilterComponent,
    ],
    templateUrl: './audit-filters-panel.component.html',
    styleUrls: ['./audit-filters-panel.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AuditFiltersPanelComponent {
    public readonly closed = output<void>();
    public readonly applied = output<void>();
    public readonly cleared = output<void>();

    public readonly flowNames = input<string[]>([]);

    public activeTab = signal<AuditFilterTab>('builder');
    public filter = model<AuditFilterState>(EMPTY_AUDIT_FILTER);

    public readonly kindOptions = KIND_OPTIONS;
    public readonly statusOptions = STATUS_OPTIONS;
    public readonly runTypeOptions = RUN_TYPE_OPTIONS;
    public readonly nodeTypeOptions = NODE_TYPE_OPTIONS;
    public readonly errorOperators = ERROR_OPERATORS;
    public readonly jsonOperators = JSON_OPERATORS;

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
    public isErrorEnabled = computed(() => isFieldEnabled('error', this.filter()));
    public isInputEnabled = computed(() => isFieldEnabled('input', this.filter()));
    public isOutputEnabled = computed(() => isFieldEnabled('output', this.filter()));
    public isDetailsEnabled = computed(() => isFieldEnabled('details', this.filter()));

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

    public setFlow(flow: AuditValuesFilter): void {
        this.filter.update((current) => ({ ...current, flow }));
    }

    public setId(id: AuditIdFilter): void {
        this.filter.update((current) => ({ ...current, id }));
    }

    public setError(error: AuditCondition[]): void {
        this.filter.update((current) => ({ ...current, error }));
    }

    public setInput(input: AuditCondition[]): void {
        this.filter.update((current) => ({ ...current, input }));
    }

    public setOutput(output: AuditCondition[]): void {
        this.filter.update((current) => ({ ...current, output }));
    }

    public setDetails(details: AuditCondition[]): void {
        this.filter.update((current) => ({ ...current, details }));
    }
}
