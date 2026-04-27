import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    computed,
    effect,
    inject,
    input,
    OnInit,
    output,
    signal,
} from '@angular/core';
import { AgGridModule } from 'ag-grid-angular';
import {
    AllCommunityModule,
    CellClickedEvent,
    CellValueChangedEvent,
    ColDef,
    GridApi,
    GridOptions,
    GridReadyEvent,
    ModuleRegistry,
    themeQuartz,
} from 'ag-grid-community';

import { AppSvgIconComponent } from '../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { ButtonComponent } from '../../../../../shared/components/buttons/button/button.component';
import { NodeType } from '../../../../core/enums/node-type';
import { ConditionGroup } from '../../../../core/models/decision-table.model';
import { FlowService } from '../../../../services/flow.service';
import { ExpressionEditorComponent } from './cell-editors/expression-editor/expression-editor.component';
import { ExpressionRendererComponent } from './cell-renderers/expression-renderer/expression-renderer.component';

ModuleRegistry.registerModules([AllCommunityModule]);

@Component({
    selector: 'app-decision-table-grid',
    standalone: true,
    imports: [AgGridModule, ButtonComponent, AppSvgIconComponent],
    templateUrl: './decision-table-grid.component.html',
    styleUrls: ['./decision-table-grid.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DecisionTableGridComponent implements OnInit {
    public conditionGroups = input.required<ConditionGroup[]>();
    public activeColor = input<string>('#685fff');
    public currentNodeId = input.required<string>();

    public conditionGroupsChange = output<ConditionGroup[]>();

    private flowService = inject(FlowService);
    private cdr = inject(ChangeDetectorRef);

    private gridApi!: GridApi;
    public rowData = signal<ConditionGroup[]>([]);

    public isEmpty = computed(() => this.rowData().length === 0);

    public availableNodes = computed(() => {
        const nodes = this.flowService.nodes();
        const currentId = this.currentNodeId();

        return nodes
            .filter(
                (node) =>
                    node.type !== NodeType.NOTE &&
                    node.type !== NodeType.START &&
                    node.type !== NodeType.WEBHOOK_TRIGGER &&
                    node.type !== NodeType.TELEGRAM_TRIGGER &&
                    node.id !== currentId
            )
            .map((node) => ({
                value: node.id,
                label: node.node_name || node.id,
            }));
    });

    constructor() {
        effect(() => {
            const nodes = this.availableNodes();
            const refData: Record<string, string> = {};
            nodes.forEach((n) => {
                refData[n.value] = n.label;
            });

            if (this.gridApi) {
                const colDefs = this.gridApi.getColumnDefs();
                if (colDefs) {
                    const newColDefs = colDefs.map((col: ColDef) => {
                        if (col.field === 'next_node' || col.colId === 'next_node') {
                            return {
                                ...col,
                                refData,
                                cellEditorParams: {
                                    values: ['', ...nodes.map((n) => n.value)],
                                },
                            };
                        }
                        return col;
                    });
                    this.gridApi.setGridOption('columnDefs', newColDefs);
                }
            }
        });
    }

    ngOnInit(): void {
        const groups = this.conditionGroups();
        const nodes = this.flowService.nodes();
        const connections = this.flowService.connections();
        const currentNodeId = this.currentNodeId();

        const findNodeId = (value: string | null, groupName: string): string | null => {
            // 1. Try direct lookup
            if (value) {
                const foundNode = nodes.find((n) => n.id === value || n.node_name === value);
                if (foundNode) return foundNode.id;
                console.warn(`[DecisionTableGrid] Node not found for value: '${value}'`);
            }

            // 2. Fallback: Visual Connection lookup
            // Port ID: `${nodeId}_decision-out-${normalizedGroupName}`
            if (groupName) {
                const normalizedGroupName = groupName.toLowerCase().replace(/\s+/g, '-');
                const portId = `${currentNodeId}_decision-out-${normalizedGroupName}`;

                const connection = connections.find(
                    (c) => c.sourceNodeId === currentNodeId && c.sourcePortId === portId
                );

                if (connection) {
                    return connection.targetNodeId;
                }
            }

            return value;
        };

        if (groups.length === 0) {
            this.rowData.set([this.createEmptyGroup(0)]);
        } else {
            const normalizedGroups = [...groups]
                .sort((a, b) => (a.order ?? Number.MAX_SAFE_INTEGER) - (b.order ?? Number.MAX_SAFE_INTEGER))
                .map((group, index) => {
                    const trimmedName = group.group_name?.trim() ?? group.group_name;
                    const normalizedGroup = {
                        ...group,
                        group_name: trimmedName,
                        order: index + 1,
                        next_node: findNodeId(group.next_node, trimmedName),
                    };
                    this.updateGroupValidFlag(normalizedGroup, index);
                    return normalizedGroup;
                });
            this.rowData.set(normalizedGroups);
        }
    }

    private createEmptyGroup(index?: number): ConditionGroup {
        const position = index !== undefined ? index + 1 : this.rowData().length + 1;
        const uniqueName = this.resolveUniqueName(`Condition ${position}`, -1);
        return {
            group_name: uniqueName,
            group_type: 'complex',
            expression: null,
            conditions: [],
            manipulation: null,
            next_node: null,
            order: position,
            valid: false,
        };
    }

    public myTheme = themeQuartz.withParams({
        accentColor: '#685fff',
        backgroundColor: '#1e1e20',
        browserColorScheme: 'dark',
        borderColor: '#c8ceda24',
        chromeBackgroundColor: '#222225',
        columnBorder: true,
        foregroundColor: '#d9d9de',
        headerBackgroundColor: '#222225',
        headerFontSize: 16,
        headerFontWeight: 500,
        headerTextColor: '#d9d9de',
        cellTextColor: '#d9d9de',
        spacing: 3.3,
        oddRowBackgroundColor: '#222226',
    });

    public columnDefs: ColDef[] = [
        {
            colId: 'index',
            headerName: '#',
            valueGetter: 'node.rowIndex + 1',
            editable: false,
            width: 60,
            minWidth: 60,
            maxWidth: 60,
            cellStyle: {
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontWeight: '600',
                color: '#999',
            },
        },
        {
            headerName: 'Condition Name',
            field: 'group_name',
            editable: true,
            flex: 1,
            minWidth: 180,
            cellEditor: 'agLargeTextCellEditor',
            cellEditorParams: {
                maxLength: 255,
            },
            cellStyle: {
                fontSize: '14px',
            },
        },
        {
            headerName: 'Expression',
            field: 'expression',
            editable: true,
            flex: 1,
            minWidth: 200,
            cellEditor: ExpressionEditorComponent,
            cellEditorPopup: true,
            cellRenderer: ExpressionRendererComponent,
            cellStyle: {
                fontSize: '14px',
            },
        },
        {
            headerName: 'Manipulation',
            field: 'manipulation',
            editable: true,
            flex: 1,
            minWidth: 200,
            cellEditor: ExpressionEditorComponent,
            cellEditorPopup: true,
            cellEditorParams: { mode: 'manipulation' },
            cellRenderer: ExpressionRendererComponent,
            cellStyle: {
                fontSize: '14px',
            },
        },
        {
            headerName: 'Next Node',
            field: 'next_node',
            editable: true,
            width: 200,
            cellEditor: 'agSelectCellEditor',
            cellEditorParams: () => {
                const nodes = this.availableNodes();
                return {
                    values: ['', ...nodes.map((n) => n.value)],
                };
            },
            valueFormatter: (params) => {
                if (!params.value) return '';
                const nodes = this.availableNodes();
                const node = nodes.find((n) => n.value === params.value);
                return node ? node.label : params.value;
            },
            cellStyle: {
                fontSize: '14px',
            },
        },
        {
            headerName: '',
            field: 'actions',
            cellRenderer: () => {
                return `<i class="ti ti-trash" style="color: #ff3b30; font-size: 1.1rem; transition: all 0.2s ease; cursor: pointer;"></i>`;
            },
            width: 60,
            minWidth: 60,
            maxWidth: 60,
            cellStyle: {
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                cursor: 'pointer',
            },
            editable: false,
        },
    ];

    public defaultColDef: ColDef = {
        sortable: false,
        resizable: false,
        wrapText: true,
        suppressMovable: true,
    };

    public gridOptions: GridOptions = {
        rowHeight: 60,
        headerHeight: 50,
        theme: this.myTheme,
        animateRows: true,
        suppressColumnVirtualisation: false,
        stopEditingWhenCellsLoseFocus: true,
        onCellValueChanged: (event: CellValueChangedEvent) => this.onCellValueChanged(event),
        onCellClicked: (event: CellClickedEvent) => this.onCellClicked(event),
    };

    public onGridReady(params: GridReadyEvent): void {
        this.gridApi = params.api;
        this.cdr.markForCheck();
    }

    public onCellValueChanged(event: CellValueChangedEvent): void {
        const colId = event.column.getColId();
        const rowIndex = event.rowIndex!;

        if (colId === 'group_name') {
            const typedName = (event.newValue ?? '').trim();
            const isEmpty = !typedName;

            if (!isEmpty) {
                const resolvedName = this.resolveUniqueName(typedName, rowIndex);
                if (resolvedName !== event.newValue) {
                    event.data.group_name = resolvedName;
                    setTimeout(() => {
                        this.gridApi.refreshCells({ rowNodes: [event.node], columns: ['group_name'], force: true });
                    });
                }
            }

            event.data.group_nameWarning = isEmpty;
        } else if (colId === 'expression') {
            event.data.expressionWarning = !event.newValue?.trim();
        } else if (colId === 'manipulation') {
            event.data.manipulationWarning = false;
        }

        this.updateGroupValidFlag(event.data, rowIndex);

        const updatedData = this.rowData().map((group) => ({ ...group }));
        this.rowData.set(updatedData);
        this.emitChanges();
    }

    private updateGroupValidFlag(group: ConditionGroup, groupIndex: number): void {
        const hasValidName = !!group.group_name?.trim();
        const hasNoDuplicateName = !this.rowData().some(
            (g, idx) => idx !== groupIndex && g.group_name === group.group_name
        );
        const hasExpression = !!group.expression?.trim();

        group.valid = hasValidName && hasNoDuplicateName && hasExpression;
    }

    private resolveUniqueName(name: string, excludeIndex: number): string {
        const trimmedName = name.trim();
        if (!trimmedName) return trimmedName;

        const otherNames = new Set(
            this.rowData()
                .filter((_, i) => i !== excludeIndex)
                .map((g) => g.group_name?.trim())
                .filter((n): n is string => !!n)
        );

        if (!otherNames.has(trimmedName)) {
            return trimmedName;
        }

        let counter = 2;
        while (otherNames.has(`${trimmedName} (${counter})`)) {
            counter++;
        }
        return `${trimmedName} (${counter})`;
    }

    public onCellClicked(event: CellClickedEvent): void {
        if (event.colDef.field === 'actions') {
            const rowIndex = event.rowIndex;
            if (rowIndex !== null && rowIndex !== undefined) {
                this.removeConditionGroup(rowIndex);
            }
        }
    }

    public addConditionGroup(): void {
        const insertIndex = this.rowData().length;
        const newGroup = this.createEmptyGroup(insertIndex);
        this.updateGroupValidFlag(newGroup, insertIndex);
        const updated = [...this.rowData(), newGroup];
        this.rowData.set(updated);

        if (this.gridApi) {
            this.gridApi.setGridOption('rowData', updated);
        }

        this.emitChanges();
    }

    public removeConditionGroup(index: number): void {
        const updated = this.rowData()
            .filter((_, i) => i !== index)
            .map((group, newIndex) => ({
                ...group,
                order: newIndex + 1,
            }));
        this.rowData.set(updated);

        if (this.gridApi) {
            this.gridApi.setGridOption('rowData', updated);
        }

        this.emitChanges();
    }

    private emitChanges(): void {
        const updatedGroups = this.rowData().map((group, index) => {
            const normalizedGroup: ConditionGroup = {
                ...group,
                order: index + 1,
            };
            this.updateGroupValidFlag(normalizedGroup, index);
            return normalizedGroup;
        });

        this.rowData.set(updatedGroups);
        this.conditionGroupsChange.emit(updatedGroups);
    }
}
