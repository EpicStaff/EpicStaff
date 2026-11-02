import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    inject,
    input,
    OnInit,
    output,
    signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AppSvgIconComponent } from '@shared/components';
import { LabelDto } from '@shared/models';
import { forkJoin } from 'rxjs';

import { AuditConditionFilterComponent } from '../../../../../audit/components/audit-condition-filter/audit-condition-filter.component';
import {
    AuditConditionGroup,
    AuditFilterOp,
    createAuditConditionGroup,
} from '../../../../../audit/models/audit-filter.models';
import { DEEP_TEXT_OPERATORS } from '../../../../../audit/models/audit-filter-options';
import { EMPTY_TOOLS_FILTER, ToolsFilterState, UsageBucket } from '../../../../models/tool-filter.model';
import { ToolFilterPresetsStorageService } from '../../../../services/tool-filter-presets-storage.service';
import { ToolsLabelsStorageService } from '../../../../services/tools-labels-storage.service';
import { ToolsSourceService } from '../../../../services/tools-source.service';
import { ToolsViewStorageService } from '../../../../services/tools-view-storage.service';
import { ToolsCheckboxEnumComponent, ToolsEnumOption } from '../tools-checkbox-enum/tools-checkbox-enum.component';
import { ToolsFilterGroupComponent } from '../tools-filter-group/tools-filter-group.component';
import { ToolsFilterPresetsComponent } from '../tools-filter-presets/tools-filter-presets.component';

interface ToolEntry {
    id: number;
    name: string;
}

const STATUS_OPTIONS: ToolsEnumOption[] = [
    { value: 'favorite', label: 'Favorite', icon: 'star-filled' },
    { value: 'not_favorite', label: 'Not Favorite', icon: 'star' },
];

const SOURCE_OPTIONS: ToolsEnumOption[] = [
    { value: 'built_in', label: 'Built In' },
    { value: 'custom', label: 'Custom' },
];

const USAGE_OPTIONS: ToolsEnumOption[] = [
    { value: 'agent_surface', label: 'Used as Agent Tools' },
    { value: 'shared_surface', label: 'Used as Shared Tools' },
    { value: 'inline_surface', label: 'Used locally in Flows' },
    { value: 'unused', label: 'Not Used' },
];

const CUSTOM_KEY_OPTIONS: { value: string; label: string }[] = [
    { value: 'name', label: 'Name' },
    { value: 'description', label: 'Description' },
    { value: 'label', label: 'Label' },
];

/** Keys from ToolsFilterState that the sidebar controls (excludes sortOrder). */
type SidebarFilterKeys =
    | 'showFavoriteOnly'
    | 'showNotFavoriteOnly'
    | 'sourceBuiltIn'
    | 'sourceCustom'
    | 'usageBuckets'
    | 'unusedOnly'
    | 'includedToolIds'
    | 'includedLabelIds'
    | 'customConditions';

type SidebarFilterState = Pick<ToolsFilterState, SidebarFilterKeys>;

function snapshotSidebarFilter(filter: ToolsFilterState): SidebarFilterState {
    return {
        showFavoriteOnly: filter.showFavoriteOnly,
        showNotFavoriteOnly: filter.showNotFavoriteOnly,
        sourceBuiltIn: filter.sourceBuiltIn,
        sourceCustom: filter.sourceCustom,
        usageBuckets: [...filter.usageBuckets],
        unusedOnly: filter.unusedOnly,
        includedToolIds: filter.includedToolIds ? [...filter.includedToolIds] : null,
        includedLabelIds: filter.includedLabelIds ? [...filter.includedLabelIds] : null,
        customConditions: filter.customConditions.map((group) => ({
            ...group,
            conditions: group.conditions.map((c) => ({ ...c })),
        })),
    };
}

type ToolsFilterTab = 'builder' | 'presets';

@Component({
    selector: 'app-tools-filter-sidebar',
    imports: [
        AppSvgIconComponent,
        AuditConditionFilterComponent,
        ToolsFilterGroupComponent,
        ToolsCheckboxEnumComponent,
        ToolsFilterPresetsComponent,
    ],
    providers: [ToolFilterPresetsStorageService],
    templateUrl: './tools-filter-sidebar.component.html',
    styleUrl: './tools-filter-sidebar.component.scss',
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ToolsFilterSidebarComponent implements OnInit {
    private readonly viewState = inject(ToolsViewStorageService);
    private readonly labelsStorage = inject(ToolsLabelsStorageService);
    private readonly toolsSource = inject(ToolsSourceService);
    private readonly presetsStorage = inject(ToolFilterPresetsStorageService);
    private readonly destroyRef = inject(DestroyRef);

    public readonly showSource = input<boolean>(false);
    public readonly closeSidebar = output<void>();

    protected readonly statusExpanded = signal(false);
    protected readonly sourceExpanded = signal(false);
    protected readonly usageExpanded = signal(false);
    protected readonly toolsExpanded = signal(false);
    protected readonly labelsExpanded = signal(false);
    protected readonly customExpanded = signal(false);

    protected readonly activeTab = signal<ToolsFilterTab>('builder');
    protected readonly isPresetsTab = computed(() => this.activeTab() === 'presets');
    protected readonly presetsCount = computed(() => this.presetsStorage.presets().length);
    protected readonly isCreatingPreset = signal(false);

    protected readonly allTools = signal<ToolEntry[]>([]);

    /** Buffered filter state — changes here do NOT affect the list until applyFilters() is called. */
    protected readonly pending = signal<SidebarFilterState>(snapshotSidebarFilter(EMPTY_TOOLS_FILTER));

    protected readonly labels = computed(() => this.labelsStorage.labels());

    protected readonly statusOptions = STATUS_OPTIONS;
    protected readonly sourceOptions = SOURCE_OPTIONS;
    protected readonly usageOptions = USAGE_OPTIONS;
    protected readonly customKeyOptions = CUSTOM_KEY_OPTIONS;
    protected readonly customOperators: AuditFilterOp[] = [...DEEP_TEXT_OPERATORS, 'is_empty', 'is_not_empty'];

    protected readonly statusValue = computed(() => {
        const result: string[] = [];
        if (this.pending().showFavoriteOnly) result.push('favorite');
        if (this.pending().showNotFavoriteOnly) result.push('not_favorite');
        return result;
    });

    protected readonly statusSummary = computed(() => {
        if (this.pending().showFavoriteOnly) return 'Favorite';
        if (this.pending().showNotFavoriteOnly) return 'Not Favorite';
        return '';
    });

    protected readonly sourceValue = computed(() => {
        const result: string[] = [];
        if (this.pending().sourceBuiltIn) result.push('built_in');
        if (this.pending().sourceCustom) result.push('custom');
        return result;
    });

    protected readonly sourceSummary = computed(() => {
        if (this.pending().sourceBuiltIn) return 'Built In';
        if (this.pending().sourceCustom) return 'Custom';
        return '';
    });

    protected readonly usageValue = computed(() => {
        const result: string[] = [...this.pending().usageBuckets];
        if (this.pending().unusedOnly) result.push('unused');
        return result;
    });

    protected readonly usageSummary = computed(() => {
        const parts: string[] = [];
        for (const bucket of this.pending().usageBuckets) {
            const option = USAGE_OPTIONS.find((opt) => opt.value === bucket);
            if (option) parts.push(option.label);
        }
        if (this.pending().unusedOnly) parts.push('Not Used');
        return parts.join(', ');
    });

    protected readonly toolOptions = computed<ToolsEnumOption[]>(() =>
        this.allTools().map((tool) => ({ value: String(tool.id), label: tool.name }))
    );

    protected readonly toolsValue = computed(() => {
        const ids = this.pending().includedToolIds;
        if (ids === null) return [];
        return ids.map(String);
    });

    protected readonly toolsSummary = computed(() => {
        const ids = this.pending().includedToolIds;
        if (ids === null || ids.length === 0) return '';
        return `${ids.length} selected`;
    });

    protected readonly labelOptions = computed<ToolsEnumOption[]>(() =>
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
        this.loadAllTools();
        this.presetsStorage.load();
        this.pending.set(snapshotSidebarFilter(this.viewState.filter()));
    }

    protected setActiveTab(tab: ToolsFilterTab): void {
        this.isCreatingPreset.set(false);
        this.activeTab.set(tab);
    }

    protected createPreset(): void {
        this.viewState.patchFilter(this.pending());
        this.isCreatingPreset.set(true);
        this.activeTab.set('presets');
    }

    protected onStatusChange(values: string[]): void {
        const wasFavorite = this.pending().showFavoriteOnly;
        const isFavorite = values.includes('favorite');
        const isNotFavorite = values.includes('not_favorite');

        if (isFavorite && !wasFavorite) {
            this.patchPending({
                showFavoriteOnly: true,
                showNotFavoriteOnly: false,
            });
        } else if (isNotFavorite && !this.pending().showNotFavoriteOnly) {
            this.patchPending({
                showFavoriteOnly: false,
                showNotFavoriteOnly: true,
            });
        } else {
            this.patchPending({
                showFavoriteOnly: isFavorite,
                showNotFavoriteOnly: isNotFavorite,
            });
        }
    }

    protected clearStatus(): void {
        this.patchPending({ showFavoriteOnly: false, showNotFavoriteOnly: false });
    }

    protected onSourceChange(values: string[]): void {
        const wasBuilt = this.pending().sourceBuiltIn;
        const isBuilt = values.includes('built_in');
        const isNotBuilt = values.includes('custom');

        if (isBuilt && !wasBuilt) {
            this.patchPending({
                sourceBuiltIn: true,
                sourceCustom: false,
            });
        } else if (isNotBuilt && !this.pending().sourceCustom) {
            this.patchPending({
                sourceBuiltIn: false,
                sourceCustom: true,
            });
        } else {
            this.patchPending({
                sourceBuiltIn: isBuilt,
                sourceCustom: isNotBuilt,
            });
        }
    }

    protected clearSource(): void {
        this.patchPending({ sourceBuiltIn: false, sourceCustom: false });
    }

    protected onUsageChange(values: string[]): void {
        const wasUnused = this.pending().unusedOnly;
        const nowUnused = values.includes('unused');
        const buckets = values.filter((value): value is UsageBucket => value !== 'unused');

        if (nowUnused && !wasUnused) {
            this.patchPending({ usageBuckets: [], unusedOnly: true });
        } else if (buckets.length > 0 && wasUnused) {
            this.patchPending({ usageBuckets: buckets, unusedOnly: false });
        } else {
            this.patchPending({ usageBuckets: buckets, unusedOnly: nowUnused });
        }
    }

    protected clearUsage(): void {
        this.patchPending({ usageBuckets: [], unusedOnly: false });
    }

    protected onToolsChange(values: string[]): void {
        const ids = values.map(Number);
        this.patchPending({ includedToolIds: ids.length === 0 ? null : ids });
    }

    protected clearTools(): void {
        this.patchPending({ includedToolIds: null });
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
        const cleared = snapshotSidebarFilter(EMPTY_TOOLS_FILTER);
        this.pending.set(cleared);
        this.viewState.patchFilter(cleared);
        this.closeSidebar.emit();
    }

    protected applyFilters(): void {
        this.viewState.patchFilter(this.pending());
        this.closeSidebar.emit();
    }

    protected cancel(): void {
        this.closeSidebar.emit();
    }

    private patchPending(patch: Partial<SidebarFilterState>): void {
        this.pending.update((current) => ({ ...current, ...patch }));
    }

    private loadAllTools(): void {
        forkJoin({
            custom: this.toolsSource.getPythonCodeTools(),
            mcp: this.toolsSource.getMcpTools(),
        })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(({ custom, mcp }) => {
                const entries: ToolEntry[] = [
                    ...custom.map((tool) => ({ id: tool.id, name: tool.name })),
                    ...mcp.map((tool) => ({ id: tool.id, name: tool.name })),
                ];
                entries.sort((a, b) => a.name.localeCompare(b.name));
                this.allTools.set(entries);
            });
    }
}
