import { ChangeDetectionStrategy, Component, computed, inject, OnInit, output, signal } from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';
import { AppSvgIconComponent } from '@shared/components';
import { LabelDto } from '@shared/models';

import { AuditConditionFilterComponent } from '../../../../../audit/components/audit-condition-filter/audit-condition-filter.component';
import {
    AuditConditionGroup,
    AuditFilterOp,
    createAuditConditionGroup,
} from '../../../../../audit/models/audit-filter.models';
import { DEEP_TEXT_OPERATORS } from '../../../../../audit/models/audit-filter-options';
import { EMPTY_FLOWS_FILTER, FlowsFilterState } from '../../../../models/flow-filter.model';
import { FlowFilterPresetsStorageService } from '../../../../services/flow-filter-presets-storage.service';
import { FlowsStorageService } from '../../../../services/flows-storage.service';
import { LabelsStorageService } from '../../../../services/labels-storage.service';
import { FlowsCheckboxEnumComponent, FlowsEnumOption } from '../flows-checkbox-enum/flows-checkbox-enum.component';
import { FlowsFilterGroupComponent } from '../flows-filter-group/flows-filter-group.component';
import { FlowsFilterPresetsComponent } from '../flows-filter-presets/flows-filter-presets.component';

const CUSTOM_KEY_OPTIONS: { value: string; label: string }[] = [
    { value: 'flow_name', label: 'Flow Name' },
    { value: 'description', label: 'Description' },
    { value: 'label', label: 'Label' },
];

/** Keys from FlowsFilterState that the sidebar controls (excludes sortOrder, searchTerm). */
type SidebarFilterKeys = 'includedFlowIds' | 'includedLabelIds' | 'customConditions';

type SidebarFilterState = Pick<FlowsFilterState, SidebarFilterKeys>;

function snapshotSidebarFilter(filter: FlowsFilterState): SidebarFilterState {
    return {
        includedFlowIds: filter.includedFlowIds ? [...filter.includedFlowIds] : null,
        includedLabelIds: filter.includedLabelIds ? [...filter.includedLabelIds] : null,
        customConditions: filter.customConditions.map((group) => ({
            ...group,
            conditions: group.conditions.map((c) => ({ ...c })),
        })),
    };
}

type FlowsFilterTab = 'builder' | 'presets';

@Component({
    selector: 'app-flows-filter-sidebar',
    imports: [
        AppSvgIconComponent,
        AuditConditionFilterComponent,
        FlowsFilterGroupComponent,
        FlowsCheckboxEnumComponent,
        FlowsFilterPresetsComponent,
        MatTooltip,
    ],
    providers: [FlowFilterPresetsStorageService],
    templateUrl: './flows-filter-sidebar.component.html',
    styleUrl: './flows-filter-sidebar.component.scss',
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowsFilterSidebarComponent implements OnInit {
    private readonly flowsStorage = inject(FlowsStorageService);
    private readonly labelsStorage = inject(LabelsStorageService);
    private readonly presetsStorage = inject(FlowFilterPresetsStorageService);

    public readonly closeSidebar = output<void>();

    protected readonly labelsExpanded = signal(false);
    protected readonly customExpanded = signal(false);

    protected readonly activeTab = signal<FlowsFilterTab>('builder');
    protected readonly isPresetsTab = computed(() => this.activeTab() === 'presets');
    protected readonly presetsCount = computed(() => this.presetsStorage.presets().length);
    protected readonly isCreatingPreset = signal(false);

    /** Buffered filter state — changes here do NOT affect the list until applyFilters() is called. */
    protected readonly pending = signal<SidebarFilterState>(snapshotSidebarFilter(EMPTY_FLOWS_FILTER));

    protected readonly labels = computed(() => this.labelsStorage.labels());

    protected readonly customKeyOptions = CUSTOM_KEY_OPTIONS;
    protected readonly customOperators: AuditFilterOp[] = [...DEEP_TEXT_OPERATORS, 'is_empty', 'is_not_empty'];

    protected readonly labelOptions = computed<FlowsEnumOption[]>(() =>
        this.labels().map((label: LabelDto) => ({ value: String(label.id), label: label.name }))
    );

    protected readonly labelsValue = computed(() => {
        const ids = this.pending().includedLabelIds;
        if (ids === null) return [];
        return ids.map(String);
    });

    protected readonly labelsSummary = computed(() => {
        const ids = this.pending().includedLabelIds;
        if (ids === null || ids.length === 0) return '';
        return `${ids.length} selected`;
    });

    protected readonly customConditionsModel = computed(() => this.pending().customConditions);

    protected readonly customSummary = computed(() => {
        const conditions = this.pending().customConditions;
        if (conditions.length === 0) return '';
        const hasValues = conditions.some((group) =>
            group.conditions.some((condition) => condition.value.trim() !== '')
        );
        return hasValues ? 'Active' : '';
    });

    public ngOnInit(): void {
        this.presetsStorage.load();
        this.pending.set(snapshotSidebarFilter(this.flowsStorage.getCurrentFilter()));
    }

    protected setActiveTab(tab: FlowsFilterTab): void {
        this.isCreatingPreset.set(false);
        this.activeTab.set(tab);
    }

    protected createPreset(): void {
        this.flowsStorage.patchFilter(this.pending());
        this.isCreatingPreset.set(true);
        this.activeTab.set('presets');
    }

    protected onLabelsChange(values: string[]): void {
        const ids = values.map(Number);
        this.patchPending({ includedLabelIds: ids.length === 0 ? null : ids });
    }

    protected clearLabels(): void {
        this.patchPending({ includedLabelIds: null });
    }

    protected onConditionsChange(groups: AuditConditionGroup[]): void {
        this.patchPending({ customConditions: groups });
    }

    protected clearCustom(): void {
        this.patchPending({ customConditions: [createAuditConditionGroup()] });
    }

    protected clearAllFilters(): void {
        const cleared = snapshotSidebarFilter(EMPTY_FLOWS_FILTER);
        this.pending.set(cleared);
        this.flowsStorage.patchFilter(cleared);
        this.closeSidebar.emit();
    }

    protected applyFilters(): void {
        this.flowsStorage.patchFilter(this.pending());
        this.closeSidebar.emit();
    }

    protected cancel(): void {
        this.closeSidebar.emit();
    }

    private patchPending(patch: Partial<SidebarFilterState>): void {
        this.pending.update((current) => ({ ...current, ...patch }));
    }
}
