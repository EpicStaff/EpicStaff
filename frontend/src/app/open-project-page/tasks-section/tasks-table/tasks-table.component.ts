import { Dialog, DialogModule } from '@angular/cdk/dialog';
import { ConnectedPosition, GlobalPositionStrategy, Overlay, OverlayRef } from '@angular/cdk/overlay';
import { ComponentPortal } from '@angular/cdk/portal';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    ElementRef,
    EventEmitter,
    HostListener,
    Input,
    OnChanges,
    Output,
    Renderer2,
    signal,
    SimpleChanges,
    ViewChild,
} from '@angular/core';
import { AgGridModule } from 'ag-grid-angular';
import {
    CellClickedEvent,
    CellContextMenuEvent,
    CellKeyDownEvent,
    CellValueChangedEvent,
    ColDef,
    GridApi,
    GridOptions,
    GridReadyEvent,
    RowDragEndEvent,
    SuppressKeyboardEventParams,
} from 'ag-grid-community';
import { AllCommunityModule, ModuleRegistry } from 'ag-grid-community';
import { themeQuartz } from 'ag-grid-community';

import { GetProjectRequest } from '../../../features/projects/models/project.model';
import { FullAgent } from '../../../features/staff/services/full-agent.service';
import { FullTask } from '../../../features/tasks/models/full-task.model';
import { CreateTaskRequest, TableFullTask, UpdateTaskRequest } from '../../../features/tasks/models/task.model';
import { TasksService } from '../../../features/tasks/services/tasks.service';
import { ToolsPopupComponent } from '../../../pages/staff-page/components/cell-popups-and-modals/tools-selector-popup/tools-popup.component';
import { IndexCellRendererComponent } from '../../../pages/staff-page/components/cell-renderers/index-row-cell-renderer/custom-row-height.component';
import { AgGridContextMenuComponent } from '../../../pages/staff-page/components/context-menu/ag-grid-context-menu.component';
import { PreventContextMenuDirective } from '../../../pages/staff-page/components/directives/prevent-context-menu.directive';
import { ToastService } from '../../../services/notifications/toast.service';
import { ClickOutsideDirective } from '../../../shared/directives/click-outside.directive';
import { buildToolIdsArray } from '../../../shared/utils/tool-ids-builder.util';
import { FullTaskService } from '../../services/full-task.service';
import { ProjectStateService } from '../../services/project-state.service';
import {
    AdvancedTaskSettingsData,
    AdvancedTaskSettingsDialogComponent,
} from './advanced-task-settings-dialog/advanced-task-settings-dialog.component';
import { HumanInputHeaderComponent } from './header-renderers/human-input-header/human-input.component';
import { KnowledgeQueryHeaderComponent } from './header-renderers/knowledge-query-header/knowledge-query-header.component';
import { AgentSelectionPopupComponent } from './popups/agent-select-popup/agent-selection-popup.component';

ModuleRegistry.registerModules([AllCommunityModule]);

interface CellInfo {
    columnId: string;
    rowIndex: number;
}
type PopupEvent = CellClickedEvent<TableFullTask, unknown> | CellKeyDownEvent<TableFullTask, unknown>;
type EnterJumpParams = SuppressKeyboardEventParams<TableFullTask, unknown>;

export type TaskPendingKind = 'create' | 'update' | 'delete' | 'reorder';

export interface TaskPendingEvent {
    rowKey: string;
    kind: TaskPendingKind;
    payload: unknown;
}

@Component({
    selector: 'app-tasks-table',
    standalone: true,
    imports: [
        AgGridModule,
        DialogModule,
        ClickOutsideDirective,
        PreventContextMenuDirective,
        AgGridContextMenuComponent,
    ],
    templateUrl: './tasks-table.component.html',
    styleUrls: ['./tasks-table.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TasksTableComponent implements OnChanges {
    private _tasks: FullTask[] = [];

    @Input()
    set tasks(value: FullTask[]) {
        // Sort tasks by 'order' (ascending) and push null orders to the end
        this._tasks = value.sort((a, b) => {
            if (a.order === null && b.order === null) {
                return 0;
            }
            if (a.order === null) {
                return 1;
            }
            if (b.order === null) {
                return -1;
            }
            return a.order - b.order;
        });
    }
    get tasks(): FullTask[] {
        return this._tasks;
    }
    @Input() agents: FullAgent[] = [];
    @Input() project!: GetProjectRequest;
    @Input() isSaving = false;

    @Output() taskPending = new EventEmitter<TaskPendingEvent>();
    @Output() dirtyChange = new EventEmitter<boolean>();

    public rowData: TableFullTask[] = [];

    private gridApi!: GridApi;

    public isLoaded = false;

    //context-menu
    public contextMenuVisible = signal(false);
    menuLeft = 0;
    menuTop = 0;
    private selectedRowData: TableFullTask | null = null;

    // Used to store a copy of the row for "Paste" actions
    private copiedRowData: TableFullTask | null = null;

    //overlay
    private popupOverlayRef: OverlayRef | null = null;
    private currentPopupCell: CellInfo | null = null;
    private currentCellElement: HTMLElement | null = null;
    private globalClickUnlistener: (() => void) | null = null;
    private globalKeydownUnlistener: (() => void) | null = null;

    // Track drag state for header drop detection
    private isDragOutsideRows = false;
    private draggedTaskData: TableFullTask | null = null;
    private dragMouseUpListener: (() => void) | null = null;

    private baselineTasksById = new Map<number, unknown>();
    private localPendingKeys = new Set<string>();
    private localDraftTempKeys = new Set<string>();

    constructor(
        private overlay: Overlay,
        private cdr: ChangeDetectorRef,
        private renderer: Renderer2,
        public dialog: Dialog,
        private projectStateService: ProjectStateService,
        private tasksService: TasksService,
        private toastService: ToastService,
        private fullTaskService: FullTaskService
    ) {}

    ngOnInit(): void {
        this.updateRowData();
        this.isLoaded = true;
        this.cdr.markForCheck();
    }

    ngOnChanges(changes: SimpleChanges): void {
        if (changes['tasks'] && this.isLoaded) {
            this.updateRowData();
            if (this.gridApi) {
                this.gridApi.setGridOption('rowData', this.rowData);
            }
            this.cdr.markForCheck();
        }

        if (changes['agents'] && this.isLoaded) {
            this.syncAgentsInCurrentRows();

            if (this.gridApi) {
                this.gridApi.setGridOption('rowData', [...this.rowData]);
            }
            this.cdr.markForCheck();
        }
    }

    private updateRowData(): void {
        const validAgentIds = new Set((this.agents ?? []).map((a) => Number(a.id)));

        const serverTasksByKey = new Map<string, TableFullTask>();

        for (const t of this.tasks) {
            const serverAgentId =
                t.agentData?.id != null
                    ? Number(t.agentData.id)
                    : Number((t as TableFullTask & { agent?: unknown }).agent);

            const hasValidServerAgent = Number.isFinite(serverAgentId) && validAgentIds.has(serverAgentId);

            serverTasksByKey.set(String(t.id), {
                ...t,
                agentData: hasValidServerAgent ? t.agentData : null,
                agent: hasValidServerAgent ? serverAgentId : null,
                mergedTools: (t as TableFullTask & { mergedTools?: unknown }).mergedTools || t.mergedTools || [],
            } as TableFullTask);
        }

        const nextRowData: TableFullTask[] = [];
        const consumedServerKeys = new Set<string>();

        for (const existing of this.rowData) {
            const key = String(existing?.id ?? '');

            if (key.startsWith('temp_')) {
                const shouldKeepTemp =
                    this.localPendingKeys.has(key) ||
                    this.localDraftTempKeys.has(key) ||
                    this.requiredErrorsRows.has(key) ||
                    this.isTempRowTouched(existing);

                if (shouldKeepTemp) {
                    nextRowData.push(existing);
                }

                continue;
            }

            const freshServerRow = serverTasksByKey.get(key);
            if (!freshServerRow) {
                continue;
            }

            consumedServerKeys.add(key);

            const serverAgentId =
                freshServerRow.agentData?.id != null
                    ? Number(freshServerRow.agentData.id)
                    : Number((freshServerRow as TableFullTask & { agent?: unknown }).agent);

            const hasValidServerAgent = Number.isFinite(serverAgentId) && validAgentIds.has(serverAgentId);

            nextRowData.push({
                ...freshServerRow,
                name: existing.name,
                instructions: existing.instructions,
                expected_output: existing.expected_output,
                knowledge_query: existing.knowledge_query,
                human_input: existing.human_input,
                async_execution: existing.async_execution,
                config: existing.config,
                output_model: existing.output_model,
                task_context_list: existing.task_context_list,
                agentData: hasValidServerAgent ? freshServerRow.agentData : null,
                agent: hasValidServerAgent ? serverAgentId : null,
                mergedTools:
                    existing.mergedTools ||
                    (freshServerRow as TableFullTask & { mergedTools?: unknown }).mergedTools ||
                    [],
                order: existing.order ?? freshServerRow.order,
            } as TableFullTask);
        }

        for (const [key, serverRow] of serverTasksByKey.entries()) {
            if (!consumedServerKeys.has(key)) {
                nextRowData.push(serverRow);
            }
        }

        this.rowData = nextRowData;
        this.ensureSingleSpareEmptyRow();

        if (this.localPendingKeys.size === 0) {
            this.baselineTasksById.clear();
            for (const t of this.tasks) {
                if (typeof t.id === 'number') {
                    this.baselineTasksById.set(t.id, this.normalizeTaskForCompare(t));
                }
            }
        }
    }

    private isSpareEmptyTempRow(row: TableFullTask): boolean {
        const id = String(row?.id ?? '');
        if (!id.startsWith('temp_')) return false;

        return (
            !this.isTempRowTouched(row) &&
            !this.localPendingKeys.has(id) &&
            !this.localDraftTempKeys.has(id) &&
            !this.requiredErrorsRows.has(id)
        );
    }

    private ensureSingleSpareEmptyRow(): void {
        const spareIndexes: number[] = [];

        for (let i = 0; i < this.rowData.length; i++) {
            if (this.isSpareEmptyTempRow(this.rowData[i])) spareIndexes.push(i);
        }

        if (spareIndexes.length === 0) {
            this.rowData.push(this.createEmptyFullTask());
            return;
        }

        for (let i = spareIndexes.length - 2; i >= 0; i--) {
            this.rowData.splice(spareIndexes[i], 1);
        }
    }

    onGridReady(event: GridReadyEvent): void {
        this.gridApi = event.api;
        this.gridApi.setGridOption('rowData', [...this.rowData]);
        this.gridApi.refreshCells({ force: true, columns: ['index'] });
    }

    private createEmptyFullTask(): TableFullTask {
        // Create a temporary ID for new tasks
        const tempId = `temp_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

        return {
            id: tempId, // Use temp ID instead of null
            name: '',
            instructions: '',
            expected_output: '',
            knowledge_query: null,
            order: this.rowData.length,
            human_input: false,
            async_execution: false,
            config: null,
            output_model: null,
            crew: this.project ? this.project.id : null,
            agent: null,
            agentData: null,
            task_context_list: [],
            tools: [],
            mergedTools: [],
        };
    }
    myTheme = themeQuartz.withParams({
        accentColor: '#685fff', // --accent-color
        backgroundColor: '#1e1e20', // --color-background-body
        browserColorScheme: 'dark',
        borderColor: '#c8ceda24', // --color-divider-regular
        chromeBackgroundColor: '#222225', // --color-sidenav-background
        columnBorder: true,
        foregroundColor: '#d9d9de', // --color-text-primary
        headerBackgroundColor: '#222225', // --color-sidenav-background
        headerFontSize: 16,
        headerFontWeight: 500,
        headerTextColor: '#d9d9de', // --color-text-primary
        cellTextColor: '#d9d9de', // --color-text-primary
        spacing: 3.3,
        oddRowBackgroundColor: '#222226',
    });

    // Column definitions
    public columnDefs: ColDef[] = [
        {
            colId: 'index',
            valueGetter: 'node.rowIndex + 1',
            cellClass: 'index-cell',
            width: 50,
            cellRenderer: IndexCellRendererComponent,
            editable: false,
        },

        {
            headerName: 'Task Name',
            field: 'name',
            headerClass: 'required-header',
            cellClass: 'agent-role-cell',
            cellEditor: 'agLargeTextCellEditor',
            suppressKeyboardEvent: (params) => this.handleEnterJumpWithinTempRow(params),
            cellEditorPopup: true,
            cellEditorParams: {
                maxLength: 1000000,
                cellEditorValidator: (value: string) => {
                    if (!value || value.trim() === '') {
                        return {
                            valid: false,
                            message: 'Task cannot be empty (cell will not be saved).',
                        };
                    }
                    return { valid: true };
                },
            },
            valueSetter: (params) => {
                params.data.name = params.newValue;
                return true;
            },
            cellClassRules: {
                'cell-warning': (params) => !!params.data.roleWarning,
                'cell-required-invalid': (params) => {
                    const id = String(params.data?.id ?? '');
                    if (!this.isTempRowId(id)) return false;
                    if (!this.requiredErrorsRows.has(id)) return false;
                    return this.isRequiredEmpty(params.value);
                },
            },
            cellStyle: {
                'white-space': 'normal',
                'text-align': 'left',
                'font-size': '14px',
            },
            flex: 1,
            minWidth: 210,
            maxWidth: 240,
            rowDrag: true,
            editable: true,
        },
        {
            headerName: 'Instructions',
            field: 'instructions',
            headerClass: 'required-header',
            cellEditor: 'agLargeTextCellEditor',
            suppressKeyboardEvent: (params) => this.handleEnterJumpWithinTempRow(params),
            cellEditorPopup: true,
            cellEditorParams: {
                maxLength: 1000000,
                cellEditorValidator: (value: string) => {
                    if (!value || value.trim() === '') {
                        return {
                            valid: false,
                            message: 'Instructions cannot be empty.',
                        };
                    }
                    return { valid: true };
                },
            },
            valueSetter: (params) => {
                params.data.instructions = params.newValue;
                return true;
            },
            cellClassRules: {
                'cell-warning': (params) => !!params.data.goalWarning,
                'cell-required-invalid': (params) => {
                    const id = String(params.data?.id ?? '');
                    if (!this.isTempRowId(id)) return false;
                    if (!this.requiredErrorsRows.has(id)) return false;
                    return this.isRequiredEmpty(params.value);
                },
            },
            cellStyle: {
                'white-space': 'normal',
                'text-align': 'left',
                'font-size': '14px',
            },
            flex: 1,
            minWidth: 255,
            editable: true,
        },
        {
            headerName: 'Expected Output',
            headerClass: 'required-header',
            field: 'expected_output',
            cellEditor: 'agLargeTextCellEditor',
            suppressKeyboardEvent: (params) => this.handleEnterJumpWithinTempRow(params),
            cellEditorPopup: true,
            cellEditorParams: {
                maxLength: 1000000,
                cellEditorValidator: (value: string) => {
                    if (!value || value.trim() === '') {
                        return {
                            valid: false,
                            message: 'Expected Output cannot be empty.',
                        };
                    }
                    return { valid: true };
                },
            },
            valueSetter: (params) => {
                params.data.expected_output = params.newValue;
                return true;
            },
            cellClassRules: {
                'cell-warning': (params) => !!params.data.backstoryWarning,
                'cell-required-invalid': (params) => {
                    const id = String(params.data?.id ?? '');
                    if (!this.isTempRowId(id)) return false;
                    if (!this.requiredErrorsRows.has(id)) return false;
                    return this.isRequiredEmpty(params.value);
                },
            },
            cellStyle: {
                'white-space': 'normal',
                'text-align': 'left',
                'font-size': '14px',
            },
            flex: 1,
            minWidth: 255,
            editable: true,
        },
        {
            // Use a custom header component so we can render the material icon + tooltip
            headerComponent: KnowledgeQueryHeaderComponent,
            field: 'knowledge_query',
            cellEditor: 'agLargeTextCellEditor',
            cellEditorParams: {
                maxLength: 1000000,
            },
            valueSetter: (params) => {
                params.data.knowledge_query = params.newValue;
                return true;
            },
            cellStyle: {
                'white-space': 'normal',
                'text-align': 'left',
                'font-size': '14px',
            },
            flex: 1,
            minWidth: 255,
            editable: true,
        },

        {
            headerName: 'Human Input',

            headerComponent: HumanInputHeaderComponent,
            field: 'human_input',
            cellRenderer: 'agCheckboxCellRenderer',
            cellEditor: 'agCheckboxCellEditor',
            editable: true,
            cellClass: 'memory-checkbox',
            width: 60,
        },
        // {
        //   headerName: 'Async Execution',

        //   headerComponent: AsyncHeaderComponent,
        //   field: 'async_execution',
        //   cellRenderer: 'agCheckboxCellRenderer',
        //   cellEditor: 'agCheckboxCellEditor',
        //   editable: true,
        //   cellClass: 'memory-checkbox',
        //   width: 60,
        // },

        {
            headerName: 'Tools',
            field: 'mergedTools',
            editable: false,
            flex: 1,
            minWidth: 200,
            maxWidth: 400,
            cellRenderer: (params: { value: unknown[] }) => {
                const tools = (params.value || []) as Array<{
                    configName?: unknown;
                    toolName?: unknown;
                    type: string;
                }>;

                if (!tools || tools.length === 0) {
                    return '<div class="no-tools">No tools assigned</div>';
                }

                const toolsHtml = tools
                    .map((tool: { configName?: unknown; toolName?: unknown; type: string }) => {
                        // For MCP tools, display the configName (mcp.name) instead of toolName (mcp.tool_name)
                        const displayName = tool.type === 'mcp-tool' ? tool.configName : tool.toolName;
                        return `
                <div class="tool-item">
                  <i class="tool-icon">🔧</i>
                  <span class="tool-name-text" title="${displayName}">${displayName}</span>
                </div>
              `;
                    })
                    .join('');

                return `<div class="tools-cell-wrapper">${toolsHtml}</div>`;
            },
        },
        {
            headerName: 'Assigned Agent',
            field: 'agentData', // Reference the agentData field
            editable: false,
            minWidth: 240,
            maxWidth: 260,
            cellRenderer: (params: { data: TableFullTask }) => {
                const agent = params.data.agentData; // Access the agentData object from the row data
                if (agent) {
                    return agent.role; // Render the agent's role if available
                } else {
                    return '<div class="no-tools">No agent assigned</div>'; // Wrap the message in a div with class "no-tools"
                }
            },
            cellClass: 'agent-role-cell', // Optional: Add a custom class if needed
        },

        {
            headerName: '',
            field: 'actions',
            cellRenderer: () => {
                return `<i class="ti ti-settings action-icon"></i>`;
            },
            width: 40,
            cellClass: 'action-cell',

            editable: false,
        },
    ];

    public defaultColDef: ColDef = {
        headerClass: 'global-header-class',
        sortable: false,
        resizable: false,
        wrapText: true,
        suppressMovable: true,
    };

    gridOptions: GridOptions = {
        rowHeight: 106,
        headerHeight: 50,
        columnDefs: this.columnDefs,
        undoRedoCellEditing: true,
        undoRedoCellEditingLimit: 20,
        theme: this.myTheme,
        animateRows: false,
        stopEditingWhenCellsLoseFocus: true,
        getRowId: (params) => {
            if (params.data.id && typeof params.data.id === 'number') {
                return params.data.id.toString();
            }

            if (params.data.id && typeof params.data.id === 'string' && params.data.id.startsWith('temp_')) {
                return params.data.id;
            }

            const tempId = `temp_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
            params.data.id = tempId;
            return tempId;
        },

        onCellClicked: (event: CellClickedEvent<TableFullTask, unknown>) => this.onCellClicked(event),
        onCellKeyDown: (event: CellKeyDownEvent) => this.onCellKeyDown(event),
        onCellValueChanged: (event) => this.onCellValueChanged(event),
        onCellFocused: (e) => {
            if (e.rowIndex == null) return;
            const node = this.gridApi?.getDisplayedRowAtIndex(e.rowIndex);
            if (!node?.data?.id) return;
            this.activeRowId = String(node.data.id);
        },
        onRowDragEnd: (event) => this.onRowDragEnd(event),
        onRowDragEnter: () => {
            // Clear the outside flag when re-entering the row area
            this.isDragOutsideRows = false;
            this.draggedTaskData = null;
            this.removeDragMouseUpListener();
        },
        onRowDragLeave: (event) => {
            // When drag leaves the grid area (e.g., into header), set flag and wait for mouseup
            this.isDragOutsideRows = true;
            this.draggedTaskData = event.node?.data as TableFullTask;

            // Add mouseup listener to detect when user releases the mouse outside rows
            this.addDragMouseUpListener();
        },
    };
    // Event handler for rowDragEnd
    onRowDragEnd(event: RowDragEndEvent) {
        // Clear drag outside state
        this.isDragOutsideRows = false;
        this.draggedTaskData = null;
        this.removeDragMouseUpListener();

        // Get the moved data
        const movedData = event.node.data as TableFullTask;

        // Find original index in our rowData
        const fromIndex = this.rowData.findIndex((row) => row === movedData);
        const toIndex = event.overIndex;

        if (fromIndex === -1 || toIndex === null || toIndex === undefined) {
            return;
        }

        // Check if dropped outside the valid rows area (e.g., into header or above rows)
        if (toIndex < 0 || toIndex >= this.rowData.length) {
            this.toastService.error('Cannot move task outside the tasks area.');
            if (this.gridApi) {
                this.gridApi.setGridOption('rowData', [...this.rowData]);
            }
            return;
        }

        // Calculate where the item will end up after removal (accounts for index shift when removing earlier item)
        const finalTargetIndex = fromIndex < toIndex ? toIndex - 1 : toIndex;

        // Check if we can move the dragged task to the final target index
        const conflictingDeps = (movedData.task_context_list || []).filter((depId: unknown) => {
            const depIdNum = Number(depId);
            const depIndex = this.rowData.findIndex((row) => {
                if (row.id === null || row.id === undefined) return false;
                // Convert both to numbers where possible
                const rowIdNum = typeof row.id === 'string' ? (row.id.startsWith('temp_') ? NaN : +row.id) : row.id;
                return depIdNum === rowIdNum;
            });
            // If dependency not found or dependency would end up below target position -> conflict
            return depIndex === -1 || depIndex >= finalTargetIndex;
        });

        if (conflictingDeps.length > 0) {
            // Build a friendly message listing up to 3 conflicting task names/ids
            const conflictNames = conflictingDeps.map((depId: unknown) => {
                const depIdNum = Number(depId);
                const row = this.rowData.find((r) => {
                    if (r.id === null || r.id === undefined) return false;
                    const rowIdNum = typeof r.id === 'string' ? (r.id.startsWith('temp_') ? NaN : +r.id) : r.id;
                    return depIdNum === rowIdNum;
                });
                return row ? `${row.name || 'Without name'} (id:${row.id})` : `id:${depId}`;
            });

            const shortList = conflictNames.slice(0, 3).join(', ');
            const more = conflictNames.length > 3 ? `, …и ещё ${conflictNames.length - 3}` : '';

            this.toastService.error(`Context conflict  ${shortList}${more}. First, arrange/edit the dependencies.`);

            // Revert any visual reorder by re-setting the grid data to our authoritative rowData
            if (this.gridApi) {
                this.gridApi.setGridOption('rowData', [...this.rowData]);
            }

            return;
        }

        // Additional check: when moving a task, other tasks between source and target
        // will shift. If any of those shifted tasks have dependencies that must be
        // above them, the shift may break their dependencies. We must check those
        // and block the move if conflicts are found.
        const shiftedConflicts: string[] = [];

        if (fromIndex < toIndex) {
            // Moving down: rows in (fromIndex+1 .. toIndex) will shift up by 1
            for (let i = fromIndex + 1; i <= toIndex; i++) {
                const row = this.rowData[i];
                if (!row) continue;
                const newIndex = i - 1;
                const deps = row.task_context_list || [];
                deps.forEach((depId: unknown) => {
                    const depIdNum = Number(depId);
                    const depIndex = this.rowData.findIndex((r) => {
                        if (r.id === null || r.id === undefined) return false;
                        const rowIdNum = typeof r.id === 'string' ? (r.id.startsWith('temp_') ? NaN : +r.id) : r.id;
                        return depIdNum === rowIdNum;
                    });
                    if (depIndex === -1 || depIndex >= newIndex) {
                        const depRow = this.rowData.find((r) => {
                            if (r.id === null || r.id === undefined) return false;
                            const rowIdNum = typeof r.id === 'string' ? (r.id.startsWith('temp_') ? NaN : +r.id) : r.id;
                            return depIdNum === rowIdNum;
                        });
                        const depLabel = depRow ? `${depRow.name || 'Without name'} (id:${depRow.id})` : `id:${depId}`;
                        shiftedConflicts.push(`${row.name || 'Without name'} (id:${row.id}) → dependency ${depLabel}`);
                    }
                });
            }
        } else if (fromIndex > toIndex) {
            // Moving up: rows in (toIndex .. fromIndex-1) will shift down by 1
            for (let i = toIndex; i <= fromIndex - 1; i++) {
                const row = this.rowData[i];
                if (!row) continue;
                const newIndex = i + 1;
                const deps = row.task_context_list || [];
                deps.forEach((depId: unknown) => {
                    const depIdNum = Number(depId);
                    const depIndex = this.rowData.findIndex((r) => {
                        if (r.id === null || r.id === undefined) return false;
                        const rowIdNum = typeof r.id === 'string' ? (r.id.startsWith('temp_') ? NaN : +r.id) : r.id;
                        return depIdNum === rowIdNum;
                    });
                    if (depIndex === -1 || depIndex >= newIndex) {
                        const depRow = this.rowData.find((r) => {
                            if (r.id === null || r.id === undefined) return false;
                            const rowIdNum = typeof r.id === 'string' ? (r.id.startsWith('temp_') ? NaN : +r.id) : r.id;
                            return depIdNum === rowIdNum;
                        });
                        const depLabel = depRow ? `${depRow.name || 'Without name'} (id:${depRow.id})` : `id:${depId}`;
                        shiftedConflicts.push(`${row.name || 'Without name'} (id:${row.id}) → dependency ${depLabel}`);
                    }
                });
            }
        }

        if (shiftedConflicts.length > 0) {
            const shortList = shiftedConflicts.slice(0, 4).join('; ');
            const more = shiftedConflicts.length > 4 ? `; …и ещё ${shiftedConflicts.length - 4}` : '';
            this.toastService.error(
                `Cannot move the task: shifting it would break the context for: ${shortList}${more}.`
            );
            if (this.gridApi) {
                this.gridApi.setGridOption('rowData', [...this.rowData]);
            }
            return;
        }

        // Proceed with the reorder. Be careful with insertion index shift when removing earlier item.
        // Remove the row from its old position
        this.rowData.splice(fromIndex, 1);

        // Calculate insertion index after removal
        let insertIndex = toIndex;
        if (fromIndex < toIndex) {
            insertIndex = toIndex - 1;
        }

        // Insert into the new position
        this.rowData.splice(insertIndex, 0, movedData);

        // Update order values in all rows
        this.rowData.forEach((row, i) => {
            row.order = i;
        });

        // Refresh all rows to update the order display
        this.gridApi.refreshCells({
            force: true,
            columns: ['index'], // Refresh only the order column
        });

        // Mark for change detection
        this.cdr.markForCheck();

        // Update task orders on the backend
        this.updateTaskOrders();
    }

    // Add mouseup listener to detect drop outside rows
    private addDragMouseUpListener(): void {
        if (this.dragMouseUpListener) return; // Already listening

        this.dragMouseUpListener = this.renderer.listen('document', 'mouseup', () => {
            if (this.isDragOutsideRows && this.draggedTaskData) {
                // User released mouse while outside row area - handle as drop to first position
                this.handleDragToFirstPosition();
            }
            // Clean up
            this.isDragOutsideRows = false;
            this.draggedTaskData = null;
            this.removeDragMouseUpListener();
        });
    }

    // Remove mouseup listener
    private removeDragMouseUpListener(): void {
        if (this.dragMouseUpListener) {
            this.dragMouseUpListener();
            this.dragMouseUpListener = null;
        }
    }

    // Handle drag to area outside the table (header or above) - show warning and revert
    private handleDragToFirstPosition(): void {
        // Show warning that task cannot be dropped outside the table area
        this.toastService.error('Cannot drop task outside the table area. Please drop it on a valid row.');

        // Revert the visual state
        if (this.gridApi) {
            this.gridApi.setGridOption('rowData', [...this.rowData]);
        }
    }

    private parseTaskData(taskData: FullTask) {
        const rawAgentId = taskData.agentData?.id ?? (taskData as TableFullTask & { agent?: unknown }).agent ?? null;

        const agentId = rawAgentId == null || String(rawAgentId).trim() === '' ? null : Number(rawAgentId);

        const crew = this.project ? this.project.id : null;
        const mergedTools =
            (taskData as TableFullTask & { mergedTools?: Array<{ type?: string; id?: unknown }> }).mergedTools || [];

        const configuredTools = mergedTools
            .filter((tool: { type?: string; id?: unknown }) => tool.type === 'tool-config')
            .map((tool: { id?: unknown }) => Number(tool.id))
            .filter((id): id is number => Number.isFinite(id));
        const pythonTools = mergedTools
            .filter((tool: { type?: string; id?: unknown }) => tool.type === 'python-tool')
            .map((tool: { id?: unknown }) => Number(tool.id))
            .filter((id): id is number => Number.isFinite(id));
        const mcpTools = mergedTools
            .filter((tool: { type?: string; id?: unknown }) => tool.type === 'mcp-tool')
            .map((tool: { id?: unknown }) => Number(tool.id))
            .filter((id): id is number => Number.isFinite(id));

        const parsed = {
            ...taskData,
            agent: Number.isFinite(agentId) ? agentId : null,
            crew,
            configured_tools: configuredTools,
            python_code_tools: pythonTools,
            mcp_tools: mcpTools,
            mergedTools,
        };

        delete (parsed as { tools?: unknown }).tools;
        return parsed;
    }

    private onCellValueChanged(event: CellValueChangedEvent): void {
        if (this.isSameCellValue(event.oldValue, event.newValue)) return;

        const colId = event.column.getColId();
        const fieldsToValidate = ['name', 'instructions', 'expected_output'];

        const isTempTask = !event.data.id || (typeof event.data.id === 'string' && event.data.id.startsWith('temp_'));

        if (isTempTask) {
            const rowKey = String(event.data.id);
            const touched = this.isTempRowTouched(event.data);
            const valid = this.isTempRowValid(event.data);

            if (!touched) {
                this.localDraftTempKeys.delete(rowKey);
                this.setPending(rowKey, null);

                this.requiredErrorsRows.delete(rowKey);
                this.gridApi.refreshCells({
                    rowNodes: [event.node],
                    columns: [...this.requiredTaskFields],
                    force: true,
                });
                this.cdr.markForCheck();
                return;
            }

            this.localDraftTempKeys.add(rowKey);
            this.updateRequiredErrorsForTempRow(rowKey, event.data);

            if (!valid) {
                this.setPending(rowKey, null);
                this.cdr.markForCheck();
                return;
            }

            this.localDraftTempKeys.delete(rowKey);
            this.requiredErrorsRows.delete(rowKey);

            const parsedData = this.parseTaskData(event.data);
            const configuredToolIds = parsedData.configured_tools || [];
            const pythonToolIds = parsedData.python_code_tools || [];
            const mcpToolIds = parsedData.mcp_tools || [];
            const toolIds = buildToolIdsArray(configuredToolIds, pythonToolIds, mcpToolIds);

            const createTaskData: CreateTaskRequest = {
                ...parsedData,
                knowledge_query: parsedData.knowledge_query ?? null,
                order: parsedData.order ?? null,
                human_input: parsedData.human_input ?? false,
                async_execution: parsedData.async_execution ?? false,
                config: parsedData.config ?? null,
                output_model: parsedData.output_model ?? null,
                task_context_list: parsedData.task_context_list ?? [],
                configured_tools: configuredToolIds,
                python_code_tools: pythonToolIds,
                mcp_tools: mcpToolIds,
                tool_ids: toolIds,
            };

            this.setPending(rowKey, {
                rowKey,
                kind: 'create',
                payload: createTaskData,
            });

            this.ensureSingleSpareEmptyRow();
            this.gridApi?.setGridOption('rowData', [...this.rowData]);
            this.gridApi?.refreshCells({ force: true, columns: ['index'] });
            this.cdr.markForCheck();
            this.emitReorderPending();
            return;
        }

        let allValid = true;
        for (const field of fieldsToValidate) {
            const v = event.data[field] ? String(event.data[field]).trim() : '';
            event.data[`${field}Warning`] = !v;
            if (!v) allValid = false;
        }

        this.gridApi.refreshCells({
            rowNodes: [event.node],
            columns: [colId],
        });

        if (!allValid) return;
        this.upsertPendingForExistingTask(event.data as TableFullTask);
        this.cdr.markForCheck();
    }

    ngOnDestroy(): void {
        this.closePopup();
        this.removeDragMouseUpListener();
    }

    openSettingsDialog(taskData: TableFullTask) {
        // Filter tasks with normal IDs (numeric IDs), non-null orders, and orders less than current task
        const normalTasks: TableFullTask[] = this.rowData.filter((task) => {
            // Check if the ID is a number or a string that can be parsed as a number
            const hasNormalId =
                typeof task.id === 'number' || (typeof task.id === 'string' && !task.id.startsWith('temp'));

            // Remove tasks with null order
            if (task.order === null) {
                return false;
            }

            // Remove tasks with order greater than or equal to current task's order
            // Only keep tasks with order < taskData.order (strictly less than)
            const hasValidOrder = taskData.order !== null && task.order < taskData.order;

            return hasNormalId && hasValidOrder;
        });

        const positionStrategy = new GlobalPositionStrategy().top('45px').centerHorizontally();

        const dialogRef = this.dialog.open(AdvancedTaskSettingsDialogComponent, {
            data: {
                config: taskData.config,
                output_model: taskData.output_model,
                task_context_list: taskData.task_context_list,
                taskName: taskData.name,
                taskId: taskData.id,
                availableTasks: normalTasks, // Pass filtered tasks to dialog
            },
            disableClose: true,
            width: '100%', // Set minimum width
            maxWidth: '650px', // Allow it to be responsive but not too wide
            height: 'fit-content', // Set height to 90% of viewport height
            maxHeight: '90vh', // Ensure maximum height
            positionStrategy,
        });

        dialogRef.closed.subscribe((updatedData) => {
            const data = updatedData as AdvancedTaskSettingsData | undefined;
            if (!data) return;

            const beforeOutput = taskData.output_model ?? null;
            const beforeCtx = Array.isArray(taskData.task_context_list) ? taskData.task_context_list : [];

            const afterOutput = data.output_model ?? null;
            const afterCtx = Array.isArray(data.task_context_list) ? data.task_context_list : [];

            const norm = (arr: unknown[]) =>
                arr
                    .map((x) => (typeof x === 'string' ? Number(x) : x))
                    .filter((x) => Number.isFinite(x))
                    .map((x) => Number(x))
                    .sort((a, b) => a - b);

            const sameOutput = JSON.stringify(beforeOutput) === JSON.stringify(afterOutput);
            const sameCtx = JSON.stringify(norm(beforeCtx)) === JSON.stringify(norm(afterCtx));

            if (sameOutput && sameCtx) return;

            this.updateTaskDataInRow(
                {
                    output_model: afterOutput,
                    task_context_list: afterCtx,
                },
                taskData
            );
        });
    }

    updateTaskDataInRow(updatedData: Partial<TableFullTask>, taskData: TableFullTask): void {
        const index = this.rowData.findIndex((task) => task.id === taskData.id);
        if (index === -1) {
            console.error('Task not found in rowData for update:', taskData);
            return;
        }

        // Create an updated version of the task
        const updatedTask: TableFullTask = {
            ...this.rowData[index],
            ...updatedData,
        };

        const isAgentCleared =
            ('agent' in updatedData && updatedData.agent == null) ||
            ('agentData' in updatedData && updatedData.agentData == null);

        if (isAgentCleared) {
            updatedTask.agent = null;
            updatedTask.agentData = null;
        }

        // Update our local row data
        this.rowData[index] = updatedTask;

        // Use transaction API to update the grid
        this.gridApi.applyTransaction({ update: [updatedTask] });

        // Mark for change detection
        this.cdr.markForCheck();

        // Check if this is a temporary task
        const isTempTask =
            !updatedTask.id || (typeof updatedTask.id === 'string' && updatedTask.id.startsWith('temp_'));

        if (isTempTask) {
            const rowKey = String(updatedTask.id);
            const touched = this.isTempRowTouched(updatedTask);
            const valid = this.isTempRowValid(updatedTask);

            if (!touched) {
                this.localDraftTempKeys.delete(rowKey);
                this.requiredErrorsRows.delete(rowKey);
                this.setPending(rowKey, null);
                this.gridApi.refreshCells({
                    rowNodes: [this.gridApi.getRowNode(rowKey)!].filter(Boolean),
                    force: true,
                });
                return;
            }

            this.localDraftTempKeys.add(rowKey);
            this.updateRequiredErrorsForTempRow(rowKey, updatedTask);

            if (!valid) {
                this.setPending(rowKey, null);
                return;
            }

            this.localDraftTempKeys.delete(rowKey);
            this.requiredErrorsRows.delete(rowKey);

            const parsedTaskData = this.parseTaskData(updatedTask as FullTask);
            const cfg = parsedTaskData.configured_tools || [];
            const py = parsedTaskData.python_code_tools || [];
            const mcp = parsedTaskData.mcp_tools || [];
            const tool_ids = buildToolIdsArray(cfg, py, mcp);

            this.setPending(rowKey, {
                rowKey,
                kind: 'create',
                payload: {
                    ...parsedTaskData,
                    knowledge_query: updatedTask.knowledge_query ?? null,
                    configured_tools: cfg,
                    python_code_tools: py,
                    mcp_tools: mcp,
                    tool_ids,
                },
            });

            this.ensureSingleSpareEmptyRow();
            this.gridApi?.setGridOption('rowData', [...this.rowData]);
            this.gridApi?.refreshCells({ force: true, columns: ['index'] });

            return;
        }

        // Parse the task data to extract tools
        const parsedTaskData = this.parseTaskData(updatedTask as FullTask);

        // Build tool_ids array for settings update
        const settingsConfiguredToolIds = parsedTaskData.configured_tools || [];
        const settingsPythonToolIds = parsedTaskData.python_code_tools || [];
        const settingsMcpToolIds = parsedTaskData.mcp_tools || [];
        const settingsToolIds = buildToolIdsArray(settingsConfiguredToolIds, settingsPythonToolIds, settingsMcpToolIds);

        // Prepare the payload for the backend update request (excluding tools field)
        const updateTaskData: UpdateTaskRequest = {
            ...parsedTaskData,
            id: +updatedTask.id,
            name: updatedTask.name,
            instructions: updatedTask.instructions,
            expected_output: updatedTask.expected_output,
            knowledge_query: updatedTask.knowledge_query ?? null,
            human_input: updatedTask.human_input,
            async_execution: updatedTask.async_execution,
            config: updatedTask.config,
            output_model: updatedTask.output_model,
            crew: updatedTask.crew,
            agent: parsedTaskData.agent,
            task_context_list: updatedTask.task_context_list,
            configured_tools: settingsConfiguredToolIds,
            python_code_tools: settingsPythonToolIds,
            mcp_tools: settingsMcpToolIds,
            tool_ids: settingsToolIds,
        };

        this.setPending(String(updatedTask.id), {
            rowKey: String(updatedTask.id),
            kind: 'update',
            payload: updateTaskData,
        });

        return;
    }
    public handleCopy(): void {
        if (!this.selectedRowData) return;
        // Deep clone the selected row (to avoid mutating references)
        this.copiedRowData = JSON.parse(JSON.stringify(this.selectedRowData));
        this.closeContextMenu();
    }
    public handlePasteBelow(): void {
        if (!this.selectedRowData || !this.copiedRowData) return;
        const index = this.rowData.findIndex((row: TableFullTask) => row === this.selectedRowData);
        if (index === -1) return;
        this.pasteNewTaskAt(index + 1);
    }

    public handlePasteAbove(): void {
        if (!this.selectedRowData || !this.copiedRowData) return;
        const index = this.rowData.findIndex((row) => row === this.selectedRowData);
        if (index === -1) return;
        this.pasteNewTaskAt(index);
    }

    public handleDelete(): void {
        if (!this.selectedRowData) return;

        // Check if row has a temp ID or null ID: handle locally
        const isTempRow =
            !this.selectedRowData.id ||
            (typeof this.selectedRowData.id === 'string' && this.selectedRowData.id.startsWith('temp_'));

        if (isTempRow) {
            // For temporary rows, remove directly without backend call
            const localIndex = this.rowData.findIndex((row) => row === this.selectedRowData);

            if (localIndex !== -1) {
                // Remove from local array
                this.rowData.splice(localIndex, 1);

                // Refresh the grid with the updated data
                this.gridApi.setGridOption('rowData', [...this.rowData]);

                // Refresh index column
                this.gridApi.refreshCells({
                    force: true,
                    columns: ['index'],
                });

                this.cdr.markForCheck();
            } else {
                console.warn('Row not found for local deletion.');
            }

            const tempRowKey = String(this.selectedRowData.id);
            this.localDraftTempKeys.delete(tempRowKey);
            this.requiredErrorsRows.delete(tempRowKey);
            this.setPending(tempRowKey, null);
            this.ensureSingleSpareEmptyRow();
            this.reindexAndSyncPendingOrders();
            this.maybeClearReorderPending();
            this.closeContextMenu();
            return;
        }

        // For rows with real IDs from the backend
        const rowToDelete = this.selectedRowData;
        const index = this.rowData.findIndex((row) => row === rowToDelete);

        if (index === -1) {
            console.error('Row not found in grid for deletion:', rowToDelete);
            this.closeContextMenu();
            return;
        }

        // Remove optimistically from local array
        this.rowData.splice(index, 1);
        this.reindexAndSyncPendingOrders();

        this.cdr.markForCheck();

        // Convert ID to number if it's a string
        const idToDelete = typeof rowToDelete.id === 'string' ? +rowToDelete.id : rowToDelete.id;

        this.setPending(String(idToDelete), {
            rowKey: String(idToDelete),
            kind: 'delete',
            payload: { id: idToDelete },
        });

        this.projectStateService.deleteTask(idToDelete);

        this.emitReorderPending();
        this.closeContextMenu();
        return;
    }

    public closeContextMenu(): void {
        this.contextMenuVisible.set(false);
    }

    private pasteNewTaskAt(insertIndex: number): void {
        // Create a temporary ID for the new task
        const tempId = `temp_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

        const newTaskData: FullTask = {
            ...JSON.parse(JSON.stringify(this.copiedRowData)),
            id: tempId, // Use temporary ID instead of null
        };

        // Update our local array
        this.rowData.splice(insertIndex, 0, newTaskData);

        // Use transaction API to add the row
        this.gridApi.applyTransaction({
            add: [newTaskData],
            addIndex: insertIndex,
        });

        // Mark for change detection
        this.cdr.markForCheck();

        // Parse the task data to extract tools
        const parsedTaskData = this.parseTaskData(newTaskData);

        // Build tool_ids array for paste operation
        const pasteConfiguredToolIds = parsedTaskData.configured_tools || [];
        const pastePythonToolIds = parsedTaskData.python_code_tools || [];
        const pasteMcpToolIds = parsedTaskData.mcp_tools || [];
        const pasteToolIds = buildToolIdsArray(pasteConfiguredToolIds, pastePythonToolIds, pasteMcpToolIds);

        const createTaskData: CreateTaskRequest = {
            ...parsedTaskData,
            name: newTaskData.name,
            instructions: newTaskData.instructions,
            expected_output: newTaskData.expected_output,
            knowledge_query: newTaskData.knowledge_query ?? null,
            order: newTaskData.order ?? null,
            human_input: newTaskData.human_input ?? false,
            async_execution: newTaskData.async_execution ?? false,
            config: newTaskData.config ?? null,
            output_model: newTaskData.output_model ?? null,
            crew: newTaskData.crew ?? null,
            agent: newTaskData.agent ?? null,
            task_context_list: newTaskData.task_context_list ?? [],
            configured_tools: pasteConfiguredToolIds,
            python_code_tools: pastePythonToolIds,
            mcp_tools: pasteMcpToolIds,
            tool_ids: pasteToolIds,
        };

        this.setPending(String(newTaskData.id), {
            rowKey: String(newTaskData.id),
            kind: 'create',
            payload: createTaskData,
        });
        this.gridApi.applyTransaction({ update: [newTaskData] });
        this.reindexAndSyncPendingOrders();
        this.closeContextMenu();
        return;
    }

    public handleAddEmptyTaskAbove(): void {
        if (!this.selectedRowData) return;
        const index = this.rowData.findIndex((row) => row === this.selectedRowData);
        if (index === -1) return;
        this.insertEmptyTaskAt(index);
    }

    public handleAddEmptyTaskBelow(): void {
        if (!this.selectedRowData) return;
        const index = this.rowData.findIndex((row) => row === this.selectedRowData);
        if (index === -1) return;
        this.insertEmptyTaskAt(index + 1);
    }

    private insertEmptyTaskAt(insertIndex: number): void {
        // Create an empty task with a temporary ID
        const emptyTask = this.createEmptyFullTask();

        // Add to our data array
        this.rowData.splice(insertIndex, 0, emptyTask);

        // Use transaction API to add efficiently
        this.gridApi.applyTransaction({
            add: [emptyTask],
            addIndex: insertIndex,
        });

        this.reindexAndSyncPendingOrders();

        // Mark for change detection
        this.cdr.markForCheck();

        this.closeContextMenu();
    }

    updateTaskOrders(): void {
        this.reindexAndSyncPendingOrders();
    }

    private onCellClicked(event: CellClickedEvent<TableFullTask, unknown>): void {
        if (event.column.getColId() === 'actions') {
            const taskData = event.data;
            if (!taskData) return;
            this.closePopup();
            this.openSettingsDialog(taskData);
            return;
        }
        const columnId = event.column.getColId();
        // Process only specific columns.
        if (columnId === 'mergedTools' || columnId === 'agentData') {
            const rowIndex = event.rowIndex ?? 0;
            const cell: CellInfo = { columnId, rowIndex };

            if (
                this.popupOverlayRef &&
                this.currentPopupCell &&
                this.currentPopupCell.columnId === cell.columnId &&
                this.currentPopupCell.rowIndex === cell.rowIndex
            ) {
                return;
            }

            this.closePopup();
            this.openPopup(event, cell);
            return;
        }

        // Prevent default behavior if needed.
        const keyboardEvent = event.event as KeyboardEvent;
        if (keyboardEvent) {
            keyboardEvent.preventDefault();
        }
    }

    private onCellKeyDown(event: CellKeyDownEvent<TableFullTask, unknown>): void {
        const keyboardEvent = event.event as KeyboardEvent;

        if (keyboardEvent?.key === 'Enter') {
            const { rowIndex, column } = event;
            const columnId = column.getColId();
            if (event.column.getColId() === 'actions') {
                const taskData = event.data;
                if (!taskData) return;
                this.closePopup();

                this.openSettingsDialog(taskData);
                return;
            }

            if (columnId === 'agentData') {
                if (rowIndex !== null) {
                    if (
                        this.popupOverlayRef &&
                        this.currentPopupCell &&
                        this.currentPopupCell.columnId === columnId &&
                        this.currentPopupCell.rowIndex === rowIndex
                    ) {
                        return;
                    }
                    // Close any existing popup before opening a new one.
                    this.closePopup();
                    this.openPopup(event, { columnId, rowIndex });
                } else {
                    console.warn('Row index is null, cannot open popup.');
                }
            }

            // Prevent default behavior if needed.
            keyboardEvent.preventDefault();
        }
    }

    private openPopup(event: PopupEvent, cell: CellInfo): void {
        this.currentPopupCell = cell;

        // Get the container cell element.
        let target = (event.event!.target as HTMLElement).closest('.ag-cell') as HTMLElement;
        if (!target) {
            target = event.event!.target as HTMLElement;
        }
        this.currentCellElement = target;

        // Add a custom CSS class to visually indicate the cell has an open popup.
        this.renderer.addClass(this.currentCellElement, 'popup-open');

        // Define possible positions for the popup.
        const positions: ConnectedPosition[] = [
            {
                originX: 'end',
                originY: 'bottom',
                overlayX: 'end',
                overlayY: 'top',
                offsetY: 5,
            },
            {
                originX: 'end',
                originY: 'top',
                overlayX: 'end',
                overlayY: 'bottom',
                offsetY: -5,
            },
            {
                originX: 'start',
                originY: 'bottom',
                overlayX: 'end',
                overlayY: 'bottom',
                offsetX: -5,
            },
            {
                originX: 'start',
                originY: 'top',
                overlayX: 'end',
                overlayY: 'top',
                offsetX: -5,
            },
            {
                originX: 'center',
                originY: 'bottom',
                overlayX: 'center',
                overlayY: 'top',
                offsetY: 5,
            },
            {
                originX: 'center',
                originY: 'top',
                overlayX: 'center',
                overlayY: 'bottom',
                offsetY: -5,
            },
            {
                originX: 'start',
                originY: 'center',
                overlayX: 'end',
                overlayY: 'center',
                offsetX: -5,
            },
            {
                originX: 'end',
                originY: 'center',
                overlayX: 'start',
                overlayY: 'center',
                offsetX: 5,
            },
            {
                originX: 'center',
                originY: 'center',
                overlayX: 'center',
                overlayY: 'center',
            },
            {
                originX: 'start',
                originY: 'bottom',
                overlayX: 'start',
                overlayY: 'top',
                offsetY: 5,
            },
            {
                originX: 'start',
                originY: 'top',
                overlayX: 'start',
                overlayY: 'bottom',
                offsetY: -5,
            },
            {
                originX: 'end',
                originY: 'bottom',
                overlayX: 'end',
                overlayY: 'top',
                offsetY: 5,
            },
            {
                originX: 'end',
                originY: 'top',
                overlayX: 'end',
                overlayY: 'bottom',
                offsetY: -5,
            },
        ];

        const positionStrategy = this.overlay
            .position()
            .flexibleConnectedTo(target)
            .withFlexibleDimensions(true)
            .withPositions(positions);

        this.popupOverlayRef = this.overlay.create({
            positionStrategy,
            hasBackdrop: false,
            scrollStrategy: this.overlay.scrollStrategies.close(),
        });
        if (cell.columnId === 'agentData') {
            // Open the agent selection popup for the agentData column
            const portal = new ComponentPortal(AgentSelectionPopupComponent);
            const popupRef = this.popupOverlayRef.attach(portal);

            popupRef.instance.agents = this.agents; // Make sure the agents list is available in the component

            // Get the current agent from the cell if it exists
            if (this.currentPopupCell) {
                const rowIndex = this.currentPopupCell.rowIndex;
                const rowNode = this.gridApi.getDisplayedRowAtIndex(rowIndex);

                if (rowNode) {
                    const currentAgent = rowNode.data.agentData;
                    // Pass the currently selected agent to the popup component

                    popupRef.instance.selectedAgent = currentAgent;
                }
            }
            // Subscribe to the agentSelected event from the popup
            popupRef.instance.agentSelected.subscribe((selectedAgent: FullAgent | null) => {
                if (!this.currentPopupCell) return;
                const rowIndex = this.currentPopupCell.rowIndex;
                const rowNode = this.gridApi.getDisplayedRowAtIndex(rowIndex);
                if (!rowNode) return;
                const taskData = rowNode.data as TableFullTask;

                if (selectedAgent === null) {
                    this.updateTaskDataInRow(
                        {
                            agent: null,
                            agentData: null,
                        },
                        taskData
                    );
                } else {
                    this.updateTaskDataInRow(
                        {
                            agent: selectedAgent.id,
                            agentData: selectedAgent,
                        },
                        taskData
                    );
                }
                this.closePopup();
            });
        }

        if (cell.columnId === 'mergedTools') {
            const portal = new ComponentPortal(ToolsPopupComponent);
            const popupRef = this.popupOverlayRef.attach(portal);
            const rowNode = event.node;
            popupRef.instance.mergedTools = event.data?.mergedTools || [];

            popupRef.instance.mergedToolsUpdated.subscribe((updatedMergedTools) => {
                const mergedToolsClone = (updatedMergedTools ?? []).map((t) => ({ ...t }));
                const taskData = rowNode.data as TableFullTask;
                this.updateTaskDataInRow({ mergedTools: mergedToolsClone }, taskData);
                this.closePopup();
            });

            popupRef.instance.cancel.subscribe(() => {
                this.closePopup();
            });
        }

        // Use Renderer2 to attach a global click listener.
        this.globalClickUnlistener = this.renderer.listen('document', 'click', (evt: MouseEvent) =>
            this.onDocumentClick(evt)
        );

        // Attach a global keydown listener to close the popup on Escape key.
        this.globalKeydownUnlistener = this.renderer.listen('document', 'keydown', (evt: KeyboardEvent) => {
            if (evt.key === 'Escape') {
                this.closePopup();
            }
        });
    }

    private onDocumentClick(event: MouseEvent): void {
        const target = event.target as HTMLElement;
        if (
            this.popupOverlayRef &&
            this.currentCellElement &&
            !this.popupOverlayRef.overlayElement.contains(target) &&
            !this.currentCellElement.contains(target)
        ) {
            this.closePopup();
        }
    }

    private closePopup(): void {
        if (this.popupOverlayRef) {
            this.popupOverlayRef.dispose();
            this.popupOverlayRef = null;
        }
        this.currentPopupCell = null;

        // Remove the custom CSS class from the cell.
        if (this.currentCellElement) {
            this.renderer.removeClass(this.currentCellElement, 'popup-open');
            this.currentCellElement = null;
        }

        // Remove the global click listener if it exists.
        if (this.globalClickUnlistener) {
            this.globalClickUnlistener();
            this.globalClickUnlistener = null;
        }

        // Remove the global keydown listener if it exists.
        if (this.globalKeydownUnlistener) {
            this.globalKeydownUnlistener();
            this.globalKeydownUnlistener = null;
        }
    }

    public onCellContextMenu(event: CellContextMenuEvent) {
        if (!event.event) return;
        event.event.preventDefault();

        this.selectedRowData = event.data;
        const mouseEvent = event.event as MouseEvent;

        // Get the available space at the bottom of the screen
        const spaceBelow = window.innerHeight - mouseEvent.clientY;
        const menuHeight = 265; // Height of the context menu, you can adjust this based on the actual height

        // If there's not enough space below, position it above
        if (spaceBelow < menuHeight) {
            this.menuLeft = mouseEvent.clientX;
            this.menuTop = mouseEvent.clientY - menuHeight; // Position above the mouse
        } else {
            this.menuLeft = mouseEvent.clientX;
            this.menuTop = mouseEvent.clientY; // Position below the mouse
        }

        this.contextMenuVisible.set(true);
    }

    // private canMoveTask(draggedId: number, newOrder: number): boolean {
    //     const draggedTask = [...this.tasks].find(t => t.id === draggedId);
    //     if (!draggedTask) return false;

    //     // получаем индекс, куда хотим вставить таск
    //     const newIndex = [...this.tasks].findIndex(t => t.order === newOrder);
    //     const newHigherTasks = [...this.tasks].slice(0, newIndex).map(t => t.id);

    //     // все зависимости должны быть выше нового места
    //     const allDependenciesAbove = draggedTask.task_context_list.every(id => newHigherTasks.includes(id));

    //     return allDependenciesAbove;
    // }

    private hasLocalDirty = false;
    private markDirty(): void {
        if (this.hasLocalDirty) return;
        this.hasLocalDirty = true;
        this.dirtyChange.emit(true);
    }

    private emitReorderPending(): void {
        const displayedRows: TableFullTask[] = [];

        if (this.gridApi) {
            const count = this.gridApi.getDisplayedRowCount();
            for (let i = 0; i < count; i++) {
                const node = this.gridApi.getDisplayedRowAtIndex(i);
                if (node?.data) displayedRows.push(node.data as TableFullTask);
            }
        } else {
            displayedRows.push(...this.rowData);
        }

        const reorderPayload = displayedRows
            .filter((t) => t?.id)
            .filter((t) => !(typeof t.id === 'string' && t.id.startsWith('temp_')))
            .map((t, idx) => ({
                id: typeof t.id === 'string' ? Number(t.id) : t.id,
                order: idx,
            }));

        this.setPending('__ALL__', {
            rowKey: '__ALL__',
            kind: 'reorder',
            payload: reorderPayload,
        });
    }

    private isSameCellValue(a: unknown, b: unknown): boolean {
        return JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
    }

    private setPending(rowKey: string, ev: TaskPendingEvent | null): void {
        if (!ev) {
            this.localPendingKeys.delete(rowKey);
            this.taskPending.emit({ rowKey, kind: 'update', payload: null });
        } else {
            this.localPendingKeys.add(rowKey);
            this.taskPending.emit(ev);
        }

        const isDirty = this.localPendingKeys.size > 0 || this.localDraftTempKeys.size > 0;

        this.hasLocalDirty = isDirty;
        this.dirtyChange.emit(isDirty);
    }

    private normalizeIdList(ids: unknown): number[] {
        const arr = Array.isArray(ids) ? ids : [];

        const nums = arr.map((x) => Number(x)).filter((x): x is number => Number.isFinite(x));

        return Array.from(new Set(nums)).sort((a, b) => a - b);
    }

    private normalizeTaskForCompare(task: FullTask): unknown {
        const parsed = this.parseTaskData(task);

        return {
            id: parsed.id != null ? Number(parsed.id) : null,
            name: String(parsed.name ?? '').trim(),
            instructions: String(parsed.instructions ?? '').trim(),
            expected_output: String(parsed.expected_output ?? '').trim(),
            knowledge_query: parsed.knowledge_query ?? null,
            order: parsed.order ?? null,
            human_input: !!parsed.human_input,
            async_execution: !!parsed.async_execution,
            config: parsed.config ?? null,
            output_model: parsed.output_model ?? null,
            crew: parsed.crew ?? null,
            agent: parsed.agent ?? null,
            task_context_list: this.normalizeIdList(parsed.task_context_list),
            configured_tools: this.normalizeIdList(parsed.configured_tools),
            python_code_tools: this.normalizeIdList(parsed.python_code_tools),
            mcp_tools: this.normalizeIdList(parsed.mcp_tools),
        };
    }

    private jsonEqual(a: unknown, b: unknown): boolean {
        return JSON.stringify(a) === JSON.stringify(b);
    }

    private upsertPendingForExistingTask(taskData: TableFullTask): void {
        const isTemp = !taskData.id || (typeof taskData.id === 'string' && taskData.id.startsWith('temp_'));

        if (isTemp) return;

        const parsedUpdateData = this.parseTaskData(taskData as FullTask);
        const configured = parsedUpdateData.configured_tools || [];
        const python = parsedUpdateData.python_code_tools || [];
        const mcp = parsedUpdateData.mcp_tools || [];
        const toolIds = buildToolIdsArray(configured, python, mcp);

        const idNum = Number(parsedUpdateData.id);
        if (!Number.isFinite(idNum)) return;

        const parsedWithoutOrder = { ...parsedUpdateData };
        delete (parsedWithoutOrder as Record<string, unknown>)['order'];

        const updateTaskRequest: UpdateTaskRequest = {
            ...parsedWithoutOrder,
            id: idNum,
            knowledge_query: parsedUpdateData.knowledge_query ?? null,
            configured_tools: configured,
            python_code_tools: python,
            mcp_tools: mcp,
            tool_ids: toolIds,
        };

        const baseline = this.baselineTasksById.get(idNum);
        const currentNorm = this.normalizeTaskForCompare(taskData as FullTask);

        if (baseline && this.jsonEqual(currentNorm, baseline)) {
            this.setPending(String(idNum), null);
            return;
        }

        this.setPending(String(idNum), {
            rowKey: String(idNum),
            kind: 'update',
            payload: updateTaskRequest,
        });
    }

    public requiredErrorsRows = new Set<string>();
    private activeRowId: string | null = null;

    private readonly requiredTaskFields = ['name', 'instructions', 'expected_output'] as const;

    private isTempRowId(id: unknown): boolean {
        return typeof id === 'string' && id.startsWith('temp_');
    }

    private isRequiredEmpty(v: unknown): boolean {
        return v == null || String(v).trim() === '';
    }

    private isTempRowTouched(task: TableFullTask): boolean {
        if (!task) return false;
        const cur = this.normalizeTempTaskForTouch(task);
        const base = this.normalizeTempTaskForTouch(this.createEmptyTempTouchBaseline());
        return JSON.stringify(cur) !== JSON.stringify(base);
    }

    private normalizeTempTaskForTouch(task: unknown): unknown {
        const t = structuredClone((task ?? {}) as Partial<TableFullTask>);
        const text = (v: unknown) => (v == null ? '' : String(v)).trim();
        const nullableText = (v: unknown) => {
            const s = text(v);
            return s === '' ? null : s;
        };

        const agentId = t.agentData?.id ?? null;

        const toolsKey: string[] = Array.isArray(t.mergedTools)
            ? t.mergedTools
                  .map((x: { type?: unknown; id?: unknown }) => `${x?.type ?? ''}:${x?.id ?? ''}`)
                  .filter((s: string) => s !== ':')
                  .sort()
            : [];

        const ctxKey: string[] = Array.isArray(t.task_context_list)
            ? t.task_context_list
                  .map((x: unknown) =>
                      typeof x === 'object' && x !== null ? String((x as { id?: unknown }).id ?? '') : String(x ?? '')
                  )
                  .filter((s: string) => s !== '')
                  .sort()
            : [];

        return {
            name: text(t.name),
            instructions: text(t.instructions),
            expected_output: text(t.expected_output),
            knowledge_query: nullableText(t.knowledge_query),
            human_input: Boolean(t.human_input),
            async_execution: Boolean(t.async_execution),
            output_model: t.output_model ?? null,
            config: t.config ?? null,
            agentId,
            toolsKey,
            ctxKey,
        };
    }

    private createEmptyTempTouchBaseline(): Partial<TableFullTask> {
        return {
            name: '',
            instructions: '',
            expected_output: '',
            knowledge_query: null,
            human_input: false,
            async_execution: false,
            output_model: null,
            config: null,
            agentData: null,
            mergedTools: [],
            task_context_list: [],
        };
    }

    private isTempRowValid(data: unknown): boolean {
        const row = (data ?? {}) as Partial<TableFullTask>;
        return this.requiredTaskFields.every((f) => !this.isRequiredEmpty(row[f]));
    }

    private updateRequiredErrorsForTempRow(rowId: string, data: unknown): void {
        const row = data as TableFullTask;
        const shouldShow = this.isTempRowTouched(row) && !this.isTempRowValid(row);

        if (shouldShow) this.requiredErrorsRows.add(rowId);
        else this.requiredErrorsRows.delete(rowId);

        const node = this.gridApi?.getRowNode(rowId);
        if (node) {
            this.gridApi.refreshCells({
                rowNodes: [node],
                columns: [...this.requiredTaskFields],
                force: true,
            });
        }
    }

    private handleEnterJumpWithinTempRow(params: EnterJumpParams): boolean {
        const e = params.event as KeyboardEvent | undefined;
        if (!e) return false;
        if (e.key !== 'Enter') return false;
        if (e.shiftKey) return false;

        const data = params.node?.data;
        const rowId = String(data?.id ?? '');
        if (!this.isTempRowId(rowId)) return false;

        e.preventDefault();
        e.stopPropagation();

        if (e.type === 'keyup') return true;
        const colId = params.column?.getColId?.() ?? params.colDef?.field;
        const order = ['name', 'instructions', 'expected_output', 'knowledge_query'];
        const idx = order.indexOf(colId);

        this.gridApi.stopEditing();
        if (idx === -1) return true;
        const nextCol = order[idx + 1];

        setTimeout(() => {
            if (!nextCol) {
                this.updateRequiredErrorsForTempRow(rowId, data);
                return;
            }
            const rowIndex = params.node?.rowIndex;
            if (rowIndex == null) return;
            this.gridApi.startEditingCell({ rowIndex, colKey: nextCol });
        }, 0);

        return true;
    }

    @ViewChild('agGridWrap', { static: true }) agGridWrap!: ElementRef<HTMLElement>;

    @HostListener('document:mousedown', ['$event'])
    onDocumentMouseDown(ev: MouseEvent): void {
        if (!this.activeRowId) return;
        const wrap = this.agGridWrap?.nativeElement;
        if (!wrap) return;

        const target = ev.target as Node | null;
        if (!target || !wrap.contains(target)) {
            const node = this.gridApi?.getRowNode(this.activeRowId);
            if (node?.data) this.updateRequiredErrorsForTempRow(this.activeRowId, node.data);
            return;
        }

        const rowEl = (target as HTMLElement).closest('.ag-row');
        const clickedId = rowEl?.getAttribute('row-id') ?? null;

        if (clickedId && clickedId !== this.activeRowId) {
            const node = this.gridApi?.getRowNode(this.activeRowId);
            if (node?.data) this.updateRequiredErrorsForTempRow(this.activeRowId, node.data);
        }
    }

    public validateBeforeSave(): boolean {
        let ok = true;

        for (const row of this.rowData) {
            const id = String(row?.id ?? '');
            if (!this.isTempRowId(id)) continue;

            if (this.isTempRowTouched(row) && !this.isTempRowValid(row)) {
                this.requiredErrorsRows.add(id);
                ok = false;
                const node = this.gridApi?.getRowNode(id);
                if (node) {
                    this.gridApi.refreshCells({ rowNodes: [node], columns: [...this.requiredTaskFields], force: true });
                }
            }
        }
        return ok;
    }

    public clearLocalDirtyAfterSave(): void {
        this.localPendingKeys.clear();
        this.localDraftTempKeys.clear();
        this.requiredErrorsRows.clear();
        this.hasLocalDirty = false;
        this.dirtyChange.emit(false);
        this.gridApi?.refreshCells({ force: true });
        this.cdr.markForCheck();
    }

    public hasLocalDrafts(): boolean {
        return this.localDraftTempKeys.size > 0;
    }

    public applyCreatedTask(tempRowKey: string, created: { id: number } & Partial<TableFullTask>): void {
        const idx = this.rowData.findIndex((t) => String(t.id) === tempRowKey);
        if (idx === -1) return;
        const oldRow = this.rowData[idx];

        const newRow: TableFullTask = {
            ...oldRow,
            ...created,
            id: Number(created.id),
        };

        this.rowData.splice(idx, 1, newRow);
        this.gridApi?.applyTransaction({
            remove: [oldRow],
            add: [newRow],
            addIndex: idx,
        });

        this.localDraftTempKeys?.delete(tempRowKey);
        this.requiredErrorsRows?.delete(tempRowKey);
        this.localPendingKeys?.delete(tempRowKey);

        this.baselineTasksById?.set(Number(created.id), this.normalizeTaskForCompare(newRow as FullTask));

        this.projectStateService.addTask(newRow as FullTask);
        this.reindexAndSyncPendingOrders();
        this.cdr.markForCheck();
    }

    public applyUpdatedTask(rowKey: string, updated: Partial<TableFullTask>): void {
        const idx = this.rowData.findIndex((t) => String(t.id) === rowKey);
        if (idx === -1) return;
        const oldRow = this.rowData[idx];

        const newRow: TableFullTask = { ...oldRow, ...updated };
        this.rowData.splice(idx, 1, newRow);
        this.gridApi?.applyTransaction({ update: [newRow] });

        this.baselineTasksById?.set(Number(newRow.id), this.normalizeTaskForCompare(newRow as FullTask));
        this.cdr.markForCheck();
    }

    public getCurrentReorderPayload(): Array<{ id: number; order: number }> {
        const displayedRows: TableFullTask[] = [];

        if (this.gridApi) {
            const count = this.gridApi.getDisplayedRowCount();
            for (let i = 0; i < count; i++) {
                const node = this.gridApi.getDisplayedRowAtIndex(i);
                if (node?.data) {
                    displayedRows.push(node.data as TableFullTask);
                }
            }
        } else {
            displayedRows.push(...this.rowData);
        }

        return displayedRows
            .filter((t) => t?.id != null)
            .filter((t) => !(typeof t.id === 'string' && t.id.startsWith('temp_')))
            .map((t, idx) => ({
                id: typeof t.id === 'string' ? Number(t.id) : t.id,
                order: idx,
            }))
            .filter((x) => Number.isFinite(x.id));
    }

    private maybeClearReorderPending(): void {
        const displayedRows: TableFullTask[] = [];

        if (this.gridApi) {
            const count = this.gridApi.getDisplayedRowCount();
            for (let i = 0; i < count; i++) {
                const node = this.gridApi.getDisplayedRowAtIndex(i);
                if (node?.data) displayedRows.push(node.data as TableFullTask);
            }
        } else {
            displayedRows.push(...this.rowData);
        }

        const displayedPayload = displayedRows
            .filter((t) => t?.id != null)
            .filter((t) => !(typeof t.id === 'string' && t.id.startsWith('temp_')))
            .map((t, idx) => ({
                id: typeof t.id === 'string' ? Number(t.id) : t.id,
                order: idx,
            }))
            .filter((x) => Number.isFinite(x.id));

        const baselinePayload = this.tasks
            .filter((t) => typeof t.id === 'number' && t.order != null)
            .sort((a, b) => (a.order ?? 999999) - (b.order ?? 999999))
            .map((t, idx) => ({ id: t.id, order: idx }));

        const same = JSON.stringify(displayedPayload) === JSON.stringify(baselinePayload);
        if (same) this.setPending('__ALL__', null);
    }

    private syncAgentsInCurrentRows(): void {
        const validAgentIds = new Set((this.agents ?? []).map((a) => Number(a.id)));

        let changed = false;

        this.rowData = this.rowData.map((row) => {
            const rowAgentId =
                row.agentData?.id != null ? Number(row.agentData.id) : row.agent != null ? Number(row.agent) : null;

            const hasAgent = rowAgentId != null && Number.isFinite(rowAgentId);

            const isValidAgent = hasAgent && validAgentIds.has(rowAgentId!);

            if (!hasAgent || isValidAgent) {
                return row;
            }

            changed = true;

            const updatedRow: TableFullTask = {
                ...row,
                agentData: null,
                agent: null,
            };

            const isTemp = typeof updatedRow.id === 'string' && updatedRow.id.startsWith('temp_');

            if (!isTemp) {
                this.upsertPendingForExistingTask(updatedRow);
            }

            return updatedRow;
        });

        if (!changed) return;
    }

    private reindexAndSyncPendingOrders(): void {
        const displayedRows: TableFullTask[] = [];

        if (this.gridApi) {
            const count = this.gridApi.getDisplayedRowCount();
            for (let i = 0; i < count; i++) {
                const node = this.gridApi.getDisplayedRowAtIndex(i);
                if (node?.data) {
                    node.data.order = i;
                    displayedRows.push(node.data as TableFullTask);
                }
            }
        } else {
            this.rowData.forEach((row, i) => {
                row.order = i;
                displayedRows.push(row);
            });
        }

        this.rowData = [...displayedRows];

        for (const row of this.rowData) {
            const rowKey = String(row.id ?? '');
            if (!rowKey.startsWith('temp_')) continue;
            if (!this.isTempRowTouched(row)) continue;
            if (!this.isTempRowValid(row)) continue;
            const parsedData = this.parseTaskData(row as FullTask);
            const configuredToolIds = parsedData.configured_tools || [];
            const pythonToolIds = parsedData.python_code_tools || [];
            const mcpToolIds = parsedData.mcp_tools || [];
            const toolIds = buildToolIdsArray(configuredToolIds, pythonToolIds, mcpToolIds);

            const createTaskData: CreateTaskRequest = {
                ...parsedData,
                knowledge_query: parsedData.knowledge_query ?? null,
                order: row.order ?? null,
                human_input: parsedData.human_input ?? false,
                async_execution: parsedData.async_execution ?? false,
                config: parsedData.config ?? null,
                output_model: parsedData.output_model ?? null,
                task_context_list: parsedData.task_context_list ?? [],
                configured_tools: configuredToolIds,
                python_code_tools: pythonToolIds,
                mcp_tools: mcpToolIds,
                tool_ids: toolIds,
            };

            this.setPending(rowKey, {
                rowKey,
                kind: 'create',
                payload: createTaskData,
            });
        }

        this.gridApi?.setGridOption('rowData', [...this.rowData]);
        this.gridApi?.refreshCells({
            force: true,
            columns: ['index', 'order'],
        });

        this.emitReorderPending();
    }

    public getCurrentRows(): TableFullTask[] {
        return [...this.rowData];
    }
}
