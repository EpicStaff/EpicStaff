import {
    ChangeDetectionStrategy,
    Component,
    computed,
    inject,
    input,
    model,
    OnInit,
    output,
    signal,
} from '@angular/core';
import { AppSvgIconComponent } from '@shared/components';
import { copyWithFeedback } from '@shared/utils';
import { DateRangeFilter } from 'src/app/shared/models';

import { ToastService } from '../../../../services/notifications';
import {
    AuditConditionGroup,
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
    QUERY_EXAMPLES,
    QUERY_FIELDS,
    QUERY_OPERATORS,
    STATUS_OPTIONS,
} from '../../models/audit-filter-options';
import { AuditPresetScope } from '../../models/audit-preset.models';
import { AuditEventKind, AuditEventStatus, AuditNodeType } from '../../models/audit-session.models';
import { AuditPresetsStorageService } from '../../services/audit-presets-storage.service';
import {
    allowedKinds,
    AUDIT_FILTER_FIELDS,
    isFieldAvailable,
    isFieldEnabled,
} from '../../utils/audit-filter-compatibility.util';
import { insertQueryText } from '../../utils/insert-query-text.util';
import { AuditCheckboxEnumComponent } from '../audit-checkbox-enum/audit-checkbox-enum.component';
import { AuditConditionFilterComponent } from '../audit-condition-filter/audit-condition-filter.component';
import { AuditDateFilterComponent } from '../audit-date-filter/audit-date-filter.component';
import { AuditFilterGroupComponent } from '../audit-filter-group/audit-filter-group.component';
import { AuditFlowFilterComponent } from '../audit-flow-filter/audit-flow-filter.component';
import { AuditIdFilterComponent } from '../audit-id-filter/audit-id-filter.component';
import { AuditMatchScopeComponent } from '../audit-match-scope/audit-match-scope.component';
import { AuditPresetsComponent } from '../audit-presets/audit-presets.component';
import { AuditTokensFilterComponent } from '../audit-tokens-filter/audit-tokens-filter.component';

export type AuditFilterTab = 'builder' | 'query' | AuditPresetScope;

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
        AuditPresetsComponent,
    ],
    providers: [AuditPresetsStorageService],
    templateUrl: './audit-filters-panel.component.html',
    styleUrls: ['./audit-filters-panel.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AuditFiltersPanelComponent implements OnInit {
    public readonly closed = output<void>();
    public readonly applied = output<void>();
    public readonly cleared = output<void>();
    public readonly presetApplied = output<AuditFilterState>();

    public readonly flowNames = input<string[]>([]);
    public readonly agentOptions = input<AuditEnumOption[]>([]);
    public readonly toolOptions = input<AuditEnumOption[]>([]);
    public readonly queryError = input<string | null>(null);

    public readonly flowOptions = computed<AuditEnumOption[]>(() =>
        this.flowNames().map((name) => ({ value: name, label: name }))
    );

    public filter = model<AuditFilterState>(EMPTY_AUDIT_FILTER);

    public readonly kindOptions = KIND_OPTIONS;
    public readonly statusOptions = STATUS_OPTIONS;
    public readonly nodeTypeOptions = NODE_TYPE_OPTIONS;
    public readonly errorOperators = ERROR_OPERATORS;
    public readonly jsonOperators = JSON_OPERATORS;
    public readonly deepTextOperators = DEEP_TEXT_OPERATORS;
    public readonly queryExamples = QUERY_EXAMPLES;
    public readonly queryFields = QUERY_FIELDS;

    public readonly queryOperators = QUERY_OPERATORS;

    public activeTab = signal<AuditFilterTab>('builder');
    public isCreatingPreset = signal(false);
    public readonly isQueryEmpty = computed(() => !this.filter().query.trim());
    public readonly isPresetsTab = computed(() => this.activeTab() === 'mine' || this.activeTab() === 'shared');

    public readonly myPresetsCount = computed(() => this.presetsStorage.presetsInScope('mine').length);
    public readonly sharedPresetsCount = computed(() => this.presetsStorage.presetsInScope('shared').length);

    private readonly toastService = inject(ToastService);
    private readonly presetsStorage = inject(AuditPresetsStorageService);

    public ngOnInit(): void {
        this.activeTab.set(this.filter().mode);
        this.presetsStorage.load();
    }

    public setActiveTab(tab: AuditFilterTab): void {
        this.isCreatingPreset.set(false);
        this.activeTab.set(tab);
    }

    public createPreset(): void {
        this.isCreatingPreset.set(true);
        this.activeTab.set('mine');
    }

    public openQuery(query: string): void {
        this.filter.update((current) => ({ ...current, query, mode: 'query' }));
        this.activeTab.set('query');
    }

    public disabledKinds = computed(() => {
        const allowed = allowedKinds(this.filter());
        return this.kindOptions
            .map((option) => option.value)
            .filter((kind) => !allowed.includes(kind as AuditEventKind));
    });

    public isStatusEnabled = computed(() => isFieldAvailable('status', this.filter()));
    public isNodeTypeEnabled = computed(() => isFieldAvailable('nodeType', this.filter()));
    public isErrorEnabled = computed(() => isFieldAvailable('error', this.filter()));
    public isInputEnabled = computed(() => isFieldAvailable('input', this.filter()));
    public isOutputEnabled = computed(() => isFieldAvailable('output', this.filter()));
    public isDetailsEnabled = computed(() => isFieldAvailable('details', this.filter()));
    public isAgentEnabled = computed(() => isFieldAvailable('agent', this.filter()));
    public isToolEnabled = computed(() => isFieldAvailable('tool', this.filter()));
    public isTaskEnabled = computed(() => isFieldAvailable('task', this.filter()));
    public isPromptEnabled = computed(() => isFieldAvailable('prompt', this.filter()));
    public isMessageTextEnabled = computed(() => isFieldAvailable('messageText', this.filter()));
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

    public useExample(query: string): void {
        this.filter.update((current) => ({ ...current, query, mode: 'query' }));
    }

    public copyQuery(): void {
        copyWithFeedback(this.filter().query, this.toastService);
    }

    // Replaces the selection with the text and puts the cursor after it (or `caretFromEnd` chars before its end).
    public insertField(textarea: HTMLTextAreaElement, field: string, caretFromEnd = 0): void {
        const { query, caret } = insertQueryText(
            textarea.value,
            textarea.selectionStart,
            textarea.selectionEnd,
            field,
            caretFromEnd
        );
        textarea.value = query;
        textarea.setSelectionRange(caret, caret);
        textarea.focus();
        this.filter.update((current) => ({ ...current, query, mode: 'query' }));
    }

    public disabledStatuses = computed(() =>
        this.isStatusEnabled() ? [] : this.statusOptions.map((option) => option.value)
    );

    public disabledNodeTypes = computed(() =>
        this.isNodeTypeEnabled() ? [] : this.nodeTypeOptions.map((option) => option.value)
    );

    public readonly dateRange = computed<DateRangeFilter>(() => ({
        after: this.filter().dateFrom,
        before: this.filter().dateTo,
    }));

    public setDateRange(range: DateRangeFilter): void {
        this.updateBuilder({ dateFrom: range.after, dateTo: range.before });
    }

    public setMatchScope(matchScope: AuditMatchScopeState): void {
        this.filter.update((current) => ({ ...current, matchScope }));
    }

    public setKinds(kinds: string[]): void {
        this.updateBuilder({ kinds: kinds as AuditEventKind[] });
    }

    public setStatuses(statuses: string[]): void {
        this.updateBuilder({ statuses: statuses as AuditEventStatus[] });
    }

    public setNodeTypes(values: string[]): void {
        this.updateBuilder({ nodeTypes: values as AuditNodeType[] });
    }

    public setFlow(flow: AuditValuesFilter): void {
        this.updateBuilder({ flow });
    }

    public setId(id: AuditIdFilter): void {
        this.updateBuilder({ id });
    }

    public setError(error: AuditConditionGroup[]): void {
        this.updateBuilder({ error });
    }

    public setInput(input: AuditConditionGroup[]): void {
        this.updateBuilder({ input });
    }

    public setOutput(output: AuditConditionGroup[]): void {
        this.updateBuilder({ output });
    }

    public setDetails(details: AuditConditionGroup[]): void {
        this.updateBuilder({ details });
    }

    public setAgent(agent: AuditValuesFilter): void {
        this.updateBuilder({ agent });
    }

    public setTool(tool: AuditValuesFilter): void {
        this.updateBuilder({ tool });
    }

    public setTask(task: AuditConditionGroup[]): void {
        this.updateBuilder({ task });
    }

    public setPrompt(prompt: AuditConditionGroup[]): void {
        this.updateBuilder({ prompt });
    }

    public setMessageText(messageText: AuditConditionGroup[]): void {
        this.updateBuilder({ messageText });
    }

    public setTokens(tokens: AuditNumberFilter): void {
        this.updateBuilder({ tokens });
    }

    public setQuery(event: Event): void {
        const query = (event.target as HTMLTextAreaElement).value;
        this.filter.update((current) => ({ ...current, query, mode: 'query' }));
    }

    private updateBuilder(change: Partial<AuditFilterState>): void {
        this.filter.update((current) => ({ ...current, ...change, mode: 'builder' }));
    }
}
