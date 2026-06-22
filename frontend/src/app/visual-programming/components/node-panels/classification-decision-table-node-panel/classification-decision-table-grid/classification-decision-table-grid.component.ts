import { Overlay, OverlayRef } from '@angular/cdk/overlay';
import { TemplatePortal } from '@angular/cdk/portal';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    computed,
    effect,
    ElementRef,
    inject,
    input,
    OnDestroy,
    output,
    Renderer2,
    signal,
    TemplateRef,
    untracked,
    ViewChild,
    ViewContainerRef,
} from '@angular/core';
import { AgGridModule } from 'ag-grid-angular';
import {
    BodyScrollEvent,
    CellClickedEvent,
    CellValueChangedEvent,
    ColDef,
    ColGroupDef,
    ColumnMovedEvent,
    ColumnResizedEvent,
    EditableCallbackParams,
    GridApi,
    GridOptions,
    GridReadyEvent,
    IRowNode,
    RowSpanParams,
    ValueGetterParams,
    ValueSetterParams,
} from 'ag-grid-community';
import { AllCommunityModule, ModuleRegistry } from 'ag-grid-community';
import { themeQuartz } from 'ag-grid-community';

import { AppSvgIconComponent } from '../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { ButtonComponent } from '../../../../../shared/components/buttons/button/button.component';
import { ConfirmationDialogService } from '../../../../../shared/components/cofirm-dialog/confimation-dialog.service';
import { HelpTooltipComponent } from '../../../../../shared/components/help-tooltip/help-tooltip.component';
import { MultiSelectComponent } from '../../../../../shared/components/multi-select/multi-select.component';
import { SelectItem } from '../../../../../shared/components/select/select.component';
import { PromptConfig } from '../../../../core/models/classification-decision-table.model';
import { ConditionGroup } from '../../../../core/models/decision-table.model';
import {
    composeExpression,
    composeManipulation,
    normalizeExpressionSpacing,
    normalizeOpPart,
    parseExpression,
    parseManipulation,
    toDisplayExpression,
} from '../../../../utils/condition-expression.helper';
import {
    CDT_COLUMN_KIND,
    CDT_FIELD_PREFIX,
    CDT_GRID_ROW_HEIGHT,
    CDT_MANIP_PREFIX,
    CDT_OVERLAY_ROW_HEIGHT,
} from '../cdt.constants';
import { ColumnHeaderMenuComponent } from './column-header-menu/column-header-menu.component';
import { EnableFilterHeaderComponent, EnableFilterMode } from './enable-filter-header/enable-filter-header.component';
import { ExpressionBuilderCellEditorComponent } from './expression-builder/expression-builder-cell-editor.component';
import { IconHeaderComponent } from './icon-header/icon-header.component';
import { MonacoCellRendererComponent } from './monaco-cell-renderer/monaco-cell-renderer.component';
import { ParamsGroupHeaderComponent } from './params-group-header/params-group-header.component';
import { PromptIdCellEditorComponent } from './prompt-id-cell-editor/prompt-id-cell-editor.component';
import { PromptTooltipRendererComponent } from './prompt-tooltip-renderer/prompt-tooltip-renderer.component';
import { SelectionCellRendererComponent } from './selection-cell-renderer/selection-cell-renderer.component';
import { SelectionCountHeaderComponent } from './selection-count-header/selection-count-header.component';

ModuleRegistry.registerModules([AllCommunityModule]);

@Component({
    selector: 'app-classification-decision-table-grid',
    imports: [AgGridModule, AppSvgIconComponent, ButtonComponent, HelpTooltipComponent, MultiSelectComponent],
    templateUrl: './classification-decision-table-grid.component.html',
    styleUrls: ['./classification-decision-table-grid.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ClassificationDecisionTableGridComponent implements OnDestroy {
    public conditionGroups = input.required<ConditionGroup[]>();
    public activeColor = input<string>('#685fff');
    public currentNodeId = input.required<string>();
    public storageNodeId = input<string>('');
    public prompts = input<Record<string, PromptConfig>>({});
    public defaultLlmId = input<number | null>(null);
    public llmConfigs = input<{ id: number; label: string }[]>([]);
    public preInputMapKeys = input<string[]>([]);
    public domainKeys = input<string[]>([]);

    public conditionGroupsChange = output<ConditionGroup[]>();
    public promptChange = output<{
        promptId: string;
        field: keyof PromptConfig;
        value: PromptConfig[keyof PromptConfig];
    }>();
    public promptAdd = output<{ id: string; config: PromptConfig }>();
    public openPromptLibrary = output<{ action: 'create' } | { action: 'edit'; promptId: string }>();

    private cdr = inject(ChangeDetectorRef);
    private elRef = inject(ElementRef);
    private renderer = inject(Renderer2);
    private overlay = inject(Overlay);
    private vcr = inject(ViewContainerRef);
    private confirmDialog = inject(ConfirmationDialogService);

    private gridApi!: GridApi;
    private outsideClickUnlisten: (() => void) | null = null;
    private fieldColumnsInitialized = false;
    public rowData = signal<ConditionGroup[]>([]);
    public contextMenu = signal<{ x: number; y: number; rowIndex: number } | null>(null);
    public dropIndicatorTop = signal<number | null>(null);

    // Ordered list of ALL movable colIds (field_* and expression)
    private movableColumnOrder = signal<string[]>([CDT_COLUMN_KIND.EXPRESSION]);

    // Manipulation field columns (manip_* and manipulation)
    private manipColumnOrder = signal<string[]>([CDT_COLUMN_KIND.MANIPULATION]);

    // Frozen column IDs (pinned left)
    public frozenColIds = signal<Set<string>>(new Set());
    public freezeAnchorColId = signal<string | null>(null);

    // User-hidden column IDs
    public hiddenColIds = signal<Set<string>>(new Set());

    public hiddenColumnGroups = signal<Map<string, { label: string; colIds: string[] }>>(new Map());

    // Hidden-column restore badges: position computed from DOM
    public hiddenColumnBadges = signal<Array<{ colId: string; x: number; y: number; label: string }>>([]);

    // Selection state for toolbar buttons
    public selectedRowCount = signal<number>(0);
    private selectedRowsAllUngrouped = signal<boolean>(true);
    public canGroupSelected = computed<boolean>(() => this.selectedRowCount() >= 1 && this.selectedRowsAllUngrouped());

    // Row group collapse state
    public collapsedGroups = signal<Set<string>>(new Set());

    public groupOverlayItems = signal<
        Array<{
            sectionId: string;
            top: number;
            height: number;
            isCollapsed: boolean;
        }>
    >([]);

    // Enable/disable filter mode (default: show only enabled rows)
    public enableFilterMode = signal<EnableFilterMode>('enabled');

    // Precomputed set of group_name keys that should remain visible given collapse + enable filter state
    public visibleRowKeys = signal<Set<string>>(new Set<string>());

    public displayedRowData = computed<ConditionGroup[]>(() => {
        const rows = this.rowData();
        const collapsed = this.collapsedGroups();
        const mode = this.enableFilterMode();
        return rows.filter((row) => {
            const section = row.section ?? null;
            if (section && collapsed.has(section)) return false;
            if (mode === 'enabled' && row.dock_visible !== true) return false;
            if (mode === 'disabled' && row.dock_visible === true) return false;
            return true;
        });
    });

    private autoCollapseGroupsOnFirstLoad(): void {
        if (this.autoCollapsedOnLoad) return;
        const rows = this.rowData();
        if (!rows || rows.length === 0) return;
        if (!this.gridApi) return;

        const sectionsInData = new Set<string>();
        for (const row of rows) {
            const section = (row as ConditionGroup).section;
            if (section) sectionsInData.add(section);
        }
        this.autoCollapsedOnLoad = true;
        if (sectionsInData.size === 0) return;

        const merged = new Set(this.collapsedGroups());
        sectionsInData.forEach((id) => merged.add(id));
        this.collapsedGroups.set(merged);

        queueMicrotask(() => this.recomputeGroupOverlays());
    }

    public recomputeGroupOverlays(): void {
        const api = this.gridApi;
        if (!api) {
            this.groupOverlayItems.set([]);
            return;
        }
        const wrapperEl = this.elRef.nativeElement.querySelector('.grid-wrapper') as HTMLElement | null;
        const bodyEl = this.elRef.nativeElement.querySelector('.ag-body-viewport') as HTMLElement | null;
        if (!wrapperEl || !bodyEl) {
            this.groupOverlayItems.set([]);
            return;
        }

        const wrapperRect = wrapperEl.getBoundingClientRect();
        const bodyRect = bodyEl.getBoundingClientRect();
        const bodyOffsetY = bodyRect.top - wrapperRect.top;
        const scrollTop = bodyEl.scrollTop;
        const collapsed = this.collapsedGroups();

        const rawRows = this.rowData() ?? [];
        const sectionRange = new Map<string, { firstIdx: number; lastIdx: number }>();
        rawRows.forEach((row, idx) => {
            const section = (row as { section?: string | null }).section;
            if (!section) return;
            const existing = sectionRange.get(section);
            if (existing) {
                existing.firstIdx = Math.min(existing.firstIdx, idx);
                existing.lastIdx = Math.max(existing.lastIdx, idx);
            } else {
                sectionRange.set(section, { firstIdx: idx, lastIdx: idx });
            }
        });

        const isRowVisible = (row: ConditionGroup): boolean => {
            const section = row.section ?? null;
            if (section && collapsed.has(section)) return false;
            const mode = this.enableFilterMode();
            if (mode === 'enabled' && row.dock_visible !== true) return false;
            if (mode === 'disabled' && row.dock_visible === true) return false;
            return true;
        };

        const passesEnableFilter = (row: ConditionGroup): boolean => {
            const mode = this.enableFilterMode();
            if (mode === 'enabled' && row.dock_visible !== true) return false;
            if (mode === 'disabled' && row.dock_visible === true) return false;
            return true;
        };

        const items: Array<{ sectionId: string; top: number; height: number; isCollapsed: boolean }> = [];
        const expandedFirstLast = new Map<string, { firstTop: number; lastBottom: number }>();

        api.forEachNodeAfterFilterAndSort((node) => {
            if (node.rowTop == null) return;
            const data = node.data as { section?: string | null } | undefined;
            const section = data?.section ?? null;
            const top = node.rowTop;
            const bottom = top + (node.rowHeight ?? CDT_OVERLAY_ROW_HEIGHT);
            if (!section) return;
            const existing = expandedFirstLast.get(section);
            if (existing) {
                existing.firstTop = Math.min(existing.firstTop, top);
                existing.lastBottom = Math.max(existing.lastBottom, bottom);
            } else {
                expandedFirstLast.set(section, { firstTop: top, lastBottom: bottom });
            }
        });

        const rowHeight = CDT_OVERLAY_ROW_HEIGHT;

        sectionRange.forEach((range, sectionId) => {
            let filteredMembers = 0;
            for (let i = range.firstIdx; i <= range.lastIdx; i++) {
                if (passesEnableFilter(rawRows[i] as ConditionGroup)) filteredMembers++;
            }
            if (filteredMembers === 0) return;

            if (collapsed.has(sectionId)) {
                let visibleBefore = 0;
                for (let i = 0; i < range.firstIdx; i++) {
                    if (isRowVisible(rawRows[i] as ConditionGroup)) visibleBefore++;
                }
                const anchorY = visibleBefore * rowHeight;
                items.push({
                    sectionId,
                    top: bodyOffsetY + anchorY - scrollTop,
                    height: 22,
                    isCollapsed: true,
                });
            } else {
                const positions = expandedFirstLast.get(sectionId);
                if (!positions) {
                    let visibleBefore = 0;
                    for (let i = 0; i < range.firstIdx; i++) {
                        if (isRowVisible(rawRows[i] as ConditionGroup)) visibleBefore++;
                    }
                    items.push({
                        sectionId,
                        top: bodyOffsetY + visibleBefore * rowHeight - scrollTop,
                        height: (range.lastIdx - range.firstIdx + 1) * rowHeight,
                        isCollapsed: false,
                    });
                    return;
                }
                items.push({
                    sectionId,
                    top: bodyOffsetY + positions.firstTop - scrollTop,
                    height: positions.lastBottom - positions.firstTop,
                    isCollapsed: false,
                });
            }
        });

        this.groupOverlayItems.set(items);
    }

    public openGroupMenuFromOverlay(sectionId: string, event: MouseEvent): void {
        this.openGroupMenu(sectionId, event.currentTarget as HTMLElement);
    }

    private groupMenuOverlayRef: OverlayRef | null = null;
    public groupMenuSectionId = signal<string | null>(null);

    public isCurrentGroupCollapsed = computed<boolean>(() => {
        const id = this.groupMenuSectionId();
        return id !== null && this.collapsedGroups().has(id);
    });

    // Computed: field names in their column order
    public activeFieldColumns = computed(() =>
        this.movableColumnOrder()
            .filter((id) => id.startsWith(CDT_FIELD_PREFIX))
            .map((id) => id.substring(CDT_FIELD_PREFIX.length))
    );

    public isEmpty = computed(() => this.displayedRowData().length === 0);

    // Manipulation field computed properties
    public activeManipFieldColumns = computed(() =>
        this.manipColumnOrder()
            .filter((id) => id.startsWith(CDT_MANIP_PREFIX))
            .map((id) => id.substring(CDT_MANIP_PREFIX.length))
    );

    public hasFieldCols = computed(() => this.movableColumnOrder().some((id) => id.startsWith(CDT_FIELD_PREFIX)));

    public hasManipCols = computed(() => this.manipColumnOrder().some((id) => id.startsWith(CDT_MANIP_PREFIX)));

    /** True when at least one above-grid "+" button is visible (i.e. at least one params group is absent). */
    public hasAboveAddButtons = computed(() => !this.hasFieldCols() || !this.hasManipCols());

    // ── Multi-select items for the field pickers ──

    /** Items for the expression-side field picker, grouped by Domain then Input Map.
     *  Deduplication: Domain takes precedence over Input Map. */
    public exprMultiSelectItems = computed<SelectItem[]>(() => {
        const domainKeys = this.domainKeys();
        const domainSet = new Set(domainKeys);
        const seen = new Set<string>();
        const items: SelectItem[] = [];

        // Domain first
        for (const k of domainKeys) {
            if (!seen.has(k)) {
                seen.add(k);
                items.push({ name: k, value: k, group: 'Domain' });
            }
        }

        // Input Map (exclude keys already classified as Domain)
        for (const k of this.preInputMapKeys()) {
            if (!seen.has(k) && !domainSet.has(k)) {
                seen.add(k);
                items.push({ name: k, value: k, group: 'Input Map' });
            }
        }

        return items;
    });

    /** Items for the manipulation-side field picker. Domain only. */
    public manipMultiSelectItems = computed<SelectItem[]>(() => {
        const seen = new Set<string>();
        const items: SelectItem[] = [];

        for (const k of this.domainKeys()) {
            if (!seen.has(k)) {
                seen.add(k);
                items.push({ name: k, value: k, group: 'Domain' });
            }
        }

        return items;
    });

    // Pre-open model value signals for the multi-selects
    public exprSelectedFieldsModel = signal<unknown[]>([]);
    public manipSelectedFieldsModel = signal<unknown[]>([]);

    @ViewChild('exprMultiSelect') exprMultiSelect!: MultiSelectComponent;
    @ViewChild('manipMultiSelect') manipMultiSelect!: MultiSelectComponent;
    @ViewChild('groupMenuTemplate') groupMenuTemplate!: TemplateRef<unknown>;

    public exprAddPos = signal<{ x: number; y: number } | null>(null);
    public manipAddPos = signal<{ x: number; y: number } | null>(null);
    private positionResizeObserver: ResizeObserver | null = null;

    constructor() {
        effect(() => {
            const groups = this.conditionGroups();
            if (groups && groups.length > 0) {
                untracked(() => {
                    this.rowData.set([...groups]);
                    if (!this.fieldColumnsInitialized) {
                        this.initFieldColumnsFromData(groups);
                        this.fieldColumnsInitialized = true;
                    }
                });
            }
        });
        effect(() => {
            this.prompts();
            untracked(() => {
                if (this.gridApi) {
                    this.gridApi.refreshCells({ columns: ['prompt_id'], force: true });
                }
            });
        });
        effect(() => {
            this.movableColumnOrder();
            this.manipColumnOrder();
            untracked(() => {
                this.rebuildColumnDefs();
                this.syncRowsFromExpression();
                this.syncRowsFromManipulation();
            });
        });
        effect(() => {
            this.hasFieldCols();
            this.hasManipCols();
            untracked(() => {
                setTimeout(() => this.updateAddButtonPositions(), 0);
            });
        });
        effect(() => {
            const rows = this.rowData();
            if (rows.length > 0 && !this.autoCollapsedOnLoad) {
                this.autoCollapseGroupsOnFirstLoad();
            }
        });
    }

    private initFieldColumnsFromData(groups: ConditionGroup[]): void {
        // Restore saved state first
        this.restoreGridState();

        const fieldKeys = new Set<string>();
        const manipKeys = new Set<string>();
        groups.forEach((g) => {
            if (g.field_expressions) {
                Object.keys(g.field_expressions).forEach((k) => fieldKeys.add(k));
            }
            if (g.field_manipulations) {
                Object.keys(g.field_manipulations).forEach((k) => manipKeys.add(k));
            }
        });
        if (fieldKeys.size > 0 && this.movableColumnOrder().length <= 1) {
            const colIds = [CDT_COLUMN_KIND.EXPRESSION, ...[...fieldKeys].map((f) => `${CDT_FIELD_PREFIX}${f}`)];
            this.movableColumnOrder.set(colIds);
        }
        if (manipKeys.size > 0 && this.manipColumnOrder().length <= 1) {
            const colIds = [CDT_COLUMN_KIND.MANIPULATION, ...[...manipKeys].map((f) => `${CDT_MANIP_PREFIX}${f}`)];
            this.manipColumnOrder.set(colIds);
        }
        this.recomputeGroupOverlays();
    }

    public myTheme = themeQuartz.withParams({
        backgroundColor: '#1e1e1e',
        foregroundColor: '#d4d4d4',
        headerBackgroundColor: '#27272b',
        headerTextColor: '#ffffff',
        oddRowBackgroundColor: '#252526',
        borderColor: 'rgba(255, 255, 255, 0.1)',
        rowHoverColor: 'rgba(104, 95, 255, 0.1)',
        columnBorder: { style: 'solid', width: 1, color: 'rgba(255, 255, 255, 0.07)' },
        fontSize: 14,
    });

    public defaultColDef: ColDef = {
        sortable: false,
        resizable: true,
        minWidth: 30,
    };

    private savedColumnWidths = new Map<string, number>();
    private saveTimeout: ReturnType<typeof setTimeout> | null = null;
    private isRebuilding = false;
    /** Guard flag to prevent recursive cellValueChanged loops during programmatic cell writes. */
    private isSyncing = false;
    private autoCollapsedOnLoad = false;

    private get storageKey(): string {
        const stableId = this.storageNodeId() || this.currentNodeId();
        return `cdt-grid-state-${stableId}`;
    }

    private saveGridState(): void {
        if (this.saveTimeout) clearTimeout(this.saveTimeout);
        this.saveTimeout = setTimeout(() => {
            const widths: Record<string, number> = {};
            this.gridApi?.getColumnState()?.forEach((s) => {
                if (s.colId && s.width) widths[s.colId] = s.width;
            });
            const state = {
                widths,
                order: this.movableColumnOrder(),
                manipOrder: this.manipColumnOrder(),
                pinned: [...this.frozenColIds()],
                hiddenColIds: [...this.hiddenColIds()],
                freezeAnchor: this.freezeAnchorColId(),
                collapsedGroups: [...this.collapsedGroups()],
                enableFilterMode: this.enableFilterMode(),
            };
            try {
                localStorage.setItem(this.storageKey, JSON.stringify(state));
            } catch {}
        }, 300);
    }

    private restoreGridState(): void {
        try {
            const raw = localStorage.getItem(this.storageKey);
            if (!raw) return;
            const state = JSON.parse(raw);
            if (state.widths) {
                Object.entries(state.widths).forEach(([k, v]) => this.savedColumnWidths.set(k, v as number));
            }
            if (state.order?.length > 0) {
                this.movableColumnOrder.set(state.order);
            }
            if (state.manipOrder?.length > 0) {
                this.manipColumnOrder.set(state.manipOrder);
            }
            if (Array.isArray(state.pinned) && state.pinned.length > 0) {
                this.frozenColIds.set(new Set(state.pinned as string[]));
            }
            if (Array.isArray(state.hiddenColIds) && state.hiddenColIds.length > 0) {
                this.hiddenColIds.set(new Set(state.hiddenColIds as string[]));
            }
            if (Array.isArray(state.collapsedGroups)) {
                this.collapsedGroups.set(new Set(state.collapsedGroups as string[]));
            }
            if (
                state.enableFilterMode === 'all' ||
                state.enableFilterMode === 'enabled' ||
                state.enableFilterMode === 'disabled'
            ) {
                this.enableFilterMode.set(state.enableFilterMode);
            }
            if (typeof state.freezeAnchor === 'string') {
                this.freezeAnchorColId.set(state.freezeAnchor);
            } else if (Array.isArray(state.pinned) && state.pinned.length > 0) {
                const fullOrder = this.getFullColOrder();
                let anchor: string | null = null;
                let anchorIdx = -1;
                for (const id of state.pinned as string[]) {
                    const idx = fullOrder.indexOf(id);
                    if (idx > anchorIdx) {
                        anchor = id;
                        anchorIdx = idx;
                    }
                }
                if (anchor) this.freezeAnchorColId.set(anchor);
            }
        } catch {}
    }

    public gridOptions: GridOptions = {
        theme: this.myTheme,
        rowHeight: CDT_GRID_ROW_HEIGHT,
        headerHeight: 45,
        suppressRowTransform: true,
        suppressCellFocus: false,
        stopEditingWhenCellsLoseFocus: true,
        domLayout: 'autoHeight',
        rowDragManaged: false,
        animateRows: true,
        suppressColumnMoveAnimation: true,
        rowSelection: {
            mode: 'multiRow',
            checkboxes: false,
            headerCheckbox: false,
            enableClickSelection: false,
        },
        context: {
            onManualRowReorder: (source: IRowNode, over: IRowNode) => this.handleManualRowReorder(source, over),
        },
        preventDefaultOnContextMenu: true,
        onCellContextMenu: (event) => {
            const mouseEvent = event.event as MouseEvent;
            this.contextMenu.set({
                x: mouseEvent.clientX,
                y: mouseEvent.clientY,
                rowIndex: event.node.rowIndex!,
            });
            this.cdr.markForCheck();
        },
        onFirstDataRendered: () => {
            setTimeout(() => this.updateAddButtonPositions(), 0);
        },
        onColumnMoved: (event: ColumnMovedEvent) => {
            if (this.isRebuilding) return;
            if (!event.finished) return;
            const colState = this.gridApi?.getColumnState();
            if (!colState) return;
            const allVisible = colState.map((s) => s.colId!);

            // Update expression column order
            const exprResult = allVisible.filter(
                (id) => id?.startsWith(CDT_FIELD_PREFIX) || id === CDT_COLUMN_KIND.EXPRESSION
            );
            this.movableColumnOrder.set(exprResult);

            // Update manipulation column order
            const manipResult = allVisible.filter(
                (id) => id?.startsWith(CDT_MANIP_PREFIX) || id === CDT_COLUMN_KIND.MANIPULATION
            );
            this.manipColumnOrder.set(manipResult);
            this.saveGridState();
            setTimeout(() => this.updateAddButtonPositions(), 0);
        },
        onColumnResized: (event: ColumnResizedEvent) => {
            if (event.finished) {
                this.saveGridState();
                setTimeout(() => this.updateAddButtonPositions(), 0);
            }
        },
        onColumnVisible: () => {
            setTimeout(() => this.updateAddButtonPositions(), 0);
        },
    };

    public columnDefs: (ColDef | ColGroupDef)[] = this.buildColumnDefs();

    // ── Freeze / Hide helpers ──

    private makeMenuHeaderParams(colId: string, label: string): object {
        return {
            label,
            colId,
            onFreezeToggle: (id: string) => this.toggleFreeze(id),
            onHide: (id: string) => this.hideColumn(id),
            isPinned: () => this.freezeAnchorColId() === colId,
        };
    }

    public toggleFreeze(colId: string): void {
        const fullOrder = this.getFullColOrder();
        const targetIdx = fullOrder.indexOf(colId);
        if (targetIdx === -1) return;

        const isAnchor = this.freezeAnchorColId() === colId;

        // Determine the new frozen prefix
        let newFrozenIds: string[];
        if (isAnchor) {
            // Unfreeze: clear the entire frozen set
            newFrozenIds = [];
            this.freezeAnchorColId.set(null);
        } else {
            // Freeze: pin every column from index 0 up to and including targetIdx
            newFrozenIds = fullOrder.slice(0, targetIdx + 1);
            this.freezeAnchorColId.set(colId);
        }

        const newFrozenSet = new Set(newFrozenIds);

        // Build state updates: set pinned:'left' for new frozen set, null for previously frozen cols no longer in set
        const stateUpdates: { colId: string; pinned: 'left' | null }[] = [];
        const previouslyFrozen = this.frozenColIds();
        for (const id of fullOrder) {
            const shouldBeFrozen = newFrozenSet.has(id);
            const wasPinned = previouslyFrozen.has(id);
            if (shouldBeFrozen && !wasPinned) {
                stateUpdates.push({ colId: id, pinned: 'left' });
            } else if (!shouldBeFrozen && wasPinned) {
                stateUpdates.push({ colId: id, pinned: null });
            }
        }

        this.frozenColIds.set(newFrozenSet);
        if (stateUpdates.length > 0) {
            this.gridApi?.applyColumnState({ state: stateUpdates });
        }
        this.gridApi?.refreshHeader();
        this.saveGridState();
        this.cdr.markForCheck();
    }

    public hideColumn(colId: string): void {
        const current = new Set(this.hiddenColIds());
        current.add(colId);
        this.hiddenColIds.set(current);
        this.gridApi?.applyColumnState({
            state: [{ colId, hide: true }],
        });
        this.saveGridState();
        setTimeout(() => this.updateAddButtonPositions(), 50);
        this.cdr.markForCheck();
    }

    public unhideColumn(colId: string): void {
        const groups = this.hiddenColumnGroups();
        if (groups.has(colId)) {
            const info = groups.get(colId)!;
            const currentCols = new Set(this.hiddenColIds());
            info.colIds.forEach((id) => currentCols.delete(id));
            this.hiddenColIds.set(currentCols);

            const nextGroups = new Map(groups);
            nextGroups.delete(colId);
            this.hiddenColumnGroups.set(nextGroups);

            this.gridApi?.applyColumnState({
                state: info.colIds.map((id) => ({ colId: id, hide: false })),
            });
            this.saveGridState();
            setTimeout(() => this.updateAddButtonPositions(), 50);
            this.cdr.markForCheck();
            return;
        }
        const current = new Set(this.hiddenColIds());
        current.delete(colId);
        this.hiddenColIds.set(current);
        this.gridApi?.applyColumnState({
            state: [{ colId, hide: false }],
        });
        this.saveGridState();
        setTimeout(() => this.updateAddButtonPositions(), 50);
        this.cdr.markForCheck();
    }

    /** Freeze all columns from index 0 through the last colId in childColIds. */
    public freezeThroughLastChild(childColIds: string[]): void {
        if (childColIds.length === 0) return;
        const fullOrder = this.getFullColOrder();
        const lastChild = childColIds[childColIds.length - 1];
        const targetIdx = fullOrder.indexOf(lastChild);
        if (targetIdx === -1) return;

        const newFrozenIds = fullOrder.slice(0, targetIdx + 1);
        const newFrozenSet = new Set(newFrozenIds);
        const previouslyFrozen = this.frozenColIds();

        const stateUpdates: { colId: string; pinned: 'left' | null }[] = [];
        for (const id of fullOrder) {
            const shouldBeFrozen = newFrozenSet.has(id);
            const wasPinned = previouslyFrozen.has(id);
            if (shouldBeFrozen && !wasPinned) {
                stateUpdates.push({ colId: id, pinned: 'left' });
            } else if (!shouldBeFrozen && wasPinned) {
                stateUpdates.push({ colId: id, pinned: null });
            }
        }

        this.frozenColIds.set(newFrozenSet);
        this.freezeAnchorColId.set(lastChild);
        if (stateUpdates.length > 0) {
            this.gridApi?.applyColumnState({ state: stateUpdates });
        }
        this.gridApi?.refreshHeader();
        this.saveGridState();
        this.cdr.markForCheck();
    }

    /** Hide all columns in the given colIds in a single batched applyColumnState call. */
    public hideColumns(colIds: string[]): void {
        if (colIds.length === 0) return;
        const current = new Set(this.hiddenColIds());
        colIds.forEach((id) => current.add(id));
        this.hiddenColIds.set(current);
        this.gridApi?.applyColumnState({
            state: colIds.map((colId) => ({ colId, hide: true })),
        });
        this.saveGridState();
        setTimeout(() => this.updateAddButtonPositions(), 50);
        this.cdr.markForCheck();
    }

    public hideColumnGroup(groupId: string, label: string, colIds: string[]): void {
        if (colIds.length === 0) return;
        const currentCols = new Set(this.hiddenColIds());
        colIds.forEach((id) => currentCols.add(id));
        this.hiddenColIds.set(currentCols);

        const currentGroups = new Map(this.hiddenColumnGroups());
        currentGroups.set(groupId, { label, colIds: [...colIds] });
        this.hiddenColumnGroups.set(currentGroups);

        this.gridApi?.applyColumnState({
            state: colIds.map((colId) => ({ colId, hide: true })),
        });
        this.saveGridState();
        setTimeout(() => this.updateAddButtonPositions(), 50);
        this.cdr.markForCheck();
    }

    // Compute the full ordered list of all colIds (excluding structural ones like 'actions')
    private getFullColOrder(): string[] {
        const order: string[] = [];
        for (const def of this.columnDefs) {
            if ('children' in def) {
                // Group — add children
                const group = def as ColGroupDef;
                for (const child of group.children as ColDef[]) {
                    if (child.colId) order.push(child.colId);
                }
            } else {
                const col = def as ColDef;
                const id = col.colId || col.field;
                if (id && id !== 'actions') order.push(id);
            }
        }
        return order;
    }

    private updateBadgePositions(): void {
        const hidden = this.hiddenColIds();
        if (hidden.size === 0) {
            this.hiddenColumnBadges.set([]);
            return;
        }

        const fullOrder = this.getFullColOrder();
        const badges: Array<{ colId: string; x: number; y: number; label: string }> = [];
        const wrapperEl = this.elRef.nativeElement.querySelector('.grid-wrapper') as HTMLElement | null;
        const containerRect = (wrapperEl ?? this.elRef.nativeElement).getBoundingClientRect();

        const headerEl = this.elRef.nativeElement.querySelector('.ag-header') as HTMLElement | null;
        const headerRect = headerEl?.getBoundingClientRect();
        const y = headerRect ? headerRect.top - containerRect.top - 24 : -24;

        const groups = this.hiddenColumnGroups();
        const groupedColIdToGroupId = new Map<string, string>();
        for (const [groupId, info] of groups.entries()) {
            for (const cid of info.colIds) {
                groupedColIdToGroupId.set(cid, groupId);
            }
        }

        const computeBoundaryX = (anchorColId: string): number | null => {
            const anchorIdx = fullOrder.indexOf(anchorColId);
            if (anchorIdx === -1) return null;

            let prevVisibleColId: string | null = null;
            for (let i = anchorIdx - 1; i >= 0; i--) {
                if (!hidden.has(fullOrder[i])) {
                    prevVisibleColId = fullOrder[i];
                    break;
                }
            }

            let nextVisibleColId: string | null = null;
            for (let i = anchorIdx + 1; i < fullOrder.length; i++) {
                if (!hidden.has(fullOrder[i])) {
                    nextVisibleColId = fullOrder[i];
                    break;
                }
            }

            if (!prevVisibleColId && !nextVisibleColId) return null;

            const prevHeader = prevVisibleColId
                ? (this.elRef.nativeElement.querySelector(
                      `.ag-header-cell[col-id="${prevVisibleColId}"]`
                  ) as HTMLElement | null)
                : null;
            const nextHeader = nextVisibleColId
                ? (this.elRef.nativeElement.querySelector(
                      `.ag-header-cell[col-id="${nextVisibleColId}"]`
                  ) as HTMLElement | null)
                : null;

            const prevRect = prevHeader?.getBoundingClientRect() ?? null;
            const nextRect = nextHeader?.getBoundingClientRect() ?? null;

            if (prevRect && nextRect) {
                return (prevRect.right + nextRect.left) / 2 - containerRect.left - 10;
            } else if (nextRect) {
                return nextRect.left - containerRect.left - 10;
            } else {
                return prevRect!.right - containerRect.left - 10;
            }
        };

        for (const hiddenId of hidden) {
            if (groupedColIdToGroupId.has(hiddenId)) continue;

            const boundaryX = computeBoundaryX(hiddenId);
            if (boundaryX === null) continue;

            const colLabel = this.getColLabel(hiddenId);
            const existing = badges.filter((b) => Math.abs(b.x - boundaryX) < 5);
            const offsetX = existing.length * 22;

            badges.push({ colId: hiddenId, x: boundaryX + offsetX, y, label: colLabel });
        }

        const emittedGroups = new Set<string>();
        for (const hiddenId of hidden) {
            const groupId = groupedColIdToGroupId.get(hiddenId);
            if (!groupId || emittedGroups.has(groupId)) continue;
            emittedGroups.add(groupId);

            const info = groups.get(groupId)!;
            const sortedColIds = info.colIds
                .filter((id) => fullOrder.indexOf(id) !== -1)
                .sort((a, b) => fullOrder.indexOf(a) - fullOrder.indexOf(b));
            if (sortedColIds.length === 0) continue;

            const anchorColId = sortedColIds[0];
            const boundaryX = computeBoundaryX(anchorColId);
            if (boundaryX === null) continue;

            const existing = badges.filter((b) => Math.abs(b.x - boundaryX) < 5);
            const offsetX = existing.length * 22;

            badges.push({ colId: groupId, x: boundaryX + offsetX, y, label: info.label });
        }

        this.hiddenColumnBadges.set(badges);
        this.cdr.markForCheck();
    }

    private getColLabel(colId: string): string {
        if (colId === CDT_COLUMN_KIND.EXPRESSION) return 'Expression';
        if (colId === CDT_COLUMN_KIND.MANIPULATION) return 'Manipulation';
        if (colId === 'prompt_id') return 'Prompt';
        if (colId === 'route_code') return 'Route Code';
        if (colId === 'group_name') return 'Condition Name';
        if (colId === 'next_node') return 'Next Node';
        if (colId.startsWith(CDT_FIELD_PREFIX)) return colId.substring(CDT_FIELD_PREFIX.length);
        if (colId.startsWith(CDT_MANIP_PREFIX)) return colId.substring(CDT_MANIP_PREFIX.length);
        return colId;
    }

    private buildFieldColDef(fieldName: string): ColDef {
        const colId = `${CDT_FIELD_PREFIX}${fieldName}`;
        return {
            colId,
            headerComponent: ColumnHeaderMenuComponent,
            headerComponentParams: {
                label: fieldName,
                colId,
                iconClass: 'ti ti-x',
                tooltip: `Remove variable "${fieldName}"`,
                variant: 'delete',
                showFreeze: false,
                showChevron: false,
                onIconClick: () => this.removeFieldColumn(fieldName),
            },
            editable: (params: EditableCallbackParams<ConditionGroup>) =>
                !this.isRowLocked(params.data as ConditionGroup),
            minWidth: Math.max(70, fieldName.length * 9 + 52),
            flex: 1,
            cellRenderer: MonacoCellRendererComponent,
            cellRendererParams: { singleLine: true },
            cellStyle: (params: RowSpanParams<ConditionGroup>) => {
                const locked = this.isRowLocked(params.data as ConditionGroup);
                return locked
                    ? { fontSize: '13px', fontFamily: 'monospace', color: '#888888' }
                    : { fontSize: '13px', fontFamily: 'monospace', color: '#d4d4d4' };
            },
            valueGetter: (params: ValueGetterParams<ConditionGroup>) => {
                if (this.isRowLocked(params.data as ConditionGroup)) return '*';
                return toDisplayExpression(params.data?.field_expressions?.[fieldName] || '');
            },
            valueSetter: (params: ValueSetterParams<ConditionGroup>) => {
                if (!params.data.field_expressions) {
                    params.data.field_expressions = {};
                }
                params.data.field_expressions[fieldName] = normalizeOpPart(params.newValue || '');
                return true;
            },
        };
    }

    private buildManipFieldColDef(fieldName: string): ColDef {
        const colId = `${CDT_MANIP_PREFIX}${fieldName}`;
        return {
            colId,
            headerComponent: ColumnHeaderMenuComponent,
            headerComponentParams: {
                label: fieldName,
                colId,
                iconClass: 'ti ti-x',
                tooltip: `Remove variable "${fieldName}"`,
                variant: 'delete',
                showFreeze: false,
                showChevron: false,
                onIconClick: () => this.removeManipFieldColumn(fieldName),
            },
            editable: (params: EditableCallbackParams<ConditionGroup>) =>
                !this.isManipRowLocked(params.data as ConditionGroup),
            minWidth: Math.max(70, fieldName.length * 9 + 52),
            flex: 1,
            cellRenderer: MonacoCellRendererComponent,
            cellRendererParams: { singleLine: true },
            cellStyle: (params: RowSpanParams<ConditionGroup>) => {
                const locked = this.isManipRowLocked(params.data as ConditionGroup);
                return locked
                    ? { fontSize: '13px', fontFamily: 'monospace', color: '#888888' }
                    : { fontSize: '13px', fontFamily: 'monospace', color: '#d4d4d4' };
            },
            valueGetter: (params: ValueGetterParams<ConditionGroup>) => {
                if (this.isManipRowLocked(params.data as ConditionGroup)) return '*';
                return toDisplayExpression(params.data?.field_manipulations?.[fieldName] || '');
            },
            valueSetter: (params: ValueSetterParams<ConditionGroup>) => {
                if (!params.data.field_manipulations) {
                    params.data.field_manipulations = {};
                }
                params.data.field_manipulations[fieldName] = params.newValue ?? '';
                return true;
            },
        };
    }

    private buildManipulationColDef(): ColDef {
        return {
            colId: CDT_COLUMN_KIND.MANIPULATION,
            field: CDT_COLUMN_KIND.MANIPULATION,
            headerComponent: ColumnHeaderMenuComponent,
            headerComponentParams: this.makeMenuHeaderParams(CDT_COLUMN_KIND.MANIPULATION, 'Manipulation'),
            editable: true,
            flex: 1,
            cellRenderer: MonacoCellRendererComponent,
            cellEditor: ExpressionBuilderCellEditorComponent,
            cellEditorPopup: true,
            cellEditorPopupPosition: 'over',
            cellEditorParams: () => ({
                variables: this.collectExpressionVariables(),
                mode: CDT_COLUMN_KIND.MANIPULATION,
            }),
            // Allow plain Enter to insert newlines inside the popup editor.
            // Ctrl/Cmd+Enter (handled by ExpressionBuilderComponent) commits.
            suppressKeyboardEvent: (params) => params.editing && params.event.key === 'Enter',
            cellStyle: { fontSize: '13px', fontFamily: 'monospace', color: '#d4d4d4' },
            valueGetter: (params: ValueGetterParams<ConditionGroup>) =>
                toDisplayExpression(params.data?.manipulation ?? ''),
            valueSetter: (params: ValueSetterParams<ConditionGroup>) => {
                params.data.manipulation = params.newValue ?? '';
                return true;
            },
        };
    }

    private buildExpressionColDef(): ColDef {
        return {
            colId: CDT_COLUMN_KIND.EXPRESSION,
            field: CDT_COLUMN_KIND.EXPRESSION,
            headerComponent: ColumnHeaderMenuComponent,
            headerComponentParams: this.makeMenuHeaderParams(CDT_COLUMN_KIND.EXPRESSION, 'Expression'),
            editable: true,
            flex: 1,
            cellRenderer: MonacoCellRendererComponent,
            cellEditor: ExpressionBuilderCellEditorComponent,
            cellEditorPopup: true,
            cellEditorPopupPosition: 'over',
            cellEditorParams: () => ({ variables: this.collectExpressionVariables() }),
            // Allow plain Enter to insert newlines inside the popup editor.
            // Ctrl/Cmd+Enter (handled by ExpressionBuilderComponent) commits.
            suppressKeyboardEvent: (params) => params.editing && params.event.key === 'Enter',
            cellStyle: () => ({ fontSize: '13px', fontFamily: 'monospace', color: '#d4d4d4' }),
            valueGetter: (params: ValueGetterParams<ConditionGroup>) =>
                toDisplayExpression(params.data?.expression ?? ''),
            valueSetter: (params: ValueSetterParams<ConditionGroup>) => {
                // The editor's getValue() already returns stored format, so write as-is.
                const raw = params.newValue || '';
                params.data.expression = raw ? normalizeExpressionSpacing(raw) : '';
                return true;
            },
        };
    }

    private collectExpressionVariables(): string[] {
        const seen = new Set<string>();

        // Domain keys and preInputMapKeys (same source as exprMultiSelectItems)
        for (const k of this.domainKeys()) {
            seen.add(k);
        }
        for (const k of this.preInputMapKeys()) {
            seen.add(k);
        }

        // Active field_* column names (strip the CDT_FIELD_PREFIX)
        for (const colId of this.movableColumnOrder()) {
            if (colId.startsWith(CDT_FIELD_PREFIX)) {
                seen.add(colId.substring(CDT_FIELD_PREFIX.length));
            }
        }

        return Array.from(seen);
    }

    private buildColumnDefs(): (ColDef | ColGroupDef)[] {
        const selectionCol: ColDef = {
            colId: 'selection',
            headerName: '',
            headerComponent: SelectionCountHeaderComponent,
            cellRenderer: SelectionCellRendererComponent,
            width: 64,
            minWidth: 64,
            maxWidth: 64,
            suppressMovable: true,
            sortable: false,
            resizable: false,
            cellStyle: { display: 'flex', alignItems: 'center', padding: '0 4px' },
        };

        const enabledCol: ColDef = {
            colId: 'dock_visible',
            field: 'dock_visible',
            headerComponent: EnableFilterHeaderComponent,
            headerComponentParams: {
                getMode: () => this.enableFilterMode(),
                setMode: (mode: EnableFilterMode) => {
                    this.enableFilterMode.set(mode);
                    this.gridApi?.refreshHeader();
                    this.saveGridState();
                },
            },
            editable: true,
            width: 85,
            minWidth: 75,
            cellDataType: 'boolean',
            suppressMovable: true,
            cellStyle: { display: 'flex', alignItems: 'center', justifyContent: 'center' },
        };

        const staticBefore: ColDef[] = [
            selectionCol,
            enabledCol,
            {
                colId: 'group_name',
                headerComponent: ColumnHeaderMenuComponent,
                headerComponentParams: this.makeMenuHeaderParams('group_name', 'Condition Name'),
                field: 'group_name',
                editable: true,
                flex: 1,
                suppressMovable: true,
                cellStyle: {
                    fontSize: '14px',
                },
            },
        ];

        // Expression section
        const visibleFieldCols: ColDef[] = this.movableColumnOrder()
            .filter((id) => id.startsWith(CDT_FIELD_PREFIX))
            .map((id) => this.buildFieldColDef(id.substring(CDT_FIELD_PREFIX.length)));

        const hasFieldCols = visibleFieldCols.length > 0;
        const expressionCol = this.buildExpressionColDef();

        let exprSection: (ColDef | ColGroupDef)[];
        if (hasFieldCols) {
            exprSection = [
                expressionCol,
                {
                    groupId: 'expr-params-group',
                    marryChildren: false,
                    headerGroupComponent: ParamsGroupHeaderComponent,
                    headerGroupComponentParams: {
                        mode: 'full',
                        onAdd: (event: MouseEvent) => this.toggleFieldPicker(event),
                        onFreeze: () => {
                            const ids = visibleFieldCols.map((c) => c.colId!);
                            if (ids.length === 0) return;
                            const lastChild = ids[ids.length - 1];
                            if (this.freezeAnchorColId() === lastChild) {
                                this.toggleFreeze(lastChild);
                            } else {
                                this.freezeThroughLastChild(ids);
                            }
                        },
                        onHide: () =>
                            this.hideColumnGroup(
                                'expr-params-group',
                                'Params',
                                visibleFieldCols.map((c) => c.colId!)
                            ),
                        isPinned: () => {
                            const ids = visibleFieldCols.map((c) => c.colId!);
                            if (ids.length === 0) return false;
                            return this.freezeAnchorColId() === ids[ids.length - 1];
                        },
                    },
                    children: visibleFieldCols,
                } as ColGroupDef,
            ];
        } else {
            exprSection = [expressionCol];
        }

        const promptIdCol: ColDef = {
            colId: 'prompt_id',
            headerComponent: ColumnHeaderMenuComponent,
            headerComponentParams: this.makeMenuHeaderParams('prompt_id', 'Prompt ID'),
            field: 'prompt_id',
            suppressMovable: true,
            editable: true,
            singleClickEdit: true,
            width: 150,
            cellRenderer: PromptTooltipRendererComponent,
            cellRendererParams: () => ({
                prompts: this.prompts(),
                llmConfigs: this.llmConfigs(),
                onPromptChange: (
                    promptId: string,
                    field: keyof PromptConfig,
                    value: PromptConfig[keyof PromptConfig]
                ) => {
                    this.promptChange.emit({ promptId, field, value });
                },
                onOpenInPromptLibrary: (promptId: string) => {
                    this.openPromptLibrary.emit({ action: 'edit', promptId });
                },
            }),
            cellEditor: PromptIdCellEditorComponent,
            cellEditorParams: () => ({
                prompts: this.prompts(),
                defaultLlmId: this.defaultLlmId(),
                llmConfigs: this.llmConfigs(),
                onNavigateToPrompts: () => {
                    this.openPromptLibrary.emit({ action: 'create' });
                },
                onOpenPromptForEdit: (promptId: string) => {
                    this.openPromptLibrary.emit({ action: 'edit', promptId });
                },
            }),
            cellEditorPopup: false,
            cellStyle: {
                fontSize: '14px',
            },
        };

        // Manipulation section
        const visibleManipCols: ColDef[] = this.manipColumnOrder()
            .filter((id) => id.startsWith(CDT_MANIP_PREFIX))
            .map((id) => this.buildManipFieldColDef(id.substring(CDT_MANIP_PREFIX.length)));

        const hasManipCols = visibleManipCols.length > 0;
        const manipCol = this.buildManipulationColDef();

        let manipSection: (ColDef | ColGroupDef)[];
        if (hasManipCols) {
            manipSection = [
                manipCol,
                {
                    groupId: 'manip-params-group',
                    marryChildren: false,
                    headerGroupComponent: ParamsGroupHeaderComponent,
                    headerGroupComponentParams: {
                        mode: 'full',
                        onAdd: (event: MouseEvent) => this.toggleManipFieldPicker(event),
                        onFreeze: () => {
                            const ids = visibleManipCols.map((c) => c.colId!);
                            if (ids.length === 0) return;
                            const lastChild = ids[ids.length - 1];
                            if (this.freezeAnchorColId() === lastChild) {
                                this.toggleFreeze(lastChild);
                            } else {
                                this.freezeThroughLastChild(ids);
                            }
                        },
                        onHide: () =>
                            this.hideColumnGroup(
                                'manip-params-group',
                                'Params',
                                visibleManipCols.map((c) => c.colId!)
                            ),
                        isPinned: () => {
                            const ids = visibleManipCols.map((c) => c.colId!);
                            if (ids.length === 0) return false;
                            return this.freezeAnchorColId() === ids[ids.length - 1];
                        },
                    },
                    children: visibleManipCols,
                } as ColGroupDef,
            ];
        } else {
            manipSection = [manipCol];
        }

        const routeCodeCol: ColDef = {
            colId: 'route_code',
            headerComponent: ColumnHeaderMenuComponent,
            headerComponentParams: this.makeMenuHeaderParams('route_code', 'Route Code'),
            field: 'route_code',
            editable: true,
            width: 150,
            suppressMovable: true,
            cellStyle: {
                fontSize: '14px',
            },
        };

        const skipCol: ColDef = {
            headerName: 'Continue',
            field: 'continue_flag',
            editable: true,
            width: 65,
            minWidth: 50,
            cellDataType: 'boolean',
            suppressMovable: true,
            cellStyle: {
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
            },
        };

        const deleteCol: ColDef = {
            headerName: '',
            headerComponent: IconHeaderComponent,
            headerComponentParams: {
                label: '',
                variant: 'delete',
            },
            field: 'actions',
            cellRenderer: () => {
                return `<i class="ti ti-x" style="color: rgba(255,255,255,0.5); font-size: 1rem; cursor: pointer;"></i>`;
            },
            width: 60,
            minWidth: 60,
            maxWidth: 60,
            suppressMovable: true,
            cellStyle: {
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                cursor: 'pointer',
            },
            onCellClicked: (event: CellClickedEvent) => {
                this.deleteRow(event.node.rowIndex!);
            },
        };

        return [...staticBefore, ...exprSection, promptIdCol, ...manipSection, routeCodeCol, skipCol, deleteCol];
    }

    private applyWidths(defs: (ColDef | ColGroupDef)[], widthMap: Map<string, number>): (ColDef | ColGroupDef)[] {
        return defs.map((def) => {
            if ('children' in def) {
                return {
                    ...def,
                    children: this.applyWidths((def as ColGroupDef).children as (ColDef | ColGroupDef)[], widthMap),
                };
            }
            const col = def as ColDef;
            const id = col.colId || col.field;
            if (id && widthMap.has(id)) {
                return { ...col, flex: undefined, width: widthMap.get(id) };
            }
            return col;
        });
    }

    private rebuildColumnDefs(): void {
        // Start from current grid state (live resizes), then fill in saved widths for columns not yet in grid
        const widthMap = new Map<string, number>();
        this.gridApi?.getColumnState()?.forEach((s) => {
            if (s.colId && s.width) widthMap.set(s.colId, s.width);
        });
        // savedColumnWidths fills in columns not yet reflected in grid state (e.g. on initial load)
        this.savedColumnWidths.forEach((w, id) => {
            if (!widthMap.has(id)) widthMap.set(id, w);
        });

        this.columnDefs = this.buildColumnDefs();

        if (widthMap.size > 0) {
            this.columnDefs = this.applyWidths(this.columnDefs, widthMap) as (ColDef | ColGroupDef)[];
        }

        if (this.gridApi) {
            this.isRebuilding = true;
            this.gridApi.setGridOption('columnDefs', this.columnDefs);
            this.isRebuilding = false;

            // Re-apply hidden/frozen state after rebuild
            this.reapplyColumnState();
        }
        setTimeout(() => this.updateAddButtonPositions(), 50);
    }

    /**
     * Syncs param cells from parsed expressions for every row.
     * Runs whenever activeFieldColumns() changes (i.e. a column is added, removed or
     * reordered) so that rows whose expression was typed before a column existed get
     * their new cell populated immediately.
     *
     * - ok:true  → for each active column: write parsed.parts[name] if present, '' otherwise.
     *              Expression is treated as source of truth for parseable rows.
     * - ok:false → leave field_expressions untouched (locked row).
     * - Empty expression → skip the row entirely (nothing to parse).
     */
    private syncRowsFromExpression(): void {
        untracked(() => {
            const rows = this.rowData();
            const activeNames = this.activeFieldColumns();
            if (rows.length === 0 || activeNames.length === 0) return;

            this.isSyncing = true;
            try {
                rows.map((row) => ({ row, expr: (row.expression ?? '').trim() }))
                    .filter(({ expr }) => !!expr)
                    .map(({ row, expr }) => ({ row, parsed: parseExpression(expr) }))
                    .filter(({ parsed }) => parsed.ok)
                    .forEach(({ row, parsed }) => {
                        row.field_expressions ??= {};
                        activeNames.forEach((name) => {
                            row.field_expressions![name] = parsed.parts[name] ?? '';
                        });
                    });

                // Rows are mutated in place — no rowData.set needed.
                // refreshCells tells ag-grid to re-render without touching Angular signals.
                this.gridApi?.refreshCells({ force: true });
            } finally {
                this.isSyncing = false;
            }
        });
    }

    private syncRowsFromManipulation(): void {
        untracked(() => {
            const rows = this.rowData();
            const activeNames = this.activeManipFieldColumns();
            if (rows.length === 0 || activeNames.length === 0) return;

            this.isSyncing = true;
            try {
                rows.map((row) => ({ row, manip: (row.manipulation ?? '').trim() }))
                    .filter(({ manip }) => !!manip)
                    .map(({ row, manip }) => ({ row, parsed: parseManipulation(manip) }))
                    .filter(({ parsed }) => parsed.ok)
                    .forEach(({ row, parsed }) => {
                        row.field_manipulations ??= {};
                        activeNames.forEach((name) => {
                            row.field_manipulations![name] = parsed.parts[name] ?? '';
                        });
                    });
                this.gridApi?.refreshCells({ force: true });
            } finally {
                this.isSyncing = false;
            }
        });
    }

    /** Re-applies the stored pinned/hidden state to the live grid after a column defs rebuild. */
    private reapplyColumnState(): void {
        const frozen = this.frozenColIds();
        const hidden = this.hiddenColIds();
        if (frozen.size === 0 && hidden.size === 0) return;

        const stateUpdates: { colId: string; pinned?: 'left' | null; hide?: boolean }[] = [];

        frozen.forEach((colId) => stateUpdates.push({ colId, pinned: 'left' }));
        hidden.forEach((colId) => stateUpdates.push({ colId, hide: true }));

        this.gridApi.applyColumnState({ state: stateUpdates });
        setTimeout(() => this.updateBadgePositions(), 50);
    }

    private updateAddButtonPositions(): void {
        const wrapperEl = this.elRef.nativeElement.querySelector('.grid-wrapper') as HTMLElement | null;
        const containerEl = wrapperEl ?? this.elRef.nativeElement;
        const containerRect = containerEl.getBoundingClientRect();
        const containerWidth = containerEl.clientWidth;
        const btnHalfWidth = 20; // half of ~40px button width used for clamping margin

        const clampX = (rawX: number): number => Math.max(btnHalfWidth, Math.min(rawX, containerWidth - btnHalfWidth));

        const findLeafCell = (colId: string): HTMLElement | null => {
            const cells = Array.from(
                this.elRef.nativeElement.querySelectorAll(`.ag-header-cell[col-id="${colId}"]`)
            ) as HTMLElement[];
            // Exclude group-header cells (those have .ag-header-group-cell)
            return cells.find((c) => !c.classList.contains('ag-header-group-cell')) ?? null;
        };

        if (this.hasFieldCols()) {
            this.exprAddPos.set(null);
        } else {
            const cell = findLeafCell(CDT_COLUMN_KIND.EXPRESSION);
            if (cell) {
                const r = cell.getBoundingClientRect();
                this.exprAddPos.set({ x: clampX(r.right - containerRect.left), y: 0 });
            } else {
                this.exprAddPos.set(null);
            }
        }

        if (this.hasManipCols()) {
            this.manipAddPos.set(null);
        } else {
            const cell = findLeafCell(CDT_COLUMN_KIND.MANIPULATION);
            if (cell) {
                const r = cell.getBoundingClientRect();
                this.manipAddPos.set({ x: clampX(r.right - containerRect.left), y: 0 });
            } else {
                this.manipAddPos.set(null);
            }
        }

        // Also update badge positions whenever buttons are updated
        this.updateBadgePositions();
    }

    toggleFieldPicker(event?: MouseEvent): void {
        const next = [...this.activeFieldColumns()];
        this.exprSelectedFieldsModel.set(next);
        const anchor = (event?.currentTarget ?? event?.target) as HTMLElement | undefined;
        if (anchor) {
            this.exprMultiSelect.openAt(anchor, next);
        } else {
            this.exprMultiSelect.openDropdown();
        }
    }

    addFieldColumn(fieldName: string): void {
        const colId = `${CDT_FIELD_PREFIX}${fieldName}`;
        const order = this.movableColumnOrder();
        if (!order.includes(colId)) {
            this.movableColumnOrder.set([...order, colId]);
        }
        this.saveGridState();
    }

    removeFieldColumn(fieldName: string): void {
        const colId = `${CDT_FIELD_PREFIX}${fieldName}`;
        this.movableColumnOrder.set(this.movableColumnOrder().filter((id) => id !== colId));
        this.saveGridState();
    }

    onExprSelectionChange(values: unknown[]): void {
        const newSet = new Set(values as string[]);
        const currentSet = new Set(this.activeFieldColumns());
        // Newly checked → add
        for (const name of newSet) {
            if (!currentSet.has(name)) this.addFieldColumn(name);
        }
        // Newly unchecked → remove
        for (const name of currentSet) {
            if (!newSet.has(name)) this.removeFieldColumn(name);
        }
    }

    toggleManipFieldPicker(event?: MouseEvent): void {
        const next = [...this.activeManipFieldColumns()];
        this.manipSelectedFieldsModel.set(next);
        const anchor = (event?.currentTarget ?? event?.target) as HTMLElement | undefined;
        if (anchor) {
            this.manipMultiSelect.openAt(anchor, next);
        } else {
            this.manipMultiSelect.openDropdown();
        }
    }

    addManipFieldColumn(fieldName: string): void {
        const colId = `${CDT_MANIP_PREFIX}${fieldName}`;
        const order = this.manipColumnOrder();
        if (!order.includes(colId)) {
            this.manipColumnOrder.set([...order, colId]);
        }
        this.saveGridState();
    }

    removeManipFieldColumn(fieldName: string): void {
        const colId = `${CDT_MANIP_PREFIX}${fieldName}`;
        this.manipColumnOrder.set(this.manipColumnOrder().filter((id) => id !== colId));
        this.saveGridState();
    }

    onManipSelectionChange(values: unknown[]): void {
        const newSet = new Set(values as string[]);
        const currentSet = new Set(this.activeManipFieldColumns());
        // Newly checked → add
        for (const name of newSet) {
            if (!currentSet.has(name)) this.addManipFieldColumn(name);
        }
        // Newly unchecked → remove
        for (const name of currentSet) {
            if (!newSet.has(name)) this.removeManipFieldColumn(name);
        }
    }

    onGridReady(params: GridReadyEvent): void {
        this.gridApi = params.api;
        this.setupBodyClickListener();
        this.setupOutsideClickListener();
        this.setupRowDragListener();
        this.gridApi.addEventListener('selectionChanged', () => {
            const nodes = this.gridApi.getSelectedNodes();
            this.selectedRowCount.set(nodes.length);
            this.selectedRowsAllUngrouped.set(
                nodes.every((n: IRowNode) => !(n.data as ConditionGroup | undefined)?.section)
            );
        });
        const overlayEvents = [
            'modelUpdated',
            'firstDataRendered',
            'bodyScroll',
            'viewportChanged',
            'rowDataUpdated',
            'filterChanged',
            'sortChanged',
            'paginationChanged',
        ] as const;
        for (const ev of overlayEvents) {
            this.gridApi.addEventListener(ev, () => this.recomputeGroupOverlays());
        }
        // Apply saved column widths after grid is ready
        if (this.savedColumnWidths.size > 0) {
            const colState = this.gridApi.getColumnState().map((s) => {
                const saved = s.colId ? this.savedColumnWidths.get(s.colId) : undefined;
                return saved ? { ...s, width: saved } : s;
            });
            this.gridApi.applyColumnState({ state: colState });
        }
        // Apply saved frozen/hidden state
        this.reapplyColumnState();
        this.autoCollapseGroupsOnFirstLoad();
        setTimeout(() => {
            this.updateAddButtonPositions();
            this.recomputeGroupOverlays();
        }, 100);
        this.positionResizeObserver = new ResizeObserver(() => this.updateAddButtonPositions());
        this.positionResizeObserver.observe(this.elRef.nativeElement);
    }

    onBodyScroll(event: BodyScrollEvent): void {
        if (event.direction === 'horizontal') {
            this.updateAddButtonPositions();
        }
    }

    private bodyClickHandler = () => {
        // Close context menu on any click
        if (this.contextMenu()) {
            this.contextMenu.set(null);
        }
    };

    private setupBodyClickListener(): void {
        document.addEventListener('click', this.bodyClickHandler);
    }

    private setupOutsideClickListener(): void {
        this.outsideClickUnlisten = this.renderer.listen('document', 'pointerdown', (event: PointerEvent) => {
            const target = event.target as Node | null;
            if (!target) return;
            const gridRoot = this.elRef.nativeElement as HTMLElement;
            // Click was inside the grid — keep focus
            if (gridRoot.contains(target)) return;
            // Click was inside an ag-grid popup rendered to document body (dropdowns, menus)
            const path = (event.composedPath?.() ?? []) as HTMLElement[];
            const inAgPopup = path.some(
                (el) => el?.classList?.contains?.('ag-popup') || el?.classList?.contains?.('ag-popup-child')
            );
            if (inAgPopup) return;
            // Clear focused cell so the purple border disappears
            this.gridApi?.clearFocusedCell();
        });
    }

    ngOnDestroy(): void {
        document.removeEventListener('click', this.bodyClickHandler);
        this.outsideClickUnlisten?.();
        this.positionResizeObserver?.disconnect();
        this.groupMenuOverlayRef?.dispose();
        const hostEl = this.elRef.nativeElement;
        hostEl.removeEventListener('mousedown', this.rowDragMouseDown, true);
    }

    private rowDragMouseDown = (e: MouseEvent): void => {
        if (e.button !== 0) return;
        const target = e.target as Element | null;
        if (!target) return;
        const grip = target.closest('.drag-grip');
        if (!grip) return;
        const rowEl = grip.closest('.ag-row') as HTMLElement | null;
        if (!rowEl) return;
        const sourceId = rowEl.getAttribute('row-id');
        if (!sourceId) return;
        const sourceNode = this.gridApi?.getRowNode(sourceId);
        if (!sourceNode) return;
        e.preventDefault();
        const startY = e.clientY;
        let dragStarted = false;
        const onMove = (mv: MouseEvent): void => {
            if (!dragStarted && Math.abs(mv.clientY - startY) > 4) {
                dragStarted = true;
                document.body.style.cursor = 'grabbing';
                document.body.style.userSelect = 'none';
            }
            if (dragStarted) {
                const hoverEl = document.elementFromPoint(mv.clientX, mv.clientY) as Element | null;
                const hoverRow = hoverEl?.closest('.ag-row') as HTMLElement | null;
                const wrapperEl = this.elRef.nativeElement.querySelector('.grid-wrapper') as HTMLElement | null;
                if (hoverRow && wrapperEl) {
                    const rowRect = hoverRow.getBoundingClientRect();
                    const wrapperRect = wrapperEl.getBoundingClientRect();
                    const midpoint = rowRect.top + rowRect.height / 2;
                    const insertBefore = mv.clientY < midpoint;
                    const lineY = insertBefore ? rowRect.top - wrapperRect.top : rowRect.bottom - wrapperRect.top;
                    this.dropIndicatorTop.set(lineY);
                } else {
                    this.dropIndicatorTop.set(null);
                }
            }
        };
        const onUp = (mu: MouseEvent): void => {
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
            this.dropIndicatorTop.set(null);
            if (!dragStarted) return;
            const overEl = document.elementFromPoint(mu.clientX, mu.clientY) as Element | null;
            const overRow = overEl?.closest('.ag-row') as HTMLElement | null;
            const overId = overRow?.getAttribute('row-id');
            if (!overId) return;
            const overNode = this.gridApi?.getRowNode(overId);
            if (!overNode) return;
            const overRect = overRow!.getBoundingClientRect();
            const insertBefore = mu.clientY < overRect.top + overRect.height / 2;
            this.handleManualRowReorder(sourceNode, overNode, insertBefore);
        };
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
    };

    private setupRowDragListener(): void {
        const hostEl = this.elRef.nativeElement;
        hostEl.addEventListener('mousedown', this.rowDragMouseDown, true);
    }

    /**
     * Returns true iff the row has a non-empty expression that cannot be decomposed
     * into per-variable AND clauses by parseExpression.
     */
    public isRowLocked(rowData: ConditionGroup): boolean {
        const expr = rowData?.expression?.trim();
        if (!expr) return false;
        // Lock only when the expression is syntactically unparseable — not when it
        // references a variable that happens to not be an active param column.
        const result = parseExpression(expr);
        return !result.ok;
    }

    /**
     * Returns true iff the row has a non-empty manipulation that cannot be decomposed
     * into per-variable assignment statements by parseManipulation.
     */
    public isManipRowLocked(rowData: ConditionGroup): boolean {
        const manip = (rowData?.manipulation ?? '').trim();
        if (!manip) return false;
        return !parseManipulation(manip).ok;
    }

    onCellValueChanged(event: CellValueChangedEvent): void {
        // Guard against recursive loops triggered by programmatic cell writes
        if (this.isSyncing) return;

        const colId: string = event.colDef.colId ?? '';
        const rowData = event.data as ConditionGroup;
        const activeNames = this.activeFieldColumns();
        const activeManipNames = this.activeManipFieldColumns();

        if (colId === CDT_COLUMN_KIND.EXPRESSION) {
            // Expression → params sync
            const newExpr: string = (rowData.expression ?? '').trim();

            this.isSyncing = true;
            try {
                if (!rowData.field_expressions) {
                    rowData.field_expressions = {};
                }

                if (!newExpr) {
                    // Empty expression → clear all active param cells
                    for (const name of activeNames) {
                        rowData.field_expressions[name] = '';
                    }
                } else {
                    // Parse without knownVarNames — validity is purely syntactic now.
                    const parsed = parseExpression(newExpr);
                    if (parsed.ok) {
                        // Write parsed parts only for active columns; clear active
                        // names not present in the parsed result. Parts that reference
                        // variables not in activeNames are silently ignored (the data
                        // stays in the expression cell but no column is auto-created).
                        for (const name of activeNames) {
                            rowData.field_expressions[name] = parsed.parts[name] ?? '';
                        }
                    }
                    // ok:false → leave field_expressions untouched (locked state)
                }

                this.gridApi?.refreshCells({ rowNodes: [event.node!], force: true });
            } finally {
                this.isSyncing = false;
            }
        } else if (colId.startsWith(CDT_FIELD_PREFIX)) {
            // Params → expression sync
            if (this.isRowLocked(rowData)) {
                // Locked row — don't recompose; the param cells should not be editable anyway
                this.isSyncing = true;
                try {
                    this.gridApi?.refreshCells({ rowNodes: [event.node!], force: true });
                } finally {
                    this.isSyncing = false;
                }
            } else {
                // Recompose expression from all active field_expressions
                const currentParts: Record<string, string> = {};
                for (const name of activeNames) {
                    currentParts[name] = rowData.field_expressions?.[name]?.trim() ?? '';
                }

                const newExpr = composeExpression(currentParts, activeNames);

                this.isSyncing = true;
                try {
                    rowData.expression = newExpr || null;
                    this.gridApi?.refreshCells({ rowNodes: [event.node!], force: true });
                } finally {
                    this.isSyncing = false;
                }
            }
        } else if (colId === CDT_COLUMN_KIND.MANIPULATION) {
            // Manipulation → manip params sync
            const newManip: string = (rowData.manipulation ?? '').trim();

            this.isSyncing = true;
            try {
                if (!rowData.field_manipulations) {
                    rowData.field_manipulations = {};
                }

                if (!newManip) {
                    // Empty manipulation → clear all active manip param cells
                    for (const name of activeManipNames) {
                        rowData.field_manipulations[name] = '';
                    }
                } else {
                    const parsed = parseManipulation(newManip);
                    if (parsed.ok) {
                        // Write parsed parts only for active columns; clear active
                        // names not present in the parsed result.
                        for (const name of activeManipNames) {
                            rowData.field_manipulations[name] = parsed.parts[name] ?? '';
                        }
                    }
                    // ok:false → leave field_manipulations untouched (locked state)
                }

                this.gridApi?.refreshCells({ rowNodes: [event.node!], force: true });
            } finally {
                this.isSyncing = false;
            }
        } else if (colId.startsWith(CDT_MANIP_PREFIX)) {
            // Manip params → manipulation sync
            if (this.isManipRowLocked(rowData)) {
                // Locked row — don't recompose; the manip param cells should not be editable anyway
                this.isSyncing = true;
                try {
                    this.gridApi?.refreshCells({ rowNodes: [event.node!], force: true });
                } finally {
                    this.isSyncing = false;
                }
            } else {
                // Recompose manipulation from all active field_manipulations
                const currentParts: Record<string, string> = {};
                for (const name of activeManipNames) {
                    currentParts[name] = rowData.field_manipulations?.[name]?.trim() ?? '';
                }

                const newManip = composeManipulation(currentParts, activeManipNames);

                this.isSyncing = true;
                try {
                    rowData.manipulation = newManip || null;
                    this.gridApi?.refreshCells({ rowNodes: [event.node!], force: true });
                } finally {
                    this.isSyncing = false;
                }
            }
        }

        const updatedRows = this.getUpdatedRows();
        this.emitChanges(updatedRows);
    }

    private createNewRow(index: number): ConditionGroup {
        const fieldExpressions: Record<string, string> = {};
        this.activeFieldColumns().forEach((f) => (fieldExpressions[f] = ''));
        return {
            group_name: `Condition ${index + 1}`,
            group_type: 'complex',
            expression: null,
            conditions: [],
            manipulation: null,
            continue_flag: false,
            route_code: '',
            dock_visible: true,
            next_node: null,
            order: index + 1,
            field_expressions: fieldExpressions,
        };
    }

    addRow(): void {
        const currentRows = this.rowData();
        const maxOrder = currentRows.reduce((max, r) => Math.max(max, r.order ?? 0), 0);
        const maxConditionNumber = currentRows.reduce((max, r) => {
            const match = /^Condition (\d+)$/.exec(r.group_name ?? '');
            return match ? Math.max(max, Number(match[1])) : max;
        }, 0);
        // Reuse createNewRow for default structure (field_expressions etc.), then assign a
        // collision-free name and order based on the current MAX (not row count), so deleting a
        // middle condition and adding a new one never duplicates an existing name/order.
        const newRow: ConditionGroup = {
            ...this.createNewRow(0),
            group_name: `Condition ${maxConditionNumber + 1}`,
            order: maxOrder + 1,
        };
        const updated = [...currentRows, newRow];
        this.rowData.set(updated);
        this.emitChanges(updated);
    }

    addRowAbove(): void {
        this.insertRowAtContext(0);
    }
    addRowBelow(): void {
        this.insertRowAtContext(1);
    }

    private insertRowAtContext(offset: 0 | 1): void {
        const ctx = this.contextMenu();
        if (!ctx) return;
        const currentRows = this.rowData();
        const insertAt = ctx.rowIndex + offset;
        const newRow = this.createNewRow(insertAt);
        const updated = [...currentRows.slice(0, insertAt), newRow, ...currentRows.slice(insertAt)].map((r, i) => ({
            ...r,
            order: i + 1,
        }));
        this.rowData.set(updated);
        this.emitChanges(updated);
        this.contextMenu.set(null);
    }

    deleteRow(rowIndex: number): void {
        const currentRows = this.rowData();
        const updatedRows = currentRows
            .filter((_, index) => index !== rowIndex)
            .map((r, i) => ({ ...r, order: i + 1 }));
        this.rowData.set(updatedRows);
        this.emitChanges(updatedRows);
    }

    public groupSelectedRows(): void {
        const nodes = this.gridApi?.getSelectedNodes() ?? [];
        if (nodes.length === 0) return;
        if (!nodes.every((n: IRowNode) => !(n.data as ConditionGroup | undefined)?.section)) return;
        const sectionId = crypto.randomUUID();
        const namesToGroup = new Set(nodes.map((n: IRowNode) => (n.data as ConditionGroup).group_name));
        const updated = this.rowData().map((row) =>
            namesToGroup.has(row.group_name) ? { ...row, section: sectionId } : row
        );
        this.rowData.set(updated);
        const collapsed = new Set(this.collapsedGroups());
        collapsed.add(sectionId);
        this.collapsedGroups.set(collapsed);
        this.gridApi?.deselectAll();
        this.emitChanges(updated);
        queueMicrotask(() => this.recomputeGroupOverlays());
    }

    public deleteSelectedRows(): void {
        const nodes = this.gridApi?.getSelectedNodes() ?? [];
        if (nodes.length === 0) return;
        const namesToDelete = new Set(nodes.map((n: IRowNode) => (n.data as ConditionGroup).group_name));
        const filtered = this.rowData()
            .filter((g) => !namesToDelete.has(g.group_name))
            .map((r, i) => ({ ...r, order: i + 1 }));
        this.gridApi?.deselectAll();
        this.rowData.set(filtered);
        this.emitChanges(filtered);
        this.recomputeGroupOverlays();
    }

    private openGroupMenu(sectionId: string, anchor: HTMLElement): void {
        if (this.groupMenuOverlayRef?.hasAttached()) {
            this.groupMenuOverlayRef.detach();
            this.groupMenuOverlayRef.dispose();
            this.groupMenuOverlayRef = null;
            if (this.groupMenuSectionId() === sectionId) {
                this.groupMenuSectionId.set(null);
                return;
            }
        }
        this.groupMenuSectionId.set(sectionId);

        const positionStrategy = this.overlay
            .position()
            .flexibleConnectedTo(anchor)
            .withPositions([
                { originX: 'end', originY: 'bottom', overlayX: 'start', overlayY: 'top', offsetY: 4 },
                { originX: 'end', originY: 'top', overlayX: 'start', overlayY: 'bottom', offsetY: -4 },
            ])
            .withPush(false);

        this.groupMenuOverlayRef = this.overlay.create({
            positionStrategy,
            hasBackdrop: true,
            backdropClass: 'cdk-overlay-transparent-backdrop',
            scrollStrategy: this.overlay.scrollStrategies.close(),
        });

        this.groupMenuOverlayRef.backdropClick().subscribe(() => {
            this.groupMenuOverlayRef?.detach();
            this.groupMenuOverlayRef?.dispose();
            this.groupMenuOverlayRef = null;
            this.groupMenuSectionId.set(null);
        });

        const portal = new TemplatePortal(this.groupMenuTemplate, this.vcr);
        this.groupMenuOverlayRef.attach(portal);
    }

    public handleGroupMenuUngroup(): void {
        const sectionId = this.groupMenuSectionId();
        this.groupMenuOverlayRef?.detach();
        this.groupMenuOverlayRef?.dispose();
        this.groupMenuOverlayRef = null;
        this.groupMenuSectionId.set(null);
        if (!sectionId) return;
        this.confirmDialog
            .confirm({
                title: 'Ungroup these rows?',
                message: 'Are you sure you want to ungroup these rows?',
                confirmText: 'Ungroup',
                cancelText: 'Cancel',
                type: 'warning',
                isShownBorder: true,
            })
            .subscribe((result) => {
                if (result === true) {
                    const updated = this.rowData().map((row) =>
                        row.section === sectionId ? { ...row, section: null } : row
                    );
                    const newCollapsed = new Set(this.collapsedGroups());
                    newCollapsed.delete(sectionId);
                    this.collapsedGroups.set(newCollapsed);
                    this.rowData.set(updated);
                    this.emitChanges(updated);
                    queueMicrotask(() => this.recomputeGroupOverlays());
                }
            });
    }

    public handleGroupMenuCollapse(): void {
        const sectionId = this.groupMenuSectionId();
        this.groupMenuOverlayRef?.detach();
        this.groupMenuOverlayRef?.dispose();
        this.groupMenuOverlayRef = null;
        this.groupMenuSectionId.set(null);
        if (!sectionId) return;
        const newCollapsed = new Set(this.collapsedGroups());
        newCollapsed.add(sectionId);
        this.collapsedGroups.set(newCollapsed);
        queueMicrotask(() => this.recomputeGroupOverlays());
    }

    public handleGroupMenuExpand(): void {
        const sectionId = this.groupMenuSectionId();
        this.groupMenuOverlayRef?.detach();
        this.groupMenuOverlayRef?.dispose();
        this.groupMenuOverlayRef = null;
        this.groupMenuSectionId.set(null);
        if (!sectionId) return;
        const next = new Set(this.collapsedGroups());
        next.delete(sectionId);
        this.collapsedGroups.set(next);
        queueMicrotask(() => this.recomputeGroupOverlays());
    }

    public handleGroupMenuExpandAll(): void {
        this.groupMenuOverlayRef?.detach();
        this.groupMenuOverlayRef?.dispose();
        this.groupMenuOverlayRef = null;
        this.groupMenuSectionId.set(null);
        this.collapsedGroups.set(new Set());
        queueMicrotask(() => this.recomputeGroupOverlays());
    }

    public handleGroupMenuCollapseAll(): void {
        this.groupMenuOverlayRef?.detach();
        this.groupMenuOverlayRef?.dispose();
        this.groupMenuOverlayRef = null;
        this.groupMenuSectionId.set(null);
        const allSections = new Set<string>();
        for (const row of this.rowData()) {
            if (row.section) allSections.add(row.section);
        }
        this.collapsedGroups.set(allSections);
        queueMicrotask(() => this.recomputeGroupOverlays());
    }

    private getUpdatedRows(): ConditionGroup[] {
        return this.rowData().map((row, index) => ({ ...row, order: index + 1 }));
    }

    private emitChanges(rows: ConditionGroup[]): void {
        this.conditionGroupsChange.emit(rows);
        this.cdr.markForCheck();
    }

    public handleManualRowReorder(source: IRowNode, over: IRowNode, insertBefore: boolean = true): void {
        if (!source || !over || source === over) return;
        const rows = this.rowData();
        const sourceIdx = rows.indexOf(source.data);
        const overIdx = rows.indexOf(over.data);
        if (sourceIdx === -1 || overIdx === -1) return;

        const original: string | null = (source.data as ConditionGroup).section ?? null;

        const next = [...rows];
        const [moved] = next.splice(sourceIdx, 1);
        let insertIdx = overIdx > sourceIdx ? overIdx - 1 : overIdx;
        if (!insertBefore) insertIdx += 1;
        next.splice(insertIdx, 0, moved);
        const prev = next[insertIdx - 1];
        const after = next[insertIdx + 1];
        const prevSection: string | null = prev?.section ?? null;
        const afterSection: string | null = after?.section ?? null;
        let movedSection: string | null;
        if (prevSection != null && prevSection === afterSection) {
            // Dropped strictly between two rows of the same group → join that group.
            movedSection = prevSection;
        } else if (original != null && (prevSection === original || afterSection === original)) {
            // Reordering within the row's OWN group and landing at the group's edge
            movedSection = original;
        } else {
            movedSection = null;
        }

        const isCrossGroup = original != null && movedSection != null && original !== movedSection;

        const commit = (): void => {
            next[insertIdx] = { ...moved, section: movedSection };
            const ordered = next.map((r, i) => ({ ...r, order: i + 1 }));
            this.rowData.set(ordered);
            this.emitChanges(ordered);
            queueMicrotask(() => this.recomputeGroupOverlays());
        };

        if (isCrossGroup) {
            this.confirmDialog
                .confirm({
                    title: 'Move row between groups?',
                    message: 'Are you sure you want to move this row?',
                    confirmText: 'Move Row',
                    cancelText: 'Cancel',
                    type: 'warning',
                    isShownBorder: true,
                })
                .subscribe((result) => {
                    if (result === true) commit();
                });
        } else {
            commit();
        }
    }
}
