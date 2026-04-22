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
    signal,
} from '@angular/core';
import { AgGridModule } from 'ag-grid-angular';
import {
    CellClickedEvent,
    CellValueChangedEvent,
    ColDef,
    ColGroupDef,
    ColumnMovedEvent,
    ColumnResizedEvent,
    GridApi,
    GridOptions,
    GridReadyEvent,
    RowSpanParams,
    ValueGetterParams,
    ValueSetterParams,
} from 'ag-grid-community';
import { AllCommunityModule, ModuleRegistry } from 'ag-grid-community';
import { themeQuartz } from 'ag-grid-community';

import { ButtonComponent } from '../../../../../shared/components/buttons/button/button.component';
import { NodeType } from '../../../../core/enums/node-type';
import { PromptConfig } from '../../../../core/models/classification-decision-table.model';
import { ConditionGroup } from '../../../../core/models/decision-table.model';
import { NodeModel } from '../../../../core/models/node.model';
import { FlowService } from '../../../../services/flow.service';
import { IconHeaderComponent } from './icon-header/icon-header.component';
import { MonacoCellRendererComponent } from './monaco-cell-renderer/monaco-cell-renderer.component';
import { NextNodeCellEditorComponent } from './next-node-cell-editor/next-node-cell-editor.component';
import { ParamsGroupHeaderComponent } from './params-group-header/params-group-header.component';
import { PromptIdCellEditorComponent } from './prompt-id-cell-editor/prompt-id-cell-editor.component';
import { PromptTooltipRendererComponent } from './prompt-tooltip-renderer/prompt-tooltip-renderer.component';

ModuleRegistry.registerModules([AllCommunityModule]);

@Component({
    selector: 'app-classification-decision-table-grid',
    imports: [AgGridModule, ButtonComponent],
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

    private flowService = inject(FlowService);
    private cdr = inject(ChangeDetectorRef);
    private elRef = inject(ElementRef);

    private gridApi!: GridApi;
    private fieldColumnsInitialized = false;
    public rowData = signal<ConditionGroup[]>([]);
    public showFieldColumnPicker = signal(false);
    public fieldSearchQuery = signal('');
    public fieldPickerPos = signal<{ x: number; y: number } | null>(null);
    public showManipFieldPicker = signal(false);
    public manipFieldSearchQuery = signal('');
    public manipPickerPos = signal<{ x: number; y: number } | null>(null);
    public contextMenu = signal<{ x: number; y: number; rowIndex: number } | null>(null);

    // Ordered list of ALL movable colIds (field_* and expression), including hidden
    private movableColumnOrder = signal<string[]>(['expression']);
    // Which field names are currently hidden
    private hiddenFieldsSet = signal<Set<string>>(new Set());

    // Manipulation field columns (manip_* and manipulation)
    private manipColumnOrder = signal<string[]>(['manipulation']);
    private hiddenManipFieldsSet = signal<Set<string>>(new Set());

    // Computed: visible field names in their column order
    public activeFieldColumns = computed(() => {
        const hidden = this.hiddenFieldsSet();
        return this.movableColumnOrder()
            .filter((id) => id.startsWith('field_') && !hidden.has(id.substring(6)))
            .map((id) => id.substring(6));
    });

    public isEmpty = computed(() => this.rowData().length === 0);

    public availableInputMapFields = computed(() => {
        const active = new Set(this.activeFieldColumns());
        const q = this.fieldSearchQuery().toLowerCase();
        return this.preInputMapKeys().filter((k) => !active.has(k) && (!q || k.toLowerCase().includes(q)));
    });

    public availableDomainFields = computed(() => {
        const active = new Set(this.activeFieldColumns());
        const inputMapKeys = new Set(this.preInputMapKeys());
        const q = this.fieldSearchQuery().toLowerCase();
        return this.domainKeys().filter(
            (k) => !active.has(k) && !inputMapKeys.has(k) && (!q || k.toLowerCase().includes(q))
        );
    });

    public hiddenFieldColumns = computed(() => {
        const visible = new Set(this.activeFieldColumns());
        const q = this.fieldSearchQuery().toLowerCase();
        const hidden = new Set<string>();
        // Fields in movableColumnOrder that are hidden
        this.movableColumnOrder()
            .filter((id) => id.startsWith('field_'))
            .map((id) => id.substring(6))
            .forEach((name) => {
                if (!visible.has(name)) hidden.add(name);
            });
        // Also check row data for orphaned fields
        this.rowData().forEach((row) => {
            if (row.field_expressions) {
                Object.entries(row.field_expressions).forEach(([k, v]) => {
                    if (v && !visible.has(k)) hidden.add(k);
                });
            }
        });
        return [...hidden].filter((k) => !q || k.toLowerCase().includes(q));
    });

    public hasAvailableFields = computed(
        () =>
            this.availableInputMapFields().length > 0 ||
            this.availableDomainFields().length > 0 ||
            this.hiddenFieldColumns().length > 0
    );

    // Manipulation field computed properties
    public activeManipFieldColumns = computed(() => {
        const hidden = this.hiddenManipFieldsSet();
        return this.manipColumnOrder()
            .filter((id) => id.startsWith('manip_') && !hidden.has(id.substring(6)))
            .map((id) => id.substring(6));
    });

    public availableManipInputMapFields = computed(() => {
        const active = new Set(this.activeManipFieldColumns());
        const q = this.manipFieldSearchQuery().toLowerCase();
        return this.preInputMapKeys().filter((k) => !active.has(k) && (!q || k.toLowerCase().includes(q)));
    });

    public availableManipDomainFields = computed(() => {
        const active = new Set(this.activeManipFieldColumns());
        const inputMapKeys = new Set(this.preInputMapKeys());
        const q = this.manipFieldSearchQuery().toLowerCase();
        return this.domainKeys().filter(
            (k) => !active.has(k) && !inputMapKeys.has(k) && (!q || k.toLowerCase().includes(q))
        );
    });

    public hiddenManipFieldColumns = computed(() => {
        const visible = new Set(this.activeManipFieldColumns());
        const q = this.manipFieldSearchQuery().toLowerCase();
        const hidden = new Set<string>();
        this.manipColumnOrder()
            .filter((id) => id.startsWith('manip_'))
            .map((id) => id.substring(6))
            .forEach((name) => {
                if (!visible.has(name)) hidden.add(name);
            });
        this.rowData().forEach((row) => {
            if (row.field_manipulations) {
                Object.entries(row.field_manipulations).forEach(([k, v]) => {
                    if (v && !visible.has(k)) hidden.add(k);
                });
            }
        });
        return [...hidden].filter((k) => !q || k.toLowerCase().includes(q));
    });

    public hasAvailableManipFields = computed(
        () =>
            this.availableManipInputMapFields().length > 0 ||
            this.availableManipDomainFields().length > 0 ||
            this.hiddenManipFieldColumns().length > 0
    );

    public hasFieldCols = computed(() =>
        this.movableColumnOrder().some((id) => id.startsWith('field_') && !this.hiddenFieldsSet().has(id.substring(6)))
    );

    public hasManipCols = computed(() =>
        this.manipColumnOrder().some(
            (id) => id.startsWith('manip_') && !this.hiddenManipFieldsSet().has(id.substring(6))
        )
    );

    public showExprParamsMenu = signal(false);
    public exprParamsMenuPos = signal<{ x: number; y: number } | null>(null);
    public showManipParamsMenu = signal(false);
    public manipParamsMenuPos = signal<{ x: number; y: number } | null>(null);

    public exprAddPos = signal<{ x: number; y: number } | null>(null);
    public manipAddPos = signal<{ x: number; y: number } | null>(null);
    private positionResizeObserver: ResizeObserver | null = null;

    public availableNodes = computed(() => {
        const nodes = this.flowService.nodes();
        return nodes
            .filter((node: NodeModel) => node.type !== NodeType.NOTE && node.type !== NodeType.EDGE)
            .map((node: NodeModel) => ({
                label: node.node_name,
                value: node.id,
            }));
    });

    constructor() {
        effect(() => {
            const groups = this.conditionGroups();
            if (groups && groups.length > 0) {
                this.rowData.set([...groups]);
                if (!this.fieldColumnsInitialized) {
                    this.initFieldColumnsFromData(groups);
                    this.fieldColumnsInitialized = true;
                }
            }
        });
        effect(() => {
            this.prompts();
            if (this.gridApi) {
                this.gridApi.refreshCells({ columns: ['prompt_id'], force: true });
            }
        });
        effect(() => {
            this.movableColumnOrder();
            this.hiddenFieldsSet();
            this.manipColumnOrder();
            this.hiddenManipFieldsSet();
            this.rebuildColumnDefs();
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
            const colIds = ['expression', ...[...fieldKeys].map((f) => `field_${f}`)];
            this.movableColumnOrder.set(colIds);
        }
        if (manipKeys.size > 0 && this.manipColumnOrder().length <= 1) {
            const colIds = ['manipulation', ...[...manipKeys].map((f) => `manip_${f}`)];
            this.manipColumnOrder.set(colIds);
        }
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

    private unmergedGroup = signal<{ colId: string; startRow: number; endRow: number } | null>(null);
    private savedColumnWidths = new Map<string, number>();
    private saveTimeout: ReturnType<typeof setTimeout> | null = null;
    private isRebuilding = false;

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
                hidden: [...this.hiddenFieldsSet()],
                manipOrder: this.manipColumnOrder(),
                hiddenManip: [...this.hiddenManipFieldsSet()],
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
            if (state.hidden?.length > 0) {
                this.hiddenFieldsSet.set(new Set(state.hidden));
            }
            if (state.manipOrder?.length > 0) {
                this.manipColumnOrder.set(state.manipOrder);
            }
            if (state.hiddenManip?.length > 0) {
                this.hiddenManipFieldsSet.set(new Set(state.hiddenManip));
            }
        } catch {}
    }

    public gridOptions: GridOptions = {
        theme: this.myTheme,
        rowHeight: 50,
        headerHeight: 45,
        suppressRowTransform: true,
        suppressCellFocus: false,
        singleClickEdit: true,
        stopEditingWhenCellsLoseFocus: true,
        domLayout: 'autoHeight',
        rowDragManaged: true,
        animateRows: true,
        onRowDragEnd: () => {
            const updatedRows = this.getUpdatedRows();
            this.emitChanges(updatedRows);
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
        onColumnMoved: (event: ColumnMovedEvent) => {
            if (this.isRebuilding) return;
            if (!event.finished) return;
            const colState = this.gridApi?.getColumnState();
            if (!colState) return;
            const allVisible = colState.map((s) => s.colId!);

            // Update expression column order
            const exprVisible = allVisible.filter((id) => id?.startsWith('field_') || id === 'expression');
            const oldExprOrder = this.movableColumnOrder();
            const hiddenExpr = this.hiddenFieldsSet();
            const hiddenExprIds = oldExprOrder.filter(
                (id) => id.startsWith('field_') && hiddenExpr.has(id.substring(6))
            );
            const exprResult = [...exprVisible];
            for (const hid of hiddenExprIds) {
                const oldIdx = oldExprOrder.indexOf(hid);
                let insertAfter = -1;
                for (let i = oldIdx - 1; i >= 0; i--) {
                    const pos = exprResult.indexOf(oldExprOrder[i]);
                    if (pos >= 0) {
                        insertAfter = pos;
                        break;
                    }
                }
                exprResult.splice(insertAfter + 1, 0, hid);
            }
            this.movableColumnOrder.set(exprResult);

            // Update manipulation column order
            const manipVisible = allVisible.filter((id) => id?.startsWith('manip_') || id === 'manipulation');
            const oldManipOrder = this.manipColumnOrder();
            const hiddenManip = this.hiddenManipFieldsSet();
            const hiddenManipIds = oldManipOrder.filter(
                (id) => id.startsWith('manip_') && hiddenManip.has(id.substring(6))
            );
            const manipResult = [...manipVisible];
            for (const hid of hiddenManipIds) {
                const oldIdx = oldManipOrder.indexOf(hid);
                let insertAfter = -1;
                for (let i = oldIdx - 1; i >= 0; i--) {
                    const pos = manipResult.indexOf(oldManipOrder[i]);
                    if (pos >= 0) {
                        insertAfter = pos;
                        break;
                    }
                }
                manipResult.splice(insertAfter + 1, 0, hid);
            }
            this.manipColumnOrder.set(manipResult);
            this.saveGridState();
        },
        onColumnResized: (event: ColumnResizedEvent) => {
            if (event.finished) {
                this.saveGridState();
                setTimeout(() => this.updateAddButtonPositions(), 0);
            }
        },
    };

    public columnDefs: (ColDef | ColGroupDef)[] = this.buildColumnDefs();

    private buildFieldColDef(fieldName: string): ColDef {
        return {
            colId: `field_${fieldName}`,
            headerComponent: IconHeaderComponent,
            headerComponentParams: {
                label: fieldName,
                iconClass: 'ti ti-x',
                tooltip: `Remove variable "${fieldName}"`,
                variant: 'delete',
                onIconClick: () => this.removeFieldColumn(fieldName),
            },
            editable: false,
            minWidth: Math.max(70, fieldName.length * 9 + 52),
            flex: 1,
            cellRenderer: MonacoCellRendererComponent,
            cellRendererParams: { singleLine: true },
            rowSpan: (params: RowSpanParams<ConditionGroup>) =>
                this.getRowSpan(params, `field_${fieldName}`, (d) => d?.field_expressions?.[fieldName] || ''),
            cellStyle: (params: RowSpanParams<ConditionGroup>) =>
                this.getSpanCellStyle(params, `field_${fieldName}`, (d) => d?.field_expressions?.[fieldName] || '', {
                    fontSize: '13px',
                    fontFamily: 'monospace',
                    color: '#d4d4d4',
                }),
            valueGetter: (params: ValueGetterParams<ConditionGroup>) => {
                return params.data?.field_expressions?.[fieldName] || '';
            },
            valueSetter: (params: ValueSetterParams<ConditionGroup>) => {
                if (!params.data.field_expressions) {
                    params.data.field_expressions = {};
                }
                params.data.field_expressions[fieldName] = params.newValue || '';
                return true;
            },
        };
    }

    private buildManipFieldColDef(fieldName: string): ColDef {
        return {
            colId: `manip_${fieldName}`,
            headerComponent: IconHeaderComponent,
            headerComponentParams: {
                label: fieldName,
                iconClass: 'ti ti-x',
                tooltip: `Remove variable "${fieldName}"`,
                variant: 'delete',
                onIconClick: () => this.removeManipFieldColumn(fieldName),
            },
            editable: false,
            minWidth: Math.max(70, fieldName.length * 9 + 52),
            flex: 1,
            cellRenderer: MonacoCellRendererComponent,
            cellRendererParams: { singleLine: true },
            cellStyle: { fontSize: '13px', fontFamily: 'monospace', color: '#d4d4d4' },
            valueGetter: (params: ValueGetterParams<ConditionGroup>) => {
                return params.data?.field_manipulations?.[fieldName] || '';
            },
            valueSetter: (params: ValueSetterParams<ConditionGroup>) => {
                if (!params.data.field_manipulations) {
                    params.data.field_manipulations = {};
                }
                params.data.field_manipulations[fieldName] = params.newValue || '';
                return true;
            },
        };
    }

    private buildManipulationColDef(): ColDef {
        return {
            colId: 'manipulation',
            field: 'manipulation',
            headerName: 'Manipulation',
            editable: false,
            flex: 1,
            cellRenderer: MonacoCellRendererComponent,
            cellStyle: { fontSize: '13px', fontFamily: 'monospace', color: '#d4d4d4' },
            valueSetter: (params: ValueSetterParams<ConditionGroup>) => {
                params.data.manipulation = params.newValue || '';
                return true;
            },
        };
    }

    private buildExpressionColDef(): ColDef {
        return {
            colId: 'expression',
            field: 'expression',
            headerName: 'Expression',
            editable: false,
            flex: 1,
            cellRenderer: MonacoCellRendererComponent,
            rowSpan: (params: RowSpanParams<ConditionGroup>) =>
                this.getRowSpan(params, 'expression', (d) => d?.expression || ''),
            cellStyle: (params: RowSpanParams<ConditionGroup>) =>
                this.getSpanCellStyle(params, 'expression', (d) => d?.expression || '', {
                    fontSize: '13px',
                    fontFamily: 'monospace',
                    color: '#d4d4d4',
                }),
            valueSetter: (params: ValueSetterParams<ConditionGroup>) => {
                params.data.expression = params.newValue || '';
                return true;
            },
        };
    }

    private buildColumnDefs(): (ColDef | ColGroupDef)[] {
        const staticBefore: ColDef[] = [
            {
                headerName: 'Enabled',
                field: 'dock_visible',
                editable: true,
                width: 85,
                minWidth: 75,
                rowDrag: true,
                cellDataType: 'boolean',
                headerTooltip: 'Enabled',
                suppressMovable: true,
                cellStyle: {
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                },
            },
            {
                headerName: 'Condition Name',
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
        const hidden = this.hiddenFieldsSet();
        const visibleFieldCols: ColDef[] = this.movableColumnOrder()
            .filter((id) => id.startsWith('field_') && !hidden.has(id.substring(6)))
            .map((id) => this.buildFieldColDef(id.substring(6)));

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
                        onChevronClick: (event: MouseEvent) => this.openExprParamsMenu(event),
                    },
                    children: visibleFieldCols,
                } as ColGroupDef,
            ];
        } else {
            exprSection = [expressionCol];
        }

        const promptIdCol: ColDef = {
            headerName: 'Prompt ID',
            field: 'prompt_id',
            suppressMovable: true,
            editable: true,
            width: 150,
            cellRenderer: PromptTooltipRendererComponent,
            cellRendererParams: () => ({
                prompts: this.prompts(),
                onPromptChange: (
                    promptId: string,
                    field: keyof PromptConfig,
                    value: PromptConfig[keyof PromptConfig]
                ) => {
                    this.promptChange.emit({ promptId, field, value });
                },
            }),
            cellEditor: PromptIdCellEditorComponent,
            cellEditorParams: () => ({
                prompts: this.prompts(),
                defaultLlmId: this.defaultLlmId(),
                llmConfigs: this.llmConfigs(),
                onAddPrompt: (id: string, config: PromptConfig) => {
                    this.promptAdd.emit({ id, config });
                },
                onPromptChange: (
                    promptId: string,
                    field: keyof PromptConfig,
                    value: PromptConfig[keyof PromptConfig]
                ) => {
                    this.promptChange.emit({ promptId, field, value });
                },
            }),
            cellEditorPopup: false,
            cellStyle: {
                fontSize: '14px',
            },
        };

        // Manipulation section
        const hiddenManip = this.hiddenManipFieldsSet();
        const visibleManipCols: ColDef[] = this.manipColumnOrder()
            .filter((id) => id.startsWith('manip_') && !hiddenManip.has(id.substring(6)))
            .map((id) => this.buildManipFieldColDef(id.substring(6)));

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
                        onChevronClick: (event: MouseEvent) => this.openManipParamsMenu(event),
                    },
                    children: visibleManipCols,
                } as ColGroupDef,
            ];
        } else {
            manipSection = [manipCol];
        }

        // TEMP: route_code column disabled
        // const routeCodeCol: ColDef = {
        //     headerName: 'Route Code',
        //     field: 'route_code',
        //     editable: true,
        //     width: 150,
        //     suppressMovable: true,
        //     cellStyle: {
        //         fontSize: '14px',
        //     },
        // };

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

        const nextNodeCol: ColDef = {
            headerName: 'Next Node',
            field: 'next_node',
            suppressMovable: true,
            editable: true,
            flex: 1,
            minWidth: 140,
            cellRenderer: (params: { value: string }) => {
                const nodeId = params.value;
                if (!nodeId) return '<span style="color: rgba(255,255,255,0.35); font-size:13px;">Select node</span>';
                const node = this.availableNodes().find((n) => n.value === nodeId);
                return node
                    ? `<span style="font-size:13px;">${node.label}</span>`
                    : '<span style="color: rgba(255,255,255,0.35); font-size:13px;">Select node</span>';
            },
            cellEditor: NextNodeCellEditorComponent,
            cellEditorParams: () => ({
                nodes: this.availableNodes(),
            }),
            cellEditorPopup: false,
            cellStyle: {
                display: 'flex',
                alignItems: 'center',
                cursor: 'pointer',
            },
        };

        const deleteCol: ColDef = {
            headerName: '',
            headerComponent: IconHeaderComponent,
            headerComponentParams: {
                iconClass: 'ti ti-trash',
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

        // TEMP: route_code column disabled — routeCodeCol removed from layout
        // return [...staticBefore, ...exprSection, promptIdCol, ...manipSection, routeCodeCol, skipCol, nextNodeCol, deleteCol];
        return [...staticBefore, ...exprSection, promptIdCol, ...manipSection, skipCol, nextNodeCol, deleteCol];
    }

    private getMergeableColIds(): string[] {
        return [...this.activeFieldColumns().map((f) => `field_${f}`), 'expression'];
    }

    // Returns the row range that column `colId` is allowed to merge within,
    // based on the left column's merge group hierarchy.
    private getHierarchicalBounds(
        params: RowSpanParams<ConditionGroup>,
        colId: string,
        idx: number
    ): { start: number; end: number } {
        const mergeableCols = this.getMergeableColIds();
        const colIndex = mergeableCols.indexOf(colId);

        if (colIndex <= 0) {
            // First column or not found — full table range
            return { start: 0, end: (params.api?.getDisplayedRowCount?.() ?? 1000) - 1 };
        }

        const leftColId = mergeableCols[colIndex - 1];
        // Recursively get the left column's own bounds
        const leftBounds = this.getHierarchicalBounds(params, leftColId, idx);

        const leftVal = this.getMergeableValueFromData(params.api?.getDisplayedRowAtIndex(idx)?.data, leftColId);

        let start = idx;
        while (start > leftBounds.start) {
            const prev = params.api?.getDisplayedRowAtIndex(start - 1);
            if (!prev || this.getMergeableValueFromData(prev.data, leftColId) !== leftVal) break;
            start--;
        }
        let end = idx;
        while (end < leftBounds.end) {
            const next = params.api?.getDisplayedRowAtIndex(end + 1);
            if (!next || this.getMergeableValueFromData(next.data, leftColId) !== leftVal) break;
            end++;
        }
        return { start, end };
    }

    private getRowSpan(
        params: RowSpanParams<ConditionGroup>,
        colId: string,
        getValue: (data: ConditionGroup | undefined) => string
    ): number {
        const idx = params.node?.rowIndex ?? 0;
        const ug = this.unmergedGroup();
        if (ug && ug.colId === colId && idx >= ug.startRow && idx <= ug.endRow) return 1;
        const cur = getValue(params.data) || '';
        if (!cur) return 1;

        const bounds = this.getHierarchicalBounds(params, colId, idx);

        // If this cell matches the one above (within bounds), AG Grid hides it behind the span above
        if (idx > bounds.start) {
            const prevNode = params.api?.getDisplayedRowAtIndex(idx - 1);
            if (prevNode && cur === (getValue(prevNode.data) || '')) {
                return 1;
            }
        }
        // Count consecutive matching rows below, bounded by hierarchy
        let span = 1;
        while (idx + span <= bounds.end) {
            const nextNode = params.api?.getDisplayedRowAtIndex(idx + span);
            if (!nextNode || cur !== (getValue(nextNode.data) || '')) break;
            span++;
        }
        return span;
    }

    private isCellMerged(params: RowSpanParams<ConditionGroup>, colId: string, idx: number): boolean {
        const ug = this.unmergedGroup();
        if (ug && ug.colId === colId && idx >= ug.startRow && idx <= ug.endRow) return false;
        const val = this.getMergeableValue(params, colId);

        const bounds = this.getHierarchicalBounds(params, colId, idx);
        const prevNode = idx > bounds.start ? params.api?.getDisplayedRowAtIndex(idx - 1) : null;
        const nextNode = idx < bounds.end ? params.api?.getDisplayedRowAtIndex(idx + 1) : null;
        return (
            !!(prevNode && val === this.getMergeableValueFromData(prevNode.data, colId)) ||
            !!(nextNode && val === this.getMergeableValueFromData(nextNode.data, colId))
        );
    }

    private getMergeableValue(params: RowSpanParams<ConditionGroup>, colId: string): string {
        return this.getMergeableValueFromData(params.data, colId);
    }

    private getMergeableValueFromData(data: ConditionGroup | undefined, colId: string): string {
        if (!data) return '';
        if (colId === 'expression') return data.expression || '';
        if (colId.startsWith('field_')) {
            const field = colId.substring(6);
            return data.field_expressions?.[field] || '';
        }
        if (colId.startsWith('manip_')) {
            const field = colId.substring(6);
            return data.field_manipulations?.[field] || '';
        }
        return '';
    }

    private static hashStr(s: string): number {
        let h = 0;
        for (let i = 0; i < s.length; i++) {
            h = ((h << 5) - h + s.charCodeAt(i)) | 0;
        }
        return h;
    }

    // ── NEW COLORING SYSTEM ──
    // Leftmost column: evenly spaced hues per group (including empty groups).
    // Next columns: blend parent hue with own value's hash hue.
    // Empty cells: inherit left color, no own hue contribution.
    // Non-merged non-empty cells: no color; breaks chain for columns to the right.
    // Color lightens going right.

    private getColumnGroupInfo(
        params: RowSpanParams<ConditionGroup>,
        colId: string
    ): { groupIdx: number; totalGroups: number } {
        const totalRows = params.api?.getDisplayedRowCount?.() ?? 0;
        const idx = params.node?.rowIndex ?? 0;
        let groupIdx = 0;
        let totalGroups = 0;
        let prevVal: string | null = null;
        for (let r = 0; r < totalRows; r++) {
            const node = params.api?.getDisplayedRowAtIndex(r);
            const val = node ? this.getMergeableValueFromData(node.data, colId) : '';
            if (prevVal === null || val !== prevVal) {
                totalGroups++;
                if (r <= idx) groupIdx = totalGroups - 1;
            }
            prevVal = val;
        }
        return { groupIdx, totalGroups };
    }

    private computeCellBg(params: RowSpanParams<ConditionGroup>, colId: string, idx: number): string {
        const mergeableCols = this.getMergeableColIds();
        const colIndex = mergeableCols.indexOf(colId);
        if (colIndex < 0) return '';

        let hue = 0;
        let depth = 0;

        for (let i = 0; i <= colIndex; i++) {
            const col = mergeableCols[i];
            const val = this.getMergeableValue(params, col);
            const merged = this.isCellMerged(params, col, idx);

            // Non-merged non-empty cell: no color, breaks chain
            if (val !== '' && !merged) return '';

            if (i === 0) {
                // Leftmost column: evenly spaced hues for all groups (including empty)
                const info = this.getColumnGroupInfo(params, col);
                hue = info.totalGroups > 1 ? (info.groupIdx * 360) / info.totalGroups : 200; // single-group fallback
                depth++;
            } else if (val !== '') {
                // Non-leftmost with value: blend parent hue with value hash
                const valHash = ClassificationDecisionTableGridComponent.hashStr(val);
                const valHue = ((Math.abs(valHash) * 0.618033988749895) % 1) * 360;
                hue = hue * 0.6 + valHue * 0.4; // weighted blend toward parent
                depth++;
            }
            // Empty non-leftmost: just inherit (hue unchanged, depth unchanged)
        }

        // Lightens going right: saturation decreases, lightness increases
        const sat = Math.max(18 - depth * 2, 6);
        const lit = Math.min(13 + depth * 2, 22);
        return `hsl(${((hue % 360) + 360) % 360}, ${sat}%, ${lit}%)`;
    }

    private getSpanCellStyle(
        params: RowSpanParams<ConditionGroup>,
        colId: string,
        getValue: (data: ConditionGroup | undefined) => string,
        baseStyle: Record<string, string>
    ): Record<string, string> {
        const style: Record<string, string> = { ...baseStyle };
        const idx = params.node?.rowIndex ?? 0;
        const ug = this.unmergedGroup();
        if (ug && ug.colId === colId && idx >= ug.startRow && idx <= ug.endRow) return style;
        const cur = getValue(params.data) || '';

        const bounds = this.getHierarchicalBounds(params, colId, idx);
        const prevNode = idx > bounds.start ? params.api?.getDisplayedRowAtIndex(idx - 1) : null;
        const nextNode = idx < bounds.end ? params.api?.getDisplayedRowAtIndex(idx + 1) : null;
        const matchesAbove = prevNode ? cur === (getValue(prevNode.data) || '') : false;
        const matchesBelow = nextNode ? cur === (getValue(nextNode.data) || '') : false;
        const isMerged = matchesAbove || matchesBelow;

        // Compute background color
        const bg = this.computeCellBg(params, colId, idx);
        if (bg) {
            style['backgroundColor'] = bg;
        }

        // Merged cell layout
        if (isMerged) {
            style['display'] = 'flex';
            style['alignItems'] = 'center';
        }

        // Separator border at top of spanning cell (group boundary)
        // For empty cells: also add border when this is the first row of the hierarchical bounds
        // (group boundary even if the cell above is also empty but in a different parent group)
        const isGroupStart = !matchesAbove && matchesBelow;
        const isEmptyBoundsStart = cur === '' && isMerged && idx === bounds.start && idx > 0;
        if (isGroupStart || isEmptyBoundsStart) {
            style['borderTop'] = '2px solid rgba(255, 255, 255, 0.18)';
        }
        return style;
    }

    private findMergeGroup(colId: string, rowIndex: number): { startRow: number; endRow: number } {
        const rows = this.rowData();
        const getVal = (i: number): string => this.getMergeableValueFromData(rows[i], colId);

        const val = getVal(rowIndex);
        if (!val) return { startRow: rowIndex, endRow: rowIndex };

        // Respect hierarchical bounds from left columns
        const mergeableCols = this.getMergeableColIds();
        const colIdx = mergeableCols.indexOf(colId);
        let boundsStart = 0;
        let boundsEnd = rows.length - 1;

        if (colIdx > 0) {
            const leftColId = mergeableCols[colIdx - 1];
            const leftGroup = this.findMergeGroup(leftColId, rowIndex);
            boundsStart = leftGroup.startRow;
            boundsEnd = leftGroup.endRow;
        }

        let start = rowIndex;
        while (start > boundsStart && getVal(start - 1) === val) start--;
        let end = rowIndex;
        while (end < boundsEnd && getVal(end + 1) === val) end++;
        return { startRow: start, endRow: end };
    }

    hideAllExprParams(): void {
        const allFieldNames = this.movableColumnOrder()
            .filter((id) => id.startsWith('field_'))
            .map((id) => id.substring(6));
        const newHidden = new Set(this.hiddenFieldsSet());
        allFieldNames.forEach((name) => newHidden.add(name));
        this.hiddenFieldsSet.set(newHidden);
        this.saveGridState();
    }

    hideAllManipParams(): void {
        const allManipNames = this.manipColumnOrder()
            .filter((id) => id.startsWith('manip_'))
            .map((id) => id.substring(6));
        const newHidden = new Set(this.hiddenManipFieldsSet());
        allManipNames.forEach((name) => newHidden.add(name));
        this.hiddenManipFieldsSet.set(newHidden);
        this.saveGridState();
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
        }
        setTimeout(() => this.updateAddButtonPositions(), 50);
    }

    private updateAddButtonPositions(): void {
        if (this.hasFieldCols()) {
            this.exprAddPos.set(null);
        } else {
            const exprCell = this.elRef.nativeElement.querySelector('.ag-header-cell[col-id="expression"]');
            if (exprCell) {
                const rect = (exprCell as HTMLElement).getBoundingClientRect();
                this.exprAddPos.set({ x: rect.right - 26, y: rect.top + rect.height / 2 - 10 });
            }
        }

        if (this.hasManipCols()) {
            this.manipAddPos.set(null);
        } else {
            const manipCell = this.elRef.nativeElement.querySelector('.ag-header-cell[col-id="manipulation"]');
            if (manipCell) {
                const rect = (manipCell as HTMLElement).getBoundingClientRect();
                this.manipAddPos.set({ x: rect.right - 26, y: rect.top + rect.height / 2 - 10 });
            }
        }
    }

    toggleFieldPicker(event?: MouseEvent): void {
        const isOpen = this.showFieldColumnPicker();
        if (!isOpen && event) {
            const rect = (event.target as HTMLElement).getBoundingClientRect();
            this.fieldPickerPos.set({ x: rect.left, y: rect.bottom + 4 });
        }
        this.showFieldColumnPicker.set(!isOpen);
        if (isOpen) {
            this.fieldSearchQuery.set('');
        }
    }

    addFieldColumn(fieldName: string): void {
        const hidden = this.hiddenFieldsSet();
        if (hidden.has(fieldName)) {
            // Unhide - position preserved in movableColumnOrder
            const newHidden = new Set(hidden);
            newHidden.delete(fieldName);
            this.hiddenFieldsSet.set(newHidden);
        } else {
            // New field - append to end of movableColumnOrder
            const colId = `field_${fieldName}`;
            const order = this.movableColumnOrder();
            if (!order.includes(colId)) {
                const newOrder = [...order, colId];
                this.movableColumnOrder.set(newOrder);
            }
        }
        this.showFieldColumnPicker.set(false);
        this.fieldSearchQuery.set('');
        this.saveGridState();
    }

    removeFieldColumn(fieldName: string): void {
        const hasData = this.rowData().some((row) => row.field_expressions && !!row.field_expressions[fieldName]);
        if (hasData) {
            const newHidden = new Set(this.hiddenFieldsSet());
            newHidden.add(fieldName);
            this.hiddenFieldsSet.set(newHidden);
        } else {
            const colId = `field_${fieldName}`;
            this.movableColumnOrder.set(this.movableColumnOrder().filter((id) => id !== colId));
        }
        this.saveGridState();
    }

    toggleManipFieldPicker(event?: MouseEvent): void {
        const isOpen = this.showManipFieldPicker();
        if (!isOpen && event) {
            const rect = (event.target as HTMLElement).getBoundingClientRect();
            this.manipPickerPos.set({ x: rect.left, y: rect.bottom + 4 });
        }
        this.showManipFieldPicker.set(!isOpen);
        if (isOpen) {
            this.manipFieldSearchQuery.set('');
        }
    }

    openExprParamsMenu(event: MouseEvent): void {
        const isOpen = this.showExprParamsMenu();
        if (!isOpen) {
            const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
            this.exprParamsMenuPos.set({ x: rect.left, y: rect.bottom + 4 });
        } else {
            this.exprParamsMenuPos.set(null);
        }
        this.showExprParamsMenu.set(!isOpen);
        this.showManipParamsMenu.set(false);
    }

    openManipParamsMenu(event: MouseEvent): void {
        const isOpen = this.showManipParamsMenu();
        if (!isOpen) {
            const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
            this.manipParamsMenuPos.set({ x: rect.left, y: rect.bottom + 4 });
        } else {
            this.manipParamsMenuPos.set(null);
        }
        this.showManipParamsMenu.set(!isOpen);
        this.showExprParamsMenu.set(false);
    }

    freezeExprParams(): void {
        this.saveGridState();
        this.showExprParamsMenu.set(false);
        this.exprParamsMenuPos.set(null);
    }

    hideExprParams(): void {
        this.hideAllExprParams();
        this.showExprParamsMenu.set(false);
        this.exprParamsMenuPos.set(null);
    }

    freezeManipParams(): void {
        this.saveGridState();
        this.showManipParamsMenu.set(false);
        this.manipParamsMenuPos.set(null);
    }

    hideManipParams(): void {
        this.hideAllManipParams();
        this.showManipParamsMenu.set(false);
        this.manipParamsMenuPos.set(null);
    }

    addManipFieldColumn(fieldName: string): void {
        const hidden = this.hiddenManipFieldsSet();
        if (hidden.has(fieldName)) {
            const newHidden = new Set(hidden);
            newHidden.delete(fieldName);
            this.hiddenManipFieldsSet.set(newHidden);
        } else {
            const colId = `manip_${fieldName}`;
            const order = this.manipColumnOrder();
            if (!order.includes(colId)) {
                const newOrder = [...order, colId];
                this.manipColumnOrder.set(newOrder);
            }
        }
        this.showManipFieldPicker.set(false);
        this.manipFieldSearchQuery.set('');
        this.saveGridState();
    }

    removeManipFieldColumn(fieldName: string): void {
        const hasData = this.rowData().some((row) => row.field_manipulations && !!row.field_manipulations[fieldName]);
        if (hasData) {
            const newHidden = new Set(this.hiddenManipFieldsSet());
            newHidden.add(fieldName);
            this.hiddenManipFieldsSet.set(newHidden);
        } else {
            const colId = `manip_${fieldName}`;
            this.manipColumnOrder.set(this.manipColumnOrder().filter((id) => id !== colId));
        }
        this.saveGridState();
    }

    onGridReady(params: GridReadyEvent): void {
        this.gridApi = params.api;
        this.setupBodyClickListener();
        // Apply saved column widths after grid is ready
        if (this.savedColumnWidths.size > 0) {
            const colState = this.gridApi.getColumnState().map((s) => {
                const saved = s.colId ? this.savedColumnWidths.get(s.colId) : undefined;
                return saved ? { ...s, width: saved } : s;
            });
            this.gridApi.applyColumnState({ state: colState });
        }
        setTimeout(() => this.updateAddButtonPositions(), 100);
        this.positionResizeObserver = new ResizeObserver(() => this.updateAddButtonPositions());
        this.positionResizeObserver.observe(this.elRef.nativeElement);
    }

    private bodyClickHandler = (event: MouseEvent) => {
        if (this.showExprParamsMenu()) {
            this.showExprParamsMenu.set(false);
            this.exprParamsMenuPos.set(null);
        }
        if (this.showManipParamsMenu()) {
            this.showManipParamsMenu.set(false);
            this.manipParamsMenuPos.set(null);
        }

        // Close context menu on any click
        if (this.contextMenu()) {
            this.contextMenu.set(null);
        }

        const currentUnmerged = this.unmergedGroup();
        const target = event.target as HTMLElement;

        // Don't act if clicking inside a Monaco tooltip popover, AG Grid header, or field controls
        if (target?.closest('.code-tooltip-popover')) return;
        if (target?.closest('.ag-header')) return;
        if (target?.closest('.field-column-controls')) return;

        // Check if the click landed on an AG Grid cell and extract its col-id
        const cellEl = target?.closest('[col-id]') as HTMLElement | null;
        const clickedColId = cellEl?.getAttribute('col-id') || null;

        if (clickedColId) {
            // Click is on a grid cell
            const isMergeableCol = clickedColId === 'expression' || clickedColId.startsWith('field_');

            if (isMergeableCol && (!currentUnmerged || currentUnmerged.colId !== clickedColId)) {
                // Only unmerge if the cell is actually spanning multiple rows
                const rowSpan = parseInt(cellEl!.getAttribute('rowspan') || '1', 10);
                if (rowSpan <= 1) return;

                // Determine which row was clicked within a spanned cell
                const rowHeight = this.gridOptions.rowHeight || 50;
                const cellRect = cellEl!.getBoundingClientRect();
                const rowOffset = Math.floor((event.clientY - cellRect.top) / rowHeight);
                const rowEl = cellEl!.closest('.ag-row');
                const topRowIndex = parseInt(rowEl?.getAttribute('row-index') || '0', 10);
                const targetRowIndex = topRowIndex + rowOffset;

                // Find merge group boundaries for this cell
                const groupRange = this.findMergeGroup(clickedColId, topRowIndex);

                // Unmerge only this group
                this.unmergedGroup.set({ colId: clickedColId, ...groupRange });
                this.rebuildColumnDefs();

                // After re-render, trigger editor on the target row's cell
                setTimeout(() => {
                    const targetCell = this.elRef.nativeElement.querySelector(
                        `.ag-row[row-index="${targetRowIndex}"] [col-id="${clickedColId}"] .code-cell`
                    );
                    if (targetCell) {
                        targetCell.click();
                    }
                }, 100);
            } else if (!isMergeableCol && currentUnmerged) {
                // Clicked a non-mergeable column → re-merge
                this.unmergedGroup.set(null);
                this.rebuildColumnDefs();
            }
        } else if (currentUnmerged) {
            // Click is outside any grid cell → re-merge
            this.unmergedGroup.set(null);
            this.rebuildColumnDefs();
        }
    };

    private setupBodyClickListener(): void {
        document.addEventListener('click', this.bodyClickHandler);
    }

    ngOnDestroy(): void {
        document.removeEventListener('click', this.bodyClickHandler);
        this.positionResizeObserver?.disconnect();
    }

    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    onCellValueChanged(_event: CellValueChangedEvent): void {
        this.unmergedGroup.set(null);
        const updatedRows = this.getUpdatedRows();
        this.emitChanges(updatedRows);
        this.rebuildColumnDefs();
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
            // TEMP: route_code disabled
            // route_code: `ROUTE_${index + 1}`,
            dock_visible: true,
            next_node: null,
            order: index + 1,
            field_expressions: fieldExpressions,
        };
    }

    addRow(): void {
        const currentRows = this.rowData();
        const newRow = this.createNewRow(currentRows.length);
        this.rowData.set([...currentRows, newRow]);
        this.emitChanges([...currentRows, newRow]);
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
        const updatedRows = currentRows.filter((_, index) => index !== rowIndex);
        this.rowData.set(updatedRows);
        this.emitChanges(updatedRows);
    }

    private getUpdatedRows(): ConditionGroup[] {
        const rows: ConditionGroup[] = [];
        this.gridApi.forEachNode((node) => {
            rows.push(node.data);
        });
        return rows.map((row, index) => ({ ...row, order: index + 1 }));
    }

    private emitChanges(rows: ConditionGroup[]): void {
        this.conditionGroupsChange.emit(rows);
        this.cdr.markForCheck();
    }
}
