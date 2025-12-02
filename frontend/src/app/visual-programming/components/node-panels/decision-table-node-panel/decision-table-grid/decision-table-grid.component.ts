import {
    ChangeDetectionStrategy,
    Component,
    input,
    output,
    signal,
    computed,
    ChangeDetectorRef,
    inject,
    OnInit,
    effect,
} from '@angular/core';
import { AgGridModule } from 'ag-grid-angular';
import {
    ColDef,
    GridApi,
    GridOptions,
    GridReadyEvent,
    CellValueChangedEvent,
    CellClickedEvent,
    ICellEditorParams,
} from 'ag-grid-community';
import { AllCommunityModule, ModuleRegistry } from 'ag-grid-community';
import { themeQuartz } from 'ag-grid-community';
import { ConditionGroup } from '../../../../core/models/decision-table.model';
import { FlowService } from '../../../../services/flow.service';
import { NodeType } from '../../../../core/enums/node-type';
import { ButtonComponent } from '../../../../../shared/components/buttons/button/button.component';

import { ExpressionEditorComponent } from './cell-editors/expression-editor/expression-editor.component';
import { ExpressionRendererComponent } from './cell-renderers/expression-renderer/expression-renderer.component';

ModuleRegistry.registerModules([AllCommunityModule]);

@Component({
    selector: 'app-decision-table-grid',
    standalone: true,
    imports: [AgGridModule, ButtonComponent, ExpressionEditorComponent, ExpressionRendererComponent],
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
            .filter((node) => 
                node.type !== NodeType.NOTE && 
                node.type !== NodeType.START &&
                node.type !== NodeType.WEBHOOK_TRIGGER &&
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
                    const newColDefs = colDefs.map((col: any) => {
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
        
        console.log('[DecisionTableGrid] Initializing with groups:', groups);

        const findNodeId = (value: string | null, groupName: string): string | null => {
            // 1. Try direct lookup
            if (value) {
                const foundNode = nodes.find(n => n.id === value || n.node_name === value);
                if (foundNode) return foundNode.id;
                console.warn(`[DecisionTableGrid] Node not found for value: '${value}'`);
            }

            // 2. Fallback: Visual Connection lookup
            // Port ID: `${nodeId}_decision-out-${normalizedGroupName}`
            if (groupName) {
                 const normalizedGroupName = groupName.toLowerCase().replace(/\s+/g, '-');
                 const portId = `${currentNodeId}_decision-out-${normalizedGroupName}`;
                 
                 const connection = connections.find(
                    c => c.sourceNodeId === currentNodeId && c.sourcePortId === portId
                 );

                 if (connection) {
                     console.log(`[DecisionTableGrid] Recovered connection for group '${groupName}' -> ${connection.targetNodeId}`);
                     return connection.targetNodeId;
                 }
            }

            return value;
        };

        if (groups.length === 0) {
            this.rowData.set([this.createEmptyGroup(0)]);
        } else {
            const normalizedGroups = [...groups]
                .sort(
                    (a, b) =>
                        (a.order ?? Number.MAX_SAFE_INTEGER) -
                        (b.order ?? Number.MAX_SAFE_INTEGER)
                )
                .map((group, index) => {
                    // Update group name if it matches the default pattern "Condition X" to reflect current position
                    const groupNameMatch = group.group_name?.match(/^(Condition|Group) (\d+)$/);
                    const normalizedGroup = {
                        ...group,
                        group_name: groupNameMatch ? `Condition ${index + 1}` : group.group_name,
                        order: index + 1,
                        next_node: findNodeId(group.next_node, group.group_name) // Ensure we use ID with fallback
                    };
                    this.updateGroupValidFlag(normalizedGroup, index);
                    return normalizedGroup;
                });
            this.rowData.set(normalizedGroups);
        }
    }

    private createEmptyGroup(index?: number): ConditionGroup {
        const position = index !== undefined ? index + 1 : this.rowData().length + 1;
        return {
            group_name: `Condition ${position}`,
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
            cellEditor: 'agLargeTextCellEditor',
            cellEditorParams: {
                maxLength: 2000,
            },
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
            cellEditorParams: (params: ICellEditorParams) => {
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
        onCellValueChanged: (event: CellValueChangedEvent) =>
            this.onCellValueChanged(event),
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
            const newName = event.newValue?.trim();
            const isEmpty = !newName;
            const isDuplicate = !isEmpty && this.rowData().some((row, idx) => 
                idx !== rowIndex && row.group_name === newName
            );
            
            (event.data as any).group_nameWarning = isEmpty || isDuplicate;
        } else if (colId === 'expression') {
            (event.data as any).expressionWarning = !event.newValue?.trim();
        } else if (colId === 'manipulation') {
            (event.data as any).manipulationWarning = false;
        }
        
        this.updateGroupValidFlag(event.data, rowIndex);
        
        const updatedData = this.rowData().map((group) => ({ ...group }));
        this.rowData.set(updatedData);
        this.emitChanges();
    }

    private updateGroupValidFlag(
        group: ConditionGroup,
        groupIndex: number
    ): void {
        const hasValidName = !!(group.group_name?.trim());
        const hasNoDuplicateName = !this.rowData().some(
            (g, idx) => idx !== groupIndex && g.group_name === group.group_name
        );
        const hasExpression = !!(group.expression?.trim());

        group.valid = hasValidName && hasNoDuplicateName && hasExpression;

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
            .map((group, newIndex) => {
                // Update group name if it matches the default pattern "Condition X" or "Group X"
                const groupNameMatch = group.group_name?.match(/^(Condition|Group) (\d+)$/);
                if (groupNameMatch) {
                    return {
                        ...group,
                        group_name: `Condition ${newIndex + 1}`,
                        order: newIndex + 1,
                    };
                }
                return {
                    ...group,
                    order: newIndex + 1,
                };
            });
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
