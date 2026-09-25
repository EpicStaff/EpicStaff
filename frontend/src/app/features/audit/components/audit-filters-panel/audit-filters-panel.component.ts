import { ChangeDetectionStrategy, Component, computed, input, model, output, signal } from '@angular/core';
import { AppSvgIconComponent } from '@shared/components';
import { DateRangeFilter } from 'src/app/shared/models';

import {
    AuditCondition,
    AuditEnumOption,
    AuditFilterState,
    AuditIdFilter,
    AuditMatchScopeState,
    AuditNumberFilter,
    AuditValuesFilter,
    EMPTY_AUDIT_FILTER,
} from '../../models/audit-filter.models';
import {
    DEEP_TEXT_OPERATORS,
    ERROR_OPERATORS,
    JSON_OPERATORS,
    KIND_OPTIONS,
    NODE_TYPE_OPTIONS,
    RUN_TYPE_OPTIONS,
    STATUS_OPTIONS,
} from '../../models/audit-filter-options';
import { AuditEventKind, AuditEventStatus, AuditNodeType, AuditRunBucket } from '../../models/audit-session.models';
import {
    allowedKinds,
    AUDIT_FILTER_FIELDS,
    isFieldAvailable,
    isFieldEnabled,
} from '../../utils/audit-filter-compatibility.util';
import { AuditCheckboxEnumComponent } from '../audit-checkbox-enum/audit-checkbox-enum.component';
import { AuditConditionFilterComponent } from '../audit-condition-filter/audit-condition-filter.component';
import { AuditDateFilterComponent } from '../audit-date-filter/audit-date-filter.component';
import { AuditFilterGroupComponent } from '../audit-filter-group/audit-filter-group.component';
import { AuditFlowFilterComponent } from '../audit-flow-filter/audit-flow-filter.component';
import { AuditIdFilterComponent } from '../audit-id-filter/audit-id-filter.component';
import { AuditMatchScopeComponent } from '../audit-match-scope/audit-match-scope.component';
import { AuditTokensFilterComponent } from '../audit-tokens-filter/audit-tokens-filter.component';

export type AuditFilterTab = 'builder' | 'query' | 'presets';

@Component({
    selector: 'app-audit-filters-panel',
    standalone: true,
    imports: [
        AppSvgIconComponent,
        AuditCheckboxEnumComponent,
        AuditFilterGroupComponent,
        AuditFlowFilterComponent,
        AuditIdFilterComponent,
        AuditConditionFilterComponent,
        AuditDateFilterComponent,
        AuditTokensFilterComponent,
        AuditMatchScopeComponent,
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
    public readonly agentOptions = input<AuditEnumOption[]>([]);
    public readonly toolOptions = input<AuditEnumOption[]>([]);

    public readonly flowOptions = computed<AuditEnumOption[]>(() =>
        this.flowNames().map((name) => ({ value: name, label: name }))
    );

    public activeTab = signal<AuditFilterTab>('builder');
    public filter = model<AuditFilterState>(EMPTY_AUDIT_FILTER);

    public readonly kindOptions = KIND_OPTIONS;
    public readonly statusOptions = STATUS_OPTIONS;
    public readonly runTypeOptions = RUN_TYPE_OPTIONS;
    public readonly nodeTypeOptions = NODE_TYPE_OPTIONS;
    public readonly errorOperators = ERROR_OPERATORS;
    public readonly jsonOperators = JSON_OPERATORS;
    public readonly deepTextOperators = DEEP_TEXT_OPERATORS;

    public setActiveTab(tab: AuditFilterTab): void {
        this.activeTab.set(tab);
    }

    public disabledKinds = computed(() => {
        const allowed = allowedKinds(this.filter());
        return this.kindOptions
            .map((option) => option.value)
            .filter((kind) => !allowed.includes(kind as AuditEventKind));
    });

    public isStatusEnabled = computed(() => isFieldAvailable('status', this.filter()));
    public isNodeTypeEnabled = computed(() => isFieldAvailable('nodeType', this.filter()));
    public isRunTypeEnabled = computed(() => isFieldAvailable('run', this.filter()));
    public isErrorEnabled = computed(() => isFieldAvailable('error', this.filter()));
    public isInputEnabled = computed(() => isFieldAvailable('input', this.filter()));
    public isOutputEnabled = computed(() => isFieldAvailable('output', this.filter()));
    public isDetailsEnabled = computed(() => isFieldAvailable('details', this.filter()));
    public isAgentEnabled = computed(() => isFieldAvailable('agent', this.filter()));
    public isToolEnabled = computed(() => isFieldAvailable('tool', this.filter()));
    public isTaskEnabled = computed(() => isFieldAvailable('task', this.filter()));
    public isPromptEnabled = computed(() => isFieldAvailable('prompt', this.filter()));
    public isMessageTextEnabled = computed(() => isFieldAvailable('messageText', this.filter()));
    public isMessageThoughtEnabled = computed(() => isFieldAvailable('messageThought', this.filter()));
    public isTokensEnabled = computed(() => isFieldAvailable('tokens', this.filter()));

    public agentHint = computed(() => {
        const state = this.filter();
        if (AUDIT_FILTER_FIELDS['tool'].isActive(state)) {
            return 'Not available together with Tool';
        }
        return isFieldEnabled('agent', state) ? '' : 'Only events carry an agent';
    });

    public toolHint = computed(() => {
        const state = this.filter();
        if (AUDIT_FILTER_FIELDS['agent'].isActive(state)) {
            return 'Not available together with Agent';
        }
        return isFieldEnabled('tool', state) ? '' : 'Only events carry a tool';
    });

    public disabledStatuses = computed(() =>
        this.isStatusEnabled() ? [] : this.statusOptions.map((option) => option.value)
    );

    public disabledNodeTypes = computed(() =>
        this.isNodeTypeEnabled() ? [] : this.nodeTypeOptions.map((option) => option.value)
    );

    public disabledRunTypes = computed(() =>
        this.isRunTypeEnabled() ? [] : this.runTypeOptions.map((option) => option.value)
    );

    public readonly dateRange = computed<DateRangeFilter>(() => ({
        after: this.filter().dateFrom,
        before: this.filter().dateTo,
    }));

    public setDateRange(range: DateRangeFilter): void {
        this.filter.update((current) => ({ ...current, dateFrom: range.after, dateTo: range.before }));
    }

    public setMatchScope(matchScope: AuditMatchScopeState): void {
        this.filter.update((current) => ({ ...current, matchScope }));
    }

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

    public setAgent(agent: AuditValuesFilter): void {
        this.filter.update((current) => ({ ...current, agent }));
    }

    public setTool(tool: AuditValuesFilter): void {
        this.filter.update((current) => ({ ...current, tool }));
    }

    public setTask(task: AuditCondition[]): void {
        this.filter.update((current) => ({ ...current, task }));
    }

    public setPrompt(prompt: AuditCondition[]): void {
        this.filter.update((current) => ({ ...current, prompt }));
    }

    public setMessageText(messageText: AuditCondition[]): void {
        this.filter.update((current) => ({ ...current, messageText }));
    }

    public setMessageThought(messageThought: AuditCondition[]): void {
        this.filter.update((current) => ({ ...current, messageThought }));
    }

    public setTokens(tokens: AuditNumberFilter): void {
        this.filter.update((current) => ({ ...current, tokens }));
    }
}
