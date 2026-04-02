import { Dialog, DialogModule } from '@angular/cdk/dialog';
import { ConnectedPosition, Overlay, OverlayRef } from '@angular/cdk/overlay';
import { ComponentPortal } from '@angular/cdk/portal';
import { NgIf } from '@angular/common';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    ElementRef,
    EventEmitter,
    HostListener,
    Input,
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
    CellEditingStoppedEvent,
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
import { catchError, concatMap, EMPTY, finalize, from, map, Observable, of, switchMap, tap, toArray } from 'rxjs';

import { CreateAgentRequest, ToolUniqueName, UpdateAgentRequest } from '../../../../features/staff/models/agent.model';
import {
    FullAgent,
    FullAgentService,
    MergedConfig,
    TableFullAgent,
} from '../../../../features/staff/services/full-agent.service';
import { RealtimeAgentService } from '../../../../features/staff/services/realtime-agent.service';
import { AgentsService } from '../../../../features/staff/services/staff.service';
import { ToastService } from '../../../../services/notifications/toast.service';
import { SpinnerComponent } from '../../../../shared/components/spinner/spinner.component';
import { ClickOutsideDirective } from '../../../../shared/directives/click-outside.directive';
import { buildToolIdsArray } from '../../../../shared/utils/tool-ids-builder.util';
import {
    AdvancedSettingsData,
    AdvancedSettingsDialogComponent,
} from '../advanced-settings-dialog.component.ts/advanced-settings-dialog.component';
import { LLMPopupComponent } from '../cell-popups-and-modals/llm-selector-popup/llm-popup.component';
import { TagsPopupComponent } from '../cell-popups-and-modals/tags-popup/tags-popup.component';
import { ToolsPopupComponent } from '../cell-popups-and-modals/tools-selector-popup/tools-popup.component';
import { IndexCellRendererComponent } from '../cell-renderers/index-row-cell-renderer/custom-row-height.component';
import { ConfigCellRendererComponent } from '../cell-renderers/llm-cell-renderer/realtime-config-cell-renderer.component';
import { AgGridContextMenuComponent } from '../context-menu/ag-grid-context-menu.component';
import { PreventContextMenuDirective } from '../directives/prevent-context-menu.directive';
import { DelegationHeaderComponent } from '../header-renderers/delegation-header.component';

ModuleRegistry.registerModules([AllCommunityModule]);

interface CellInfo {
    columnId: string;
    rowIndex: number;
}
type PopupEvent = CellClickedEvent<TableFullAgent, unknown> | CellKeyDownEvent<TableFullAgent, unknown>;
type AgentRequiredField = 'role' | 'goal' | 'backstory';
const isAgentRequiredField = (field: string): field is AgentRequiredField =>
    field === 'role' || field === 'goal' || field === 'backstory';

type PendingKind = 'create' | 'update' | 'delete';

interface PendingChange {
    kind: PendingKind;
    rowId: string;
    payload?: CreateAgentRequest | UpdateAgentRequest;
}

@Component({
    selector: 'app-agents-table',
    standalone: true,
    imports: [
        AgGridModule,
        DialogModule,
        ClickOutsideDirective,
        PreventContextMenuDirective,
        AgGridContextMenuComponent,
        NgIf,
        SpinnerComponent,
    ],
    templateUrl: './agents-table.component.html',
    styleUrls: ['./agents-table.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AgentsTableComponent {
    @Input() newAgent: FullAgent | null = null;
    @Input() isSaving = false;
    private gridApi!: GridApi;

    public isLoading = signal<boolean>(true);
    private loadStartTime: number = 0;
    public rowData: TableFullAgent[] = [];
    private copiedRowData: TableFullAgent | null = null;
    //context-menu
    public contextMenuVisible = signal(false);
    menuLeft = 0;
    menuTop = 0;
    private selectedRowData: TableFullAgent | null = null;

    //overlay
    private popupOverlayRef: OverlayRef | null = null;
    private currentPopupCell: CellInfo | null = null;
    private currentCellElement: HTMLElement | null = null;
    private globalClickUnlistener: (() => void) | null = null;
    private globalKeydownUnlistener: (() => void) | null = null;

    @Output() dirtyChange = new EventEmitter<boolean>();
    private pending = new Map<string, PendingChange>();
    private savedSnapshot = new Map<string, unknown>();
    private deletedRows = new Map<string, { row: TableFullAgent; index: number }>();

    @ViewChild('agGridWrap', { static: true }) agGridWrap!: ElementRef<HTMLElement>;
    private activeRowId: string | null = null;

    constructor(
        private overlay: Overlay,
        private cdr: ChangeDetectorRef,
        private fullAgentService: FullAgentService,
        private agentsService: AgentsService,
        private renderer: Renderer2,
        private toastService: ToastService,
        private realtimeAgentService: RealtimeAgentService,
        public dialog: Dialog
    ) {}

    ngOnInit(): void {
        this.loadStartTime = Date.now();

        this.fullAgentService.getFullAgents().subscribe({
            next: (data: FullAgent[]) => {
                // Sort and set data
                this.rowData = data.sort((a, b) => b.id - a.id);

                for (const a of this.rowData) {
                    const rowId = String(a.id);
                    if (!rowId.startsWith('temp_')) {
                        this.savedSnapshot.set(rowId, this.buildComparablePayload(a));
                    }
                }

                this.ensureSingleSpareEmptyRow();

                this.cdr.markForCheck();
            },
            error: (err) => {
                console.error('Error fetching agents:', err);
                this.cdr.markForCheck();
            },
        });
    }
    ngOnChanges(changes: SimpleChanges): void {
        if (changes['isSaving']?.currentValue) {
            this.closePopup();
            this.closeContextMenu();
            this.gridApi?.stopEditing();
        }

        if (changes['newAgent'] && changes['newAgent'].currentValue && !changes['newAgent'].firstChange) {
            const newAgent = changes['newAgent'].currentValue as FullAgent;

            if (this.gridApi) {
                this.rowData.unshift(newAgent);

                this.gridApi.applyTransaction({ add: [newAgent], addIndex: 0 });

                this.gridApi.ensureIndexVisible(0, 'top');

                setTimeout(() => {
                    // Get the first row node
                    const rowNode = this.gridApi.getDisplayedRowAtIndex(0);
                    if (rowNode) {
                        const column = this.gridApi.getColumnDef('role');
                        if (column) {
                            this.gridApi.setFocusedCell(0, 'role');
                        }
                    }
                }, 0);

                this.cdr.markForCheck();
            } else {
                console.error('Grid API not available when trying to add new agent');

                this.rowData.unshift(newAgent);
                this.cdr.markForCheck();
            }
        }
    }
    public onGridReady(params: GridReadyEvent): void {
        this.gridApi = params.api;
        this.gridApi.setGridOption('rowData', [...this.rowData]);
        this.gridApi.refreshCells({ force: true, columns: ['index'] });
        this.cdr.markForCheck();
    }

    private createEmptyFullAgent(): TableFullAgent {
        const tempId = `temp_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

        return {
            id: tempId,
            role: '',
            goal: '',
            backstory: '',
            configured_tools: [],
            python_code_tools: [],
            mcp_tools: [],
            llm_config: null,
            fcm_llm_config: null,
            allow_delegation: false,
            memory: false,
            max_iter: 20,
            max_rpm: 10,
            max_execution_time: 60,
            cache: false,
            allow_code_execution: false,
            max_retry_limit: 0,
            respect_context_window: false,
            default_temperature: null,
            tags: [],
            knowledge_collection: null,
            rag: null,
            tools: [],
            search_configs: {
                naive: {
                    search_limit: 3,
                    similarity_threshold: 0.2,
                },
            },
            // Replace realtime_config with realtime_agent object using provided defaults
            realtime_agent: {
                wake_word: '',
                stop_prompt: 'stop',
                language: null,
                voice_recognition_prompt: null,
                voice: 'alloy',
                realtime_config: null,
                realtime_transcription_config: null,
            },
            // Additional fields from FullAgent
            fullLlmConfig: undefined,
            fullFcmLlmConfig: undefined,
            fullRealtimeConfig: undefined,
            fullConfiguredTools: [],
            fullPythonTools: [],
            fullMcpTools: [],
            mergedTools: [],
            mergedConfigs: [],
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
            cellRenderer: IndexCellRendererComponent,
            editable: false,
            width: 50,
            minWidth: 50,
            maxWidth: 50,
        },

        {
            headerName: 'Agent Role',
            field: 'role',
            headerClass: 'required-header',
            cellClass: 'agent-role-cell',
            cellEditor: 'agLargeTextCellEditor',
            cellEditorPopup: true,
            suppressKeyboardEvent: (params) => this.handleEnterJumpWithinTempRow(params),
            cellEditorParams: {
                maxLength: 1000000,
                cellEditorValidator: (value: string) => {
                    if (!value || value.trim() === '') {
                        return {
                            valid: false,
                            message: 'Role cannot be empty (cell will not be saved).',
                        };
                    }
                    return { valid: true };
                },
            },
            valueSetter: (params) => {
                params.data.role = params.newValue;
                return true;
            },
            cellClassRules: {
                //'cell-warning': (params) => !!params.data.roleWarning,
                'cell-warning': (p) => !this.isTempRowId(String(p.data?.id ?? '')) && !!p.data.roleWarning,
                'cell-required-invalid': (p) => {
                    const id = String(p.data?.id ?? '');
                    if (!id.startsWith('temp_')) return false;
                    if (!this.requiredErrorsRows.has(id)) return false;
                    return String(p.value ?? '').trim().length === 0;
                },
            },
            cellStyle: {
                'white-space': 'normal',
                'text-align': 'left',
                'font-size': '14px',
            },
            flex: 1,
            minWidth: 190,
            maxWidth: 400,
            //   rowDrag: true,
            editable: () => !this.shouldBlockInteraction(),
        },
        {
            headerName: 'Goal',
            field: 'goal',
            headerClass: 'required-header',
            cellEditor: 'agLargeTextCellEditor',
            cellEditorPopup: true,
            suppressKeyboardEvent: (params) => this.handleEnterJumpWithinTempRow(params),
            cellEditorParams: {
                maxLength: 1000000,
                cellEditorValidator: (value: string) => {
                    if (!value || value.trim() === '') {
                        return {
                            valid: false,
                            message: 'Goal cannot be empty.',
                        };
                    }
                    return { valid: true };
                },
            },
            valueSetter: (params) => {
                params.data.goal = params.newValue;
                return true;
            },
            cellClassRules: {
                //'cell-warning': (params) => !!params.data.goalWarning,
                'cell-warning': (p) => !this.isTempRowId(String(p.data?.id ?? '')) && !!p.data.goalWarning,
                'cell-required-invalid': (p) => {
                    const id = String(p.data?.id ?? '');
                    if (!id.startsWith('temp_')) return false;
                    if (!this.requiredErrorsRows.has(id)) return false;
                    return String(p.value ?? '').trim().length === 0;
                },
            },
            cellStyle: {
                'white-space': 'normal',
                'text-align': 'left',
                'font-size': '14px',
            },
            flex: 1,
            minWidth: 280,

            editable: () => !this.shouldBlockInteraction(),
        },
        {
            headerName: 'Backstory',
            field: 'backstory',
            headerClass: 'required-header',
            cellEditor: 'agLargeTextCellEditor',
            cellEditorPopup: true,
            suppressKeyboardEvent: (params) => this.handleEnterJumpWithinTempRow(params),
            cellEditorParams: {
                maxLength: 1000000,
                cellEditorValidator: (value: string) => {
                    if (!value || value.trim() === '') {
                        return {
                            valid: false,
                            message: 'Backstory cannot be empty.',
                        };
                    }
                    return { valid: true };
                },
            },
            valueSetter: (params) => {
                params.data.backstory = params.newValue;
                return true;
            },
            cellClassRules: {
                //'cell-warning': (params) => !!params.data.backstoryWarning,
                'cell-warning': (p) => !this.isTempRowId(String(p.data?.id ?? '')) && !!p.data.backstoryWarning,
                'cell-required-invalid': (p) => {
                    const id = String(p.data?.id ?? '');
                    if (!id.startsWith('temp_')) return false;
                    if (!this.requiredErrorsRows.has(id)) return false;
                    return String(p.value ?? '').trim().length === 0;
                },
            },
            cellStyle: {
                'white-space': 'normal',
                'text-align': 'left',
                'font-size': '14px',
            },
            flex: 1,
            minWidth: 280,

            editable: () => !this.shouldBlockInteraction(),
        },

        {
            headerName: 'Delegation',

            headerComponent: DelegationHeaderComponent,
            field: 'allow_delegation',
            cellRenderer: 'agCheckboxCellRenderer',
            cellEditor: 'agCheckboxCellEditor',
            editable: true,
            cellClass: 'memory-checkbox',
            width: 50,
            minWidth: 50,
            maxWidth: 50,
        },
        // {
        //   headerName: 'Memory',

        //   headerComponent: MemoryHeaderComponent,
        //   field: 'memory',
        //   cellRenderer: 'agCheckboxCellRenderer',
        //   cellEditor: 'agCheckboxCellEditor',
        //   editable: true,
        //   cellClass: 'memory-checkbox',
        //   width: 50,
        //   minWidth: 50,
        //   maxWidth: 50,
        // },
        {
            headerName: 'LLMs',
            field: 'mergedConfigs',
            editable: false,
            flex: 1,
            minWidth: 220,
            maxWidth: 400,
            cellRenderer: ConfigCellRendererComponent,
        },
        {
            headerName: 'Tools',
            field: 'mergedTools',
            editable: false,
            flex: 1,
            minWidth: 200,
            maxWidth: 400,
            cellRenderer: (params: { value: { configName: string; toolName: string; type: string }[] }) => {
                const tools = params.value || [];

                if (!tools || tools.length === 0) {
                    return '<div class="no-tools">No tools assigned</div>';
                }

                const toolsHtml = tools
                    .map((tool: { configName: string; toolName: string; type: string }) => {
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
        // {
        //   headerName: 'Tags',
        //   field: 'tags',
        //   cellClass: 'tags-cell-wrapper',
        //   cellRenderer: (params: ICellRendererParams) => {
        //     return params.value
        //       .map((tag: string) => {

        //         const cleanTag: string = tag.replace('#', '').toLowerCase();
        //         return `<span class="tag tag-${cleanTag}" >#${tag}</span>`;
        //       })
        //       .join(' ');
        //   },

        //   flex: 1,
        //   minWidth: 160,
        //   maxWidth: 170,
        //   editable: false,
        // },
        {
            headerName: '',
            field: 'actions',
            cellRenderer: () => {
                return `<i class="ti ti-settings action-icon"></i>`;
            },
            width: 50,
            minWidth: 50,
            maxWidth: 50,
            cellClass: 'action-cell',

            editable: false,
        },
        {
            headerName: '',
            field: 'copy',
            cellRenderer: () => {
                return `<i class="ti ti-copy action-icon"></i>`;
            },
            width: 50,
            minWidth: 50,
            maxWidth: 50,
            cellClass: 'action-cell',

            editable: false,
        },
    ];

    public defaultColDef: ColDef = {
        headerClass: 'global-header-class',
        sortable: false, // Disable sorting for all columns
        resizable: false, // Disable column resizing
        wrapText: true,
        suppressMovable: true,
    };

    gridOptions: GridOptions = {
        rowHeight: 108,
        headerHeight: 50,
        columnDefs: this.columnDefs,
        undoRedoCellEditing: true,
        undoRedoCellEditingLimit: 20,
        theme: this.myTheme,
        animateRows: false,
        onCellFocused: (e) => this.onCellFocused(e),

        suppressColumnVirtualisation: false, // Enable column virtualization for performance
        stopEditingWhenCellsLoseFocus: true,

        rowClassRules: {
            'row-invalid': (p) => this.invalidTempRows.has(String(p.data?.id)),
        },

        onCellEditingStopped: (e) => this.onCellEditingStopped(e),

        onFirstDataRendered: () => {
            this.isLoading.set(false);
        },
        getRowId: (params) => {
            const id = params.data?.id;
            if (typeof id === 'string' && id.startsWith('temp_')) return id;
            if (id !== null && id !== undefined) return String(id);
            return `temp_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
        },
        onCellClicked: (event: CellClickedEvent<TableFullAgent, unknown>) => this.onCellClicked(event),
        onCellKeyDown: (event: CellKeyDownEvent) => this.onCellKeyDown(event),
        onCellValueChanged: (event) => this.onCellValueChanged(event),
        onRowDragEnd: (event) => this.onRowDragEnd(event),
    };

    onRowDragEnd(event: RowDragEndEvent) {
        if (this.shouldBlockInteraction()) return;
        // Get the moved data
        const movedData = event.node.data;
        const index = this.rowData.findIndex((row) => row === movedData);

        if (index !== -1) {
            // Remove the row from its old position
            this.rowData.splice(index, 1);
            // Insert it into the new position
            this.rowData.splice(event.overIndex, 0, movedData);

            // Force update the index column
            this.gridApi.refreshCells({
                force: true,
                columns: ['index'],
            });

            // Mark for check to trigger change detection
            this.cdr.markForCheck();
        }
    }

    // Function to parse the necessary fields (merged tools and config)
    private parseAgentData = (agentData: TableFullAgent) => {
        // Extract LLM config ID and realtime config ID from mergedConfigs
        let llmConfigId = null;
        let realtimeConfigId = null;

        // Check if mergedConfigs exist and process them
        if (agentData.mergedConfigs && Array.isArray(agentData.mergedConfigs)) {
            // Find LLM config
            const llmConfig = agentData.mergedConfigs.find((config: MergedConfig) => config.type === 'llm');
            if (llmConfig) {
                llmConfigId = llmConfig.id;
            }

            // Find realtime config
            const realtimeConfig = agentData.mergedConfigs.find((config: MergedConfig) => config.type === 'realtime');
            if (realtimeConfig) {
                realtimeConfigId = realtimeConfig.id;
            }
        } else {
            // Fallback to direct fields if mergedConfigs isn't available
            llmConfigId = agentData.fullLlmConfig?.id || null;
        }

        // Process merged tools
        const mergedTools = agentData.mergedTools || [];

        // Create or update the realtime_agent object
        const realtime_agent = {
            ...(agentData.realtime_agent || {}),
            realtime_config: realtimeConfigId,
            // Include other realtime_agent properties if they exist in agentData
            wake_word: agentData.realtime_agent?.wake_word,
            stop_prompt: agentData.realtime_agent?.stop_prompt,
            language: agentData.realtime_agent?.language,
            voice_recognition_prompt: agentData.realtime_agent?.voice_recognition_prompt,
            voice: agentData.realtime_agent?.voice,
            realtime_transcription_config: agentData.realtime_agent?.realtime_transcription_config,
        };

        const parsed = {
            ...agentData,
            llm_config: llmConfigId,
            fcm_llm_config: agentData.fullFcmLlmConfig?.id ?? agentData.fcm_llm_config ?? llmConfigId,
            realtime_agent: realtime_agent, // Use the properly structured realtime_agent object
            configured_tools: mergedTools
                .filter((tool: { id: number; type: string }) => tool.type === 'tool-config')
                .map((tool: { id: number; type: string }) => tool.id),
            python_code_tools: mergedTools
                .filter((tool: { id: number; type: string }) => tool.type === 'python-tool')
                .map((tool: { id: number; type: string }) => tool.id),
            mcp_tools: mergedTools
                .filter((tool: { id: number; type: string }) => tool.type === 'mcp-tool')
                .map((tool: { id: number; type: string }) => tool.id),
        };

        // Delete tools field to ensure it's never included in create/update requests
        delete (parsed as Record<string, unknown>)['tools'];
        delete (parsed as Record<string, unknown>)['fullFcmLlmConfig'];
        delete (parsed as Record<string, unknown>)['selected_knowledge_source'];

        return parsed;
    };

    private onCellValueChanged(event: CellValueChangedEvent<TableFullAgent>): void {
        if (this.shouldBlockInteraction()) {
            this.gridApi.stopEditing();
            return;
        }
        const colId = event.column.getColId();
        const fieldsToValidate: AgentRequiredField[] = ['role', 'goal', 'backstory'];
        const row = event.data as TableFullAgent & Record<string, unknown>;

        // If the row has a temporary ID (starts with 'temp_') or null id, create a new agent after validation
        const isTempRow = !row.id || (typeof row.id === 'string' && row.id.startsWith('temp_'));

        if (isTempRow) {
            if (isAgentRequiredField(colId)) {
                const value = row[colId];
                const newValue = value ? String(value).trim() : '';
                row[`${colId}Warning`] = !newValue;
            }

            const rowId = String(row.id);

            const touched = this.isTempRowTouched(row);

            if (!touched) {
                this.draftTempRows.delete(rowId);
                this.pending.delete(rowId);
                this.markRowInvalid(rowId, false);
                this.emitDirty();
                this.cdr.markForCheck();
                this.requiredErrorsRows.delete(rowId);
                this.gridApi.refreshCells({
                    rowNodes: [event.node],
                    columns: ['role', 'goal', 'backstory'],
                    force: true,
                });
                return;
            }

            if (touched) {
                this.draftTempRows.add(rowId);
            } else {
                this.draftTempRows.delete(rowId);
                if (this.pending.has(rowId)) this.pending.delete(rowId);
            }

            this.emitDirty();

            const isValid = fieldsToValidate.every((field) => {
                const fieldValue = row[field] ? String(row[field]).trim() : '';
                return fieldValue !== '';
            });

            if (!isValid) {
                console.warn('Warning: One or more required fields (role, goal, backstory) are empty.');

                if (this.pending.has(rowId)) this.pending.delete(rowId);

                this.emitDirty();
                this.cdr.markForCheck();
                return;
            }

            const parsedData = this.parseAgentData(row);
            const configuredToolIds = parsedData.configured_tools || [];
            const pythonToolIds = parsedData.python_code_tools || [];
            const mcpToolIds = parsedData.mcp_tools || [];
            const toolIds = buildToolIdsArray(configuredToolIds, pythonToolIds, mcpToolIds);

            const createAgentData: CreateAgentRequest = {
                ...parsedData,
                configured_tools: configuredToolIds,
                python_code_tools: pythonToolIds,
                mcp_tools: mcpToolIds,
                tool_ids: toolIds,
            };

            this.setPending(rowId, {
                kind: 'create',
                rowId,
                payload: createAgentData,
            });

            this.draftTempRows.delete(rowId);
            this.emitDirty();
            this.ensureSingleSpareEmptyRow();
            this.gridApi.setGridOption('rowData', [...this.rowData]);
            this.gridApi.refreshCells({ force: true, columns: ['index'] });
            this.cdr.markForCheck();
            return;
        }

        // For rows with a valid id, validate all fields that require validation
        let allValid = true; // Flag to check if all fields are valid
        fieldsToValidate.forEach((field) => {
            const fieldValue = row[field] ? String(row[field]).trim() : '';
            row[`${field}Warning`] = !fieldValue;

            // If any field is invalid, mark as invalid
            if (!fieldValue) {
                allValid = false;
            }
        });

        // Refresh only the edited cell
        this.gridApi.refreshCells({
            rowNodes: [event.node],
            columns: [colId],
        });

        // If any required field is empty, log a warning and do not proceed with saving
        if (!allValid) {
            console.warn(
                'Warning: One or more required fields (role, goal, backstory) are empty. Row will not be saved to the backend.'
            );
            return; // Prevent saving the row
        }

        // Parse the agent data
        const parsedUpdateData = this.parseAgentData(row);

        // Build tool_ids array for update
        const updateConfiguredToolIds = parsedUpdateData.configured_tools || [];
        const updatePythonToolIds = parsedUpdateData.python_code_tools || [];
        const updateMcpToolIds = parsedUpdateData.mcp_tools || [];
        const updateToolIds = buildToolIdsArray(updateConfiguredToolIds, updatePythonToolIds, updateMcpToolIds);

        // Update the agent using the id if all fields are valid
        const updateAgentData: UpdateAgentRequest = {
            ...parsedUpdateData,
            id: Number(row.id),
            configured_tools: updateConfiguredToolIds,
            python_code_tools: updatePythonToolIds,
            mcp_tools: updateMcpToolIds,
            tool_ids: updateToolIds,
        };

        const rowId = String(row.id);

        this.reconcilePendingUpdate(rowId, updateAgentData);
        this.cdr.markForCheck();
    }

    ngOnDestroy(): void {
        this.closePopup();
    }

    openSettingsDialog(agentData: TableFullAgent) {
        if (this.shouldBlockInteraction()) return;
        const before = this.normalizeAdvancedSettings(agentData);
        const dialogRef = this.dialog.open(AdvancedSettingsDialogComponent, {
            disableClose: true,
            data: {
                id: agentData.id,
                agentRole: agentData.role,
                fullFcmLlmConfig: agentData.fullFcmLlmConfig,
                max_iter: agentData.max_iter ?? 20,
                max_rpm: agentData.max_rpm ?? 10,
                max_execution_time: agentData.max_execution_time ?? 60,
                cache: agentData.cache ?? false,
                allow_code_execution: agentData.allow_code_execution ?? false,
                max_retry_limit: agentData.max_retry_limit ?? null,
                respect_context_window: agentData.respect_context_window ?? false,
                default_temperature: null,
                knowledge_collection: agentData.knowledge_collection ?? null, // Changed parameter name
                rag: agentData.rag ?? null,
                search_configs: {
                    naive: {
                        similarity_threshold: agentData.search_configs?.naive?.similarity_threshold ?? null,
                        search_limit: agentData.search_configs?.naive?.search_limit ?? null,
                    },
                },
                memory: agentData.memory ?? true,
            },
        });

        dialogRef.closed.subscribe((updatedData: unknown) => {
            const data = updatedData as AdvancedSettingsData | undefined;
            if (!data) return;
            const after = this.normalizeAdvancedSettings(data as unknown as TableFullAgent);
            if (this.jsonEqual(before, after)) return;
            this.updateAgentDataInRow(data, agentData);

            const rowId = String(agentData.id ?? '');
            const rowNode = this.gridApi?.getRowNode(rowId);
            const fresh = rowNode?.data;

            if (fresh) {
                this.updateRequiredErrorsForTempRow(rowId, fresh);
            }
        });
    }

    updateAgentDataInRow(updatedData: Partial<TableFullAgent>, agentData: TableFullAgent): void {
        if (this.shouldBlockInteraction()) return;

        const index = this.rowData.findIndex((agent) => agent.id === agentData.id);
        if (index === -1) {
            console.error('Agent not found in rowData for update:', agentData);
            return;
        }

        // Create an updated version of the agent using both existing values and updated fields
        const updatedAgent: TableFullAgent = {
            ...this.rowData[index],
            ...updatedData,
        };

        // Update our local row data
        this.rowData[index] = updatedAgent;

        // Use transaction API to update the grid
        this.gridApi.applyTransaction({ update: [updatedAgent] });

        // Mark for check due to OnPush change detection
        this.cdr.markForCheck();

        // Check if this is a temporary row or one with a real ID
        // Get realtime config ID - check mergedConfigs FIRST as it's the source of truth
        let realtimeConfigId = null;

        // First check mergedConfigs if available (most up-to-date)
        if (updatedAgent.mergedConfigs && Array.isArray(updatedAgent.mergedConfigs)) {
            const realtimeConfig = updatedAgent.mergedConfigs.find((config) => config.type === 'realtime');
            if (realtimeConfig) {
                realtimeConfigId = realtimeConfig.id;
            }
        }
        // Fallback to fullRealtimeConfig if mergedConfigs doesn't exist
        else if (updatedAgent.fullRealtimeConfig?.id) {
            realtimeConfigId = updatedAgent.fullRealtimeConfig.id;
        }
        // Finally check the realtime_agent.realtime_config field directly
        else if (updatedAgent.realtime_agent?.realtime_config) {
            realtimeConfigId = updatedAgent.realtime_agent.realtime_config;
        }

        // Create or update the realtime_agent object
        const realtime_agent = {
            ...(updatedAgent.realtime_agent || {
                wake_word: '',
                stop_prompt: 'stop',
                language: null,
                voice_recognition_prompt: null,
                voice: 'alloy',
                realtime_transcription_config: null,
            }),
            realtime_config: realtimeConfigId,
        };

        const allToolsPreBuilding = {
            configured_tools: this.rowData[index].mergedTools
                .filter((tool: { id: number; type: string }) => tool.type === 'tool-config')
                .map((tool: { id: number; type: string }) => tool.id),
            python_code_tools: this.rowData[index].mergedTools
                .filter((tool: { id: number; type: string }) => tool.type === 'python-tool')
                .map((tool: { id: number; type: string }) => tool.id),
            mcp_tools: this.rowData[index].mergedTools
                .filter((tool: { id: number; type: string }) => tool.type === 'mcp-tool')
                .map((tool: { id: number; type: string }) => tool.id),
        };

        // Build tool_ids array for settings update
        const settingsConfiguredToolIds = allToolsPreBuilding.configured_tools || [];
        const settingsPythonToolIds = allToolsPreBuilding.python_code_tools || [];
        const settingsMcpToolIds = allToolsPreBuilding.mcp_tools || [];

        const settingsToolIds = buildToolIdsArray(settingsConfiguredToolIds, settingsPythonToolIds, settingsMcpToolIds);

        const parsedUpdateData = this.parseAgentData(this.rowData[index]);

        // Prepare the payload for the backend update request
        const rowId = String(updatedAgent.id ?? '');
        const isTemp = rowId.startsWith('temp_');

        if (isTemp) {
            const createAgentData: CreateAgentRequest = {
                ...parsedUpdateData,
                realtime_agent,
                configured_tools: settingsConfiguredToolIds,
                python_code_tools: settingsPythonToolIds,
                mcp_tools: settingsMcpToolIds,
                tool_ids: settingsToolIds as ToolUniqueName[],
            };

            this.setPending(rowId, { kind: 'create', rowId, payload: createAgentData });
        } else {
            const updateAgentData: UpdateAgentRequest = {
                ...parsedUpdateData,
                id: +updatedAgent.id,
                realtime_agent,
                configured_tools: settingsConfiguredToolIds,
                python_code_tools: settingsPythonToolIds,
                mcp_tools: settingsMcpToolIds,
                tool_ids: settingsToolIds,
            };
            this.reconcilePendingUpdate(rowId, updateAgentData);
        }

        this.cdr.markForCheck();
    }

    public onCellContextMenu(event: CellContextMenuEvent) {
        if (this.shouldBlockInteraction()) {
            this.closeContextMenu();
            return;
        }
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
    public handleDelete(): void {
        if (this.isSaving) return;

        // Make sure we have a selected row
        if (!this.selectedRowData) {
            return;
        }

        const rowId = this.selectedRowData.id;

        const isTempRow = typeof rowId === 'string' && rowId.startsWith('temp_');

        const clearLocalPendingState = (id: string) => {
            this.pending.delete(id);
            this.savedSnapshot.delete(id);
            this.draftTempRows.delete(id);
            this.invalidTempRows.delete(id);
            this.requiredErrorsRows.delete(id);
            this.emitDirty();
        };

        if (isTempRow) {
            const index = this.rowData.findIndex((row) => row.id === rowId);

            if (index !== -1) {
                // Remove from the data array
                this.rowData.splice(index, 1)[0];

                // Update the grid with the new data
                this.gridApi.setGridOption('rowData', [...this.rowData]);

                // Refresh index column
                this.gridApi.refreshCells({
                    force: true,
                    columns: ['index'],
                });

                this.cdr.markForCheck();
            } else {
                console.warn('Temporary row not found in data array');
            }

            clearLocalPendingState(rowId);
            this.closeContextMenu();
            return;
        }

        // For permanent rows (with numeric IDs)
        const numericId = typeof rowId === 'number' ? rowId : parseInt(rowId as string, 10);

        if (isNaN(numericId)) {
            console.error('Invalid ID for deletion:', rowId);
            this.toastService.error('Cannot delete agent: Invalid ID');
            this.closeContextMenu();
            return;
        }

        const idStr = String(numericId);
        clearLocalPendingState(idStr);

        const index = this.rowData.findIndex((row) => {
            const rowIdNum = typeof row.id === 'number' ? row.id : parseInt(row.id as string, 10);
            return rowIdNum === numericId;
        });

        if (index === -1) {
            console.warn('Row not found in data array for delete:', numericId);
            this.closeContextMenu();
            return;
        }

        this.deletedRows.set(idStr, { row: this.rowData[index], index });
        this.rowData.splice(index, 1);
        this.gridApi.setGridOption('rowData', [...this.rowData]);
        this.gridApi.refreshCells({ force: true, columns: ['index'] });
        this.cdr.markForCheck();
        this.setPending(idStr, { kind: 'delete', rowId: idStr });
        this.closeContextMenu();
        return;
    }

    public handleCopy(): void {
        if (this.shouldBlockInteraction()) return;
        if (!this.selectedRowData) return;
        this.copiedRowData = JSON.parse(JSON.stringify(this.selectedRowData));
        this.closeContextMenu();
    }

    public handlePasteBelow(): void {
        if (this.shouldBlockInteraction()) return;
        if (!this.selectedRowData || !this.copiedRowData) return;
        const index = this.rowData.findIndex((row) => row === this.selectedRowData);
        if (index === -1) return;
        this.pasteNewAgentAt(index + 1);
    }

    public handlePasteAbove(): void {
        if (this.shouldBlockInteraction()) return;
        if (!this.selectedRowData || !this.copiedRowData) return;
        const index = this.rowData.findIndex((row) => row === this.selectedRowData);
        if (index === -1) return;
        this.pasteNewAgentAt(index);
    }

    public closeContextMenu(): void {
        this.contextMenuVisible.set(false);
    }

    private pasteNewAgentAt(insertIndex: number): void {
        if (this.shouldBlockInteraction()) return;
        if (!this.copiedRowData) return;

        const tempId = `temp_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

        // 1) local clone + new temp id
        const newAgentData: TableFullAgent = {
            ...JSON.parse(JSON.stringify(this.copiedRowData)),
            id: tempId,
        };

        // 2) insert locally
        this.rowData.splice(insertIndex, 0, newAgentData);
        this.ensureSingleSpareEmptyRow();

        this.gridApi.applyTransaction({
            add: [newAgentData],
            addIndex: insertIndex,
        });

        this.gridApi.refreshCells({ force: true, columns: ['index'] });
        this.cdr.markForCheck();

        // 3) build CreateAgentRequest (same mapping as you already had)
        let realtimeConfigId = null;

        if (newAgentData.mergedConfigs && Array.isArray(newAgentData.mergedConfigs)) {
            const realtimeConfig = newAgentData.mergedConfigs.find((c) => c.type === 'realtime');
            if (realtimeConfig) realtimeConfigId = realtimeConfig.id;
        } else if (newAgentData.fullRealtimeConfig?.id) {
            realtimeConfigId = newAgentData.fullRealtimeConfig.id;
        } else if (newAgentData.realtime_agent?.realtime_config) {
            realtimeConfigId = newAgentData.realtime_agent.realtime_config;
        }

        const realtime_agent = {
            ...(newAgentData.realtime_agent || {
                wake_word: '',
                stop_prompt: 'stop',
                language: null,
                voice_recognition_prompt: null,
                voice: 'alloy',
                realtime_transcription_config: null,
            }),
            realtime_config: realtimeConfigId,
        };

        const parsedAgentData = this.parseAgentData(newAgentData);

        const configuredToolIds = parsedAgentData.configured_tools || [];
        const pythonToolIds = parsedAgentData.python_code_tools || [];
        const mcpToolIds = parsedAgentData.mcp_tools || [];
        const toolIds = buildToolIdsArray(configuredToolIds, pythonToolIds, mcpToolIds);

        const createAgentData: CreateAgentRequest = {
            ...parsedAgentData,
            realtime_agent,
            configured_tools: configuredToolIds,
            python_code_tools: pythonToolIds,
            mcp_tools: mcpToolIds,
            tool_ids: toolIds as ToolUniqueName[],
        };

        // 4) mark as pending create (so global Save will persist it)
        this.setPending(tempId, {
            kind: 'create',
            rowId: tempId,
            payload: createAgentData,
        });

        this.closeContextMenu();
    }

    public handleAddEmptyAgentAbove(): void {
        if (this.shouldBlockInteraction()) return;

        if (!this.selectedRowData) return;
        const index = this.rowData.findIndex((row) => row === this.selectedRowData);
        if (index === -1) return;
        this.insertEmptyAgentAt(index);
    }

    public handleAddEmptyAgentBelow(): void {
        if (this.shouldBlockInteraction()) return;
        if (!this.selectedRowData) return;
        const index = this.rowData.findIndex((row) => row === this.selectedRowData);
        if (index === -1) return;
        this.insertEmptyAgentAt(index + 1);
    }

    private insertEmptyAgentAt(insertIndex: number): void {
        if (this.shouldBlockInteraction()) return;
        const emptyAgent = this.createEmptyFullAgent();

        // Add to internal data array
        this.rowData.splice(insertIndex, 0, emptyAgent);
        this.ensureSingleSpareEmptyRow();

        // Use transaction API instead of replacing whole array
        this.gridApi.applyTransaction({
            add: [emptyAgent],
            addIndex: insertIndex,
        });

        this.gridApi.refreshCells({
            force: true,
            columns: ['index'],
        });

        this.cdr.markForCheck();

        this.closeContextMenu();
    }
    private onCellClicked(event: CellClickedEvent<TableFullAgent, unknown>): void {
        if (this.shouldBlockInteraction()) return;
        if (event.column.getColId() === 'actions') {
            const agentData = event.data;
            if (!agentData) return;
            this.closePopup();

            this.openSettingsDialog(agentData);
        }
        const columnId = event.column.getColId();

        if (event.column.getColId() === 'copy') {
            this.selectedRowData = event.data ?? null;
            this.copiedRowData = JSON.parse(JSON.stringify(event.data));
            const rowIndex = this.rowData.findIndex((row) => row === event.data);
            if (rowIndex !== -1) this.pasteNewAgentAt(rowIndex + 1);
            return;
        }
        // Process only specific columns.
        if (columnId !== 'mergedConfigs' && columnId !== 'mergedTools' && columnId !== 'tags') {
            return;
        }

        const rowIndex = event.rowIndex ?? 0;
        const cell: CellInfo = { columnId, rowIndex };

        // Avoid reopening the popup if it is already open on the same cell.
        if (
            this.popupOverlayRef &&
            this.currentPopupCell &&
            this.currentPopupCell.columnId === cell.columnId &&
            this.currentPopupCell.rowIndex === cell.rowIndex
        ) {
            return;
        }

        // Close any existing popup
        this.closePopup();
        this.openPopup(event, cell);
    }

    private onCellKeyDown(event: CellKeyDownEvent<TableFullAgent, unknown>): void {
        if (this.shouldBlockInteraction()) return;

        const keyboardEvent = event.event as KeyboardEvent;

        if (keyboardEvent?.key === 'Enter') {
            const { rowIndex, column } = event;
            const columnId = column.getColId();
            if (
                event.column.getColId() !== 'actions' &&
                columnId !== 'mergedConfigs' &&
                columnId !== 'mergedTools' &&
                columnId !== 'tags' &&
                rowIndex != null
            ) {
                const rowNode = this.gridApi.getDisplayedRowAtIndex(rowIndex);
                const data = rowNode?.data;
                const rowId = String(data?.id ?? '');

                if (this.isTempRowId(rowId)) {
                    const firstEmpty = (['role', 'goal', 'backstory'] as const).find((f) =>
                        this.isRequiredEmpty(data, f)
                    );

                    if (firstEmpty) {
                        keyboardEvent.preventDefault();
                        this.gridApi.stopEditing();
                        this.gridApi.setFocusedCell(rowIndex, firstEmpty);
                        this.gridApi.startEditingCell({ rowIndex, colKey: firstEmpty });
                        return;
                    }

                    const order: Array<'role' | 'goal' | 'backstory'> = ['role', 'goal', 'backstory'];
                    const idx = order.indexOf(columnId as 'role' | 'goal' | 'backstory');
                    if (idx >= 0 && idx < order.length - 1) {
                        const next = order[idx + 1];
                        keyboardEvent.preventDefault();
                        this.gridApi.stopEditing();
                        this.gridApi.setFocusedCell(rowIndex, next);
                        this.gridApi.startEditingCell({ rowIndex, colKey: next });
                        return;
                    }
                }
            }
            if (event.column.getColId() === 'actions') {
                const agentData = event.data;
                if (!agentData) return;
                this.closePopup();

                this.openSettingsDialog(agentData);
                return;
            }
            // Process only specific columns
            if (columnId === 'mergedConfigs' || columnId === 'mergedTools' || columnId === 'tags') {
                if (rowIndex !== null) {
                    // If a popup is already open for the same cell, do nothing.
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
        if (this.shouldBlockInteraction()) return;
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
                offsetY: -5,
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

        // Attach the appropriate popup component.
        if (cell.columnId === 'mergedConfigs') {
            const portal = new ComponentPortal(LLMPopupComponent);
            const popupRef = this.popupOverlayRef.attach(portal);

            popupRef.instance.cellValue = event.data?.mergedConfigs || [];

            // Subscribe to the configsSelected event
            popupRef.instance.configsSelected.subscribe((mergedConfigs: MergedConfig[]) => {
                if (this.currentPopupCell) {
                    const rowIndex = this.currentPopupCell.rowIndex;
                    const rowNode = this.gridApi.getDisplayedRowAtIndex(rowIndex);

                    if (rowNode) {
                        const rowData = rowNode.data;
                        const isTempRow =
                            !rowData?.id || (typeof rowData.id === 'string' && rowData.id.startsWith('temp_'));

                        // Update the mergedConfigs in the row data
                        rowNode.setDataValue('mergedConfigs', mergedConfigs);

                        // Update related fullLlmConfig and fullRealtimeConfig properties
                        const llmConfig = mergedConfigs.find((config) => config.type === 'llm');
                        const realtimeConfig = mergedConfigs.find((config) => config.type === 'realtime');

                        if (llmConfig) {
                            rowNode.setDataValue('llm_config', llmConfig.id);
                        } else {
                            rowNode.setDataValue('llm_config', null);
                            rowNode.setDataValue('fullLlmConfig', null);
                        }

                        if (realtimeConfig) {
                            const realtime_agent = {
                                ...(rowData.realtime_agent || {}),
                                realtime_config: realtimeConfig.id,
                            };
                            rowNode.setDataValue('realtime_agent', realtime_agent);
                        } else {
                            rowNode.setDataValue('fullRealtimeConfig', null);
                            if (rowData.realtime_agent) {
                                const realtime_agent = {
                                    ...rowData.realtime_agent,
                                    realtime_config: null,
                                };
                                rowNode.setDataValue('realtime_agent', realtime_agent);
                            }
                        }

                        const freshRowData = rowNode.data;
                        const tempRowId = String(freshRowData?.id ?? '');

                        if (this.isTempRowId(tempRowId)) {
                            if (this.isTempRowTouched(freshRowData)) {
                                this.draftTempRows.add(tempRowId);
                            } else {
                                this.draftTempRows.delete(tempRowId);
                            }
                            this.emitDirty();
                            this.updateRequiredErrorsForTempRow(tempRowId, freshRowData);
                            const touched = this.isTempRowTouched(freshRowData);

                            if (!touched) {
                                this.draftTempRows.delete(tempRowId);
                                this.pending.delete(tempRowId);
                                this.markRowInvalid(tempRowId, false);
                                this.emitDirty();
                                this.cdr.markForCheck();
                                this.closePopup();
                                return;
                            }

                            const valid = this.isTempRowValid(freshRowData);
                            this.markRowInvalid(tempRowId, touched && !valid);
                        }

                        const parsedData = this.parseAgentData(freshRowData);

                        const configuredToolIds = parsedData.configured_tools || [];
                        const pythonToolIds = parsedData.python_code_tools || [];
                        const mcpToolIds = parsedData.mcp_tools || [];
                        const toolIds = buildToolIdsArray(configuredToolIds, pythonToolIds, mcpToolIds);

                        const rowId = String(freshRowData.id);

                        if (isTempRow) {
                            const createAgentData: CreateAgentRequest = {
                                ...parsedData,
                                configured_tools: configuredToolIds,
                                python_code_tools: pythonToolIds,
                                mcp_tools: mcpToolIds,
                                tool_ids: toolIds,
                            };

                            this.setPending(rowId, { kind: 'create', rowId, payload: createAgentData });
                        } else {
                            const updateAgentData: UpdateAgentRequest = {
                                ...parsedData,
                                id: Number(freshRowData.id),
                                configured_tools: configuredToolIds,
                                python_code_tools: pythonToolIds,
                                mcp_tools: mcpToolIds,
                                tool_ids: toolIds,
                            };

                            this.reconcilePendingUpdate(rowId, updateAgentData);
                        }

                        this.cdr.markForCheck();
                    }
                }
                // Close the popup after selection
                this.closePopup();
            });

            // Handle cancel event
            popupRef.instance.cancel.subscribe(() => {
                this.closePopup();
            });
        } else if (cell.columnId === 'mergedTools') {
            const portal = new ComponentPortal(ToolsPopupComponent);
            const popupRef = this.popupOverlayRef.attach(portal);
            // Pass the mergedTools array (or an empty array if not present)
            popupRef.instance.mergedTools = event.data?.mergedTools || [];

            // Subscribe to the mergedToolsSaved event
            popupRef.instance.mergedToolsUpdated.subscribe((updatedMergedTools: string[]) => {
                if (this.currentPopupCell) {
                    const rowIndex = this.currentPopupCell.rowIndex;

                    // Get the row node using the row index
                    const rowNode = this.gridApi.getDisplayedRowAtIndex(rowIndex);
                    if (rowNode) {
                        // Use setDataValue to update the mergedTools cell
                        rowNode.setDataValue('mergedTools', updatedMergedTools);

                        const rowData = rowNode.data;
                        const rowId = String(rowData?.id ?? '');

                        if (this.isTempRowId(rowId)) {
                            if (this.isTempRowTouched(rowData)) {
                                this.draftTempRows.add(rowId);
                            } else {
                                this.draftTempRows.delete(rowId);
                            }
                            this.emitDirty();
                            this.updateRequiredErrorsForTempRow(rowId, rowData);

                            this.cdr.markForCheck();
                        }
                    }
                }
                // Close the popup after saving
                this.closePopup();
            });

            // Handle cancel event
            popupRef.instance.cancel.subscribe(() => {
                this.closePopup();
            });
        } else if (cell.columnId === 'tags') {
            const portal = new ComponentPortal(TagsPopupComponent);
            const popupRef = this.popupOverlayRef.attach(portal);
            popupRef.instance.cellTags = event.data?.tags || [];

            popupRef.instance.tagsSaved.subscribe((updatedTags: string[]) => {
                if (this.currentPopupCell) {
                    const rowIndex = this.currentPopupCell.rowIndex;

                    // Get the row node using the row index
                    const rowNode = this.gridApi.getDisplayedRowAtIndex(rowIndex);
                    if (rowNode) {
                        // Use setDataValue to update the tags cell
                        rowNode.setDataValue('tags', updatedTags);

                        const rowData = rowNode.data;
                        const rowId = String(rowData?.id ?? '');

                        if (this.isTempRowId(rowId)) {
                            const touched = this.isTempRowTouched(rowData);
                            if (touched) this.draftTempRows.add(rowId);
                            else this.draftTempRows.delete(rowId);
                            this.emitDirty();
                            this.updateRequiredErrorsForTempRow(rowId, rowData);
                            this.cdr.markForCheck();
                        }
                    }
                }

                // Close the popup after saving
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

    private setPending(rowId: string, change: PendingChange): void {
        this.pending.set(rowId, change);
        this.emitDirty();
    }

    public flushPending(): Observable<void> {
        if (this.pending.size === 0) {
            return of(void 0);
        }

        const changes = Array.from(this.pending.values());

        const ordered = [...changes].sort((a, b) => {
            const rank = (k: PendingKind) => (k === 'delete' ? 0 : k === 'create' ? 1 : 2);
            return rank(a.kind) - rank(b.kind);
        });

        let needsReload = false;

        return from(ordered).pipe(
            concatMap((change) => {
                if (change.kind === 'delete') {
                    const idNum = Number(change.rowId);

                    if (Number.isNaN(idNum)) {
                        this.toastService.error('Failed to delete agent: invalid ID');
                        this.pending.delete(change.rowId);
                        this.emitDirty();
                        return of(void 0);
                    }

                    return this.agentsService.deleteAgent(idNum).pipe(
                        tap(() => {
                            const rowId = change.rowId;
                            this.pending.delete(rowId);
                            this.deletedRows.delete(rowId);
                            this.savedSnapshot.delete(rowId);
                            needsReload = true;
                            this.emitDirty();
                        }),
                        catchError((err) => {
                            if (err?.status === 404) {
                                const rowId = change.rowId;
                                this.pending.delete(rowId);
                                this.deletedRows.delete(rowId);
                                this.savedSnapshot.delete(rowId);
                                needsReload = true;
                                this.emitDirty();
                                return EMPTY;
                            }

                            this.toastService.error('Failed to delete agent');
                            return EMPTY;
                        }),
                        map(() => void 0)
                    );
                }

                if (change.kind === 'create') {
                    return this.agentsService.createAgent(change.payload as CreateAgentRequest).pipe(
                        tap(() => {
                            const rowId = change.rowId;
                            this.pending.delete(rowId);
                            this.requiredErrorsRows.delete(rowId);
                            this.invalidTempRows.delete(rowId);
                            this.draftTempRows.delete(rowId);
                            this.deletedRows.delete(rowId);
                            needsReload = true;
                            this.emitDirty();
                        }),
                        catchError(() => {
                            this.toastService.error('Failed to create agent');
                            return EMPTY;
                        }),
                        map(() => void 0)
                    );
                }

                return this.agentsService.updateAgent(change.payload as UpdateAgentRequest).pipe(
                    tap(() => {
                        const rowId = change.rowId;
                        const current = this.rowData.find((r) => String(r.id) === rowId);

                        if (current) {
                            this.savedSnapshot.set(rowId, this.buildComparablePayload(current));
                        }

                        this.pending.delete(rowId);
                        this.emitDirty();
                    }),
                    catchError(() => {
                        this.toastService.error('Failed to update agent');
                        return EMPTY;
                    }),
                    map(() => void 0)
                );
            }),
            toArray(),
            switchMap(() => {
                if (!needsReload) {
                    this.emitDirty();
                    this.cdr.markForCheck();
                    return of(void 0);
                }

                return this.fullAgentService.getFullAgents().pipe(
                    tap((fullAgents: FullAgent[]) => {
                        this.rowData = fullAgents.sort((a, b) => b.id - a.id);
                        this.savedSnapshot.clear();

                        for (const a of this.rowData) {
                            const rowId = String(a.id);
                            if (!rowId.startsWith('temp_')) {
                                this.savedSnapshot.set(rowId, this.buildComparablePayload(a));
                            }
                        }

                        this.deletedRows.clear();
                        this.ensureSingleSpareEmptyRow();
                        this.gridApi.setGridOption('rowData', [...this.rowData]);
                        this.gridApi.refreshCells({
                            force: true,
                            columns: ['index'],
                        });
                        this.gridApi.redrawRows();
                        this.emitDirty();
                        this.cdr.markForCheck();
                    }),
                    map(() => void 0)
                );
            }),
            finalize(() => {
                this.cdr.markForCheck();
            })
        );
    }

    public get hasPendingChanges(): boolean {
        return this.pending.size > 0;
    }

    public discardPending(): void {
        if (this.deletedRows.size > 0) {
            const restore = Array.from(this.deletedRows.values()).sort((a, b) => a.index - b.index);

            for (const item of restore) {
                const idx = Math.min(Math.max(item.index, 0), this.rowData.length);
                this.rowData.splice(idx, 0, item.row);
            }

            this.deletedRows.clear();
            this.gridApi.setGridOption('rowData', [...this.rowData]);
            this.gridApi.refreshCells({ force: true, columns: ['index'] });
        }
        this.pending.clear();
        this.dirtyChange.emit(false);
        this.cdr.markForCheck();
    }

    public addPendingCreateFromDialog(payload: CreateAgentRequest): void {
        if (this.shouldBlockInteraction()) return;

        if (!this.gridApi) {
            const tempRow = this.createEmptyFullAgent();
            const tempId = String(tempRow.id);

            Object.assign(tempRow, {
                role: payload.role ?? '',
                goal: payload.goal ?? '',
                backstory: payload.backstory ?? '',
                allow_delegation: payload.allow_delegation ?? false,
                memory: payload.memory ?? false,
                max_iter: payload.max_iter ?? 20,
                max_rpm: payload.max_rpm ?? 10,
                max_execution_time: payload.max_execution_time ?? 60,
                cache: payload.cache ?? false,
                max_retry_limit: payload.max_retry_limit ?? 0,
                respect_context_window: payload.respect_context_window ?? false,
                default_temperature: payload.default_temperature ?? null,
                knowledge_collection: payload.knowledge_collection ?? null,
                rag: payload.rag ?? null,
                llm_config: payload.llm_config ?? null,
                fcm_llm_config: payload.fcm_llm_config ?? null,
                configured_tools: payload.configured_tools ?? [],
                python_code_tools: payload.python_code_tools ?? [],
                mcp_tools: payload.mcp_tools ?? [],
                search_configs: payload.search_configs ?? tempRow.search_configs,
                realtime_agent: payload.realtime_agent ?? tempRow.realtime_agent,
            });

            this.rowData.unshift(tempRow);
            this.setPending(tempId, { kind: 'create', rowId: tempId, payload });
            this.requiredErrorsRows.delete(tempId);
            this.invalidTempRows.delete(tempId);
            this.draftTempRows.delete(tempId);
            this.cdr.markForCheck();
            return;
        }

        const tempRow = this.createEmptyFullAgent();
        const tempId = String(tempRow.id);

        Object.assign(tempRow, {
            role: payload.role ?? '',
            goal: payload.goal ?? '',
            backstory: payload.backstory ?? '',
            allow_delegation: payload.allow_delegation ?? false,
            memory: payload.memory ?? false,
            max_iter: payload.max_iter ?? 20,
            max_rpm: payload.max_rpm ?? 10,
            max_execution_time: payload.max_execution_time ?? 60,
            cache: payload.cache ?? false,
            max_retry_limit: payload.max_retry_limit ?? 0,
            respect_context_window: payload.respect_context_window ?? false,
            default_temperature: payload.default_temperature ?? null,
            knowledge_collection: payload.knowledge_collection ?? null,
            rag: payload.rag ?? null,
            llm_config: payload.llm_config ?? null,
            fcm_llm_config: payload.fcm_llm_config ?? null,
            configured_tools: payload.configured_tools ?? [],
            python_code_tools: payload.python_code_tools ?? [],
            mcp_tools: payload.mcp_tools ?? [],
            search_configs: payload.search_configs ?? tempRow.search_configs,
            realtime_agent: payload.realtime_agent ?? tempRow.realtime_agent,
        });

        this.rowData.unshift(tempRow);
        this.gridApi.applyTransaction({ add: [tempRow], addIndex: 0 });
        this.setPending(tempId, { kind: 'create', rowId: tempId, payload });
        this.requiredErrorsRows.delete(tempId);
        this.invalidTempRows.delete(tempId);
        this.draftTempRows.delete(tempId);
        this.gridApi.refreshCells({ force: true, columns: ['index'] });
        this.cdr.markForCheck();
    }

    public addPendingUpdateFromDialog(payload: UpdateAgentRequest): void {
        if (this.shouldBlockInteraction()) return;
        const rowId = String(payload.id);

        if (rowId.startsWith('temp_')) {
            this.setPending(rowId, { kind: 'create', rowId, payload: payload as CreateAgentRequest });
            this.cdr.markForCheck();
            return;
        }

        const index = this.rowData.findIndex((r) => String(r.id) === rowId);
        if (index !== -1) {
            this.rowData[index] = { ...this.rowData[index], ...payload } as TableFullAgent;
            this.gridApi?.setGridOption('rowData', [...this.rowData]);
        }

        this.reconcilePendingUpdate(rowId, payload);
        this.cdr.markForCheck();
    }

    private normalizeAdvancedSettings(input: TableFullAgent): Record<string, unknown> {
        const rawInput = input as TableFullAgent & Record<string, unknown>;
        const sl = input?.search_configs?.naive?.search_limit;
        const st = input?.search_configs?.naive?.similarity_threshold;
        return {
            fcm_llm_config_id: input?.fullFcmLlmConfig?.id ?? input?.fcm_llm_config ?? null,
            knowledge_collection: input?.knowledge_collection ?? rawInput['selected_knowledge_source'] ?? null,
            rag_id: input?.rag?.rag_id ?? rawInput['rag_id'] ?? null,
            max_iter: input?.max_iter ?? 20,
            max_rpm: input?.max_rpm ?? 10,
            max_execution_time: input?.max_execution_time ?? 60,
            max_retry_limit: input?.max_retry_limit ?? null,

            memory: !!input?.memory,
            cache: !!input?.cache,
            respect_context_window: !!input?.respect_context_window,

            search_limit: sl == null ? null : Number(sl),
            similarity_threshold: st == null ? null : Number(st),
        };
    }

    private jsonEqual(a: unknown, b: unknown): boolean {
        return JSON.stringify(a) === JSON.stringify(b);
    }

    private draftTempRows = new Set<string>();
    private invalidTempRows = new Set<string>();

    private emitDirty(): void {
        this.dirtyChange.emit(this.pending.size > 0 || this.draftTempRows.size > 0);
    }

    private isNonEmpty(v: unknown): boolean {
        return v !== null && v !== undefined && String(v).trim() !== '';
    }

    private isTempRowId(id: unknown): boolean {
        return typeof id === 'string' && id.startsWith('temp_');
    }

    private getByPath(obj: Record<string, unknown>, path: string): unknown {
        return path
            .split('.')
            .reduce(
                (acc: unknown, key: string) =>
                    acc && typeof acc === 'object' ? (acc as Record<string, unknown>)[key] : undefined,
                obj
            );
    }

    private isTempRowTouched(data: unknown): boolean {
        if (!data || typeof data !== 'object') return false;
        const row = data as Record<string, unknown>;
        const defaults = {
            role: '',
            goal: '',
            backstory: '',
            configured_tools: [],
            python_code_tools: [],
            mcp_tools: [],
            mergedTools: [],
            mergedConfigs: [],
            llm_config: null,
            fcm_llm_config: null,
            allow_delegation: false,
            memory: false,
            max_iter: 20,
            max_rpm: 10,
            max_execution_time: 60,
            cache: false,
            allow_code_execution: false,
            max_retry_limit: 0,
            respect_context_window: false,
            default_temperature: null,
            tags: [],
            knowledge_collection: null,
            rag: null,
            search_configs: {
                naive: {
                    search_limit: 3,
                    similarity_threshold: 0.2,
                },
            },
            realtime_agent: {
                wake_word: '',
                stop_prompt: 'stop',
                language: null,
                voice_recognition_prompt: null,
                voice: 'alloy',
                realtime_config: null,
                realtime_transcription_config: null,
            },
        };

        const pathsToCheck = [
            'role',
            'goal',
            'backstory',
            'llm_config',
            'fcm_llm_config',
            'mergedTools',
            'mergedConfigs',
            'allow_delegation',
            'memory',
            'cache',
            'allow_code_execution',
            'respect_context_window',
            'max_iter',
            'max_rpm',
            'max_execution_time',
            'max_retry_limit',
            'default_temperature',
            'tags',
            'knowledge_collection',
            'rag',
            'search_configs.naive.search_limit',
            'search_configs.naive.similarity_threshold',
            'realtime_agent.wake_word',
            'realtime_agent.stop_prompt',
            'realtime_agent.language',
            'realtime_agent.voice_recognition_prompt',
            'realtime_agent.voice',
            'realtime_agent.realtime_config',
            'realtime_agent.realtime_transcription_config',
        ];

        return pathsToCheck.some((path) => {
            const curRaw = this.getByPath(row, path);
            const defRaw = this.getByPath(defaults, path);
            const cur = this.normalizeTouchedValue(path, curRaw);
            const def = this.normalizeTouchedValue(path, defRaw);
            const curIsObj = cur && typeof cur === 'object';
            const defIsObj = def && typeof def === 'object';

            if (Array.isArray(cur) || Array.isArray(def) || curIsObj || defIsObj) {
                return !this.jsonEqual(cur ?? null, def ?? null);
            }

            return (cur ?? null) !== (def ?? null);
        });
    }

    private isTempRowValid(data: unknown): boolean {
        const row = (data ?? {}) as Record<string, unknown>;
        return this.isNonEmpty(row['role']) && this.isNonEmpty(row['goal']) && this.isNonEmpty(row['backstory']);
    }

    private markRowInvalid(rowId: string, isInvalid: boolean): void {
        if (isInvalid) this.invalidTempRows.add(rowId);
        else this.invalidTempRows.delete(rowId);
        this.gridApi?.redrawRows();
    }

    private onCellEditingStopped(e: CellEditingStoppedEvent<TableFullAgent>): void {
        const data = e?.data;
        const rowId = String(data?.id ?? '');
        if (!this.isTempRowId(rowId)) return;
        if (!this.isTempRowTouched(data)) return;
        const valid = this.isTempRowValid(data);
        this.markRowInvalid(rowId, !valid);
        this.updateRequiredErrorsForTempRow(rowId, data);

        // if (!valid) {
        //     this.toastService.warning('All required fields must be filled');
        // }
    }

    public validateBeforeSave(): boolean {
        for (const id of this.draftTempRows) {
            const rowNode = this.gridApi?.getRowNode(id);
            const data = rowNode?.data;
            if (!data) continue;

            if (!this.isTempRowValid(data)) {
                this.requiredErrorsRows.add(id);
                this.gridApi.refreshCells({
                    rowNodes: [rowNode],
                    columns: ['role', 'goal', 'backstory'],
                    force: true,
                });
                return false;
            }
        }
        return true;
    }

    private requiredErrorsRows = new Set<string>();

    private lastFocusedRowIndex: number | null = null;

    private onCellFocused(e: { rowIndex?: number | null }): void {
        const rowIndex = typeof e?.rowIndex === 'number' ? e.rowIndex : null;
        if (rowIndex != null && rowIndex >= 0) {
            const node = this.gridApi?.getDisplayedRowAtIndex(rowIndex);
            this.activeRowId = node?.data?.id != null ? String(node.data.id) : null;
        }
        const newRowIndex = typeof e?.rowIndex === 'number' ? e.rowIndex : null;

        if (this.lastFocusedRowIndex != null && this.lastFocusedRowIndex !== newRowIndex) {
            const prevNode = this.gridApi?.getDisplayedRowAtIndex(this.lastFocusedRowIndex);
            const prevRowId = prevNode?.data?.id != null ? String(prevNode.data.id) : null;
            if (prevRowId) this.applyRequiredErrorsOnRowExit(prevRowId);
        }

        this.lastFocusedRowIndex = newRowIndex;
    }

    private applyRequiredErrorsOnRowExit(rowId: string): void {
        if (!this.isTempRowId(rowId)) {
            this.requiredErrorsRows.delete(rowId);
            return;
        }

        const rowNode = this.gridApi.getRowNode(rowId);
        const data = rowNode?.data;
        if (!data) return;
        const touched = this.isTempRowTouched(data);
        const valid = this.isTempRowValid(data);

        if (touched && !valid) {
            this.requiredErrorsRows.add(rowId);
        } else {
            this.requiredErrorsRows.delete(rowId);
        }

        this.gridApi.refreshCells({
            rowNodes: rowNode ? [rowNode] : undefined,
            columns: ['role', 'goal', 'backstory'],
            force: true,
        });
    }

    private showRequiredErrorsForRow(rowId: string): void {
        if (!this.isTempRowId(rowId)) return;

        this.requiredErrorsRows.add(rowId);

        const rowNode = this.gridApi?.getRowNode(rowId);
        if (!rowNode) return;

        this.gridApi.refreshCells({
            rowNodes: [rowNode],
            columns: ['role', 'goal', 'backstory'],
            force: true,
        });
    }

    private clearRequiredErrorsForRow(rowId: string): void {
        this.requiredErrorsRows.delete(rowId);

        const rowNode = this.gridApi?.getRowNode(rowId);
        if (!rowNode) return;

        this.gridApi.refreshCells({
            rowNodes: [rowNode],
            columns: ['role', 'goal', 'backstory'],
            force: true,
        });
    }

    private readonly requiredCols = ['role', 'goal', 'backstory'] as const;

    private isRequiredEmpty(data: Record<string, unknown>, field: (typeof this.requiredCols)[number]): boolean {
        const v = (data?.[field] ?? '').toString().trim();
        return v.length === 0;
    }

    private enterJumpInProgress = false;

    private handleEnterJumpWithinTempRow(params: SuppressKeyboardEventParams<TableFullAgent>): boolean {
        const e = params.event as KeyboardEvent | undefined;
        if (!e || e.key !== 'Enter') return false;

        if (e.shiftKey) return false;

        e.preventDefault();
        e.stopPropagation();

        if (e.type === 'keyup') return true;
        if (e.type !== 'keydown') return true;
        if (this.enterJumpInProgress) return true;
        this.enterJumpInProgress = true;

        const rowIndex = params.node?.rowIndex;
        if (rowIndex == null || rowIndex < 0) {
            this.enterJumpInProgress = false;
            return true;
        }

        const data = params.node?.data;
        const rowId = String(data?.id ?? '');
        if (!rowId.startsWith('temp_')) {
            this.enterJumpInProgress = false;
            return false;
        }

        this.gridApi.stopEditing();

        const requiredCols = ['role', 'goal', 'backstory'] as const;
        const curCol = params.column?.getColId?.() ?? '';
        const curIdx = requiredCols.indexOf(curCol as 'role' | 'goal' | 'backstory');

        if (curIdx === -1) {
            this.enterJumpInProgress = false;
            return false;
        }

        if (curIdx < requiredCols.length - 1) {
            const next = requiredCols[curIdx + 1];
            setTimeout(() => {
                this.gridApi.setFocusedCell(rowIndex, next);
                this.gridApi.startEditingCell({ rowIndex, colKey: next });
                this.enterJumpInProgress = false;
            }, 0);
            return true;
        }

        setTimeout(() => {
            const touched = this.isTempRowTouched(data);
            const valid = this.isTempRowValid(data);

            if (touched && !valid) {
                this.showRequiredErrorsForRow(rowId);
            } else {
                this.clearRequiredErrorsForRow(rowId);
            }

            this.gridApi.setFocusedCell(rowIndex, 'backstory');
            this.enterJumpInProgress = false;
        }, 0);

        return true;
    }

    private isClickInsideRow(target: HTMLElement, rowId: string): boolean {
        const wrap = this.agGridWrap?.nativeElement;
        const insideGrid = wrap?.contains(target) ?? false;
        if (!insideGrid) return false;
        const rowEl = target.closest('.ag-row') as HTMLElement | null;
        if (!rowEl) return false;
        const rowIndexAttr = rowEl.getAttribute('row-index');
        const rowIndex = rowIndexAttr != null ? Number(rowIndexAttr) : NaN;
        if (!Number.isFinite(rowIndex)) return false;
        const node = this.gridApi?.getDisplayedRowAtIndex(rowIndex);
        const clickedRowId = node?.data?.id != null ? String(node.data.id) : null;
        return clickedRowId === rowId;
    }

    private updateRequiredErrorsForTempRow(rowId: string, data: unknown): void {
        if (!this.isTempRowId(rowId) || !data) return;
        const shouldShow = this.isTempRowTouched(data) && !this.isTempRowValid(data);

        if (shouldShow) this.requiredErrorsRows.add(rowId);
        else this.requiredErrorsRows.delete(rowId);

        const rowNode = this.gridApi?.getRowNode(rowId);
        if (!rowNode) return;

        this.gridApi.refreshCells({
            rowNodes: [rowNode],
            columns: ['role', 'goal', 'backstory'],
            force: true,
        });
    }

    private normalizeTouchedValue(path: string, v: unknown): unknown {
        if (path === 'role' || path === 'goal' || path === 'backstory') {
            return (v ?? '').toString();
        }

        return v;
    }

    private buildComparablePayload(agent: TableFullAgent): Record<string, unknown> {
        const parsed = this.parseAgentData(agent);

        const configured = (agent.mergedTools ?? [])
            .filter((t: { id: number; type: string }) => t.type === 'tool-config')
            .map((t: { id: number; type: string }) => t.id);

        const python = (agent.mergedTools ?? [])
            .filter((t: { id: number; type: string }) => t.type === 'python-tool')
            .map((t: { id: number; type: string }) => t.id);

        const mcp = (agent.mergedTools ?? [])
            .filter((t: { id: number; type: string }) => t.type === 'mcp-tool')
            .map((t: { id: number; type: string }) => t.id);

        const tool_ids = buildToolIdsArray(configured, python, mcp);

        const updateLikePayload = {
            ...parsed,
            configured_tools: configured,
            python_code_tools: python,
            mcp_tools: mcp,
            tool_ids,
            tags: agent.tags ?? [],
            max_iter: parsed.max_iter == null ? null : Number(parsed.max_iter),
            max_rpm: parsed.max_rpm == null ? null : Number(parsed.max_rpm),
        };

        return this.normalizeForCompare(updateLikePayload);
    }

    private reconcilePendingUpdate(rowId: string, updatePayload: UpdateAgentRequest): void {
        const baseline = this.savedSnapshot.get(rowId);
        const comparable = this.normalizeForCompare(updatePayload as unknown as Record<string, unknown>);

        if (this.jsonEqual(baseline, comparable)) {
            this.pending.delete(rowId);
            this.emitDirty();
            return;
        }

        this.setPending(rowId, { kind: 'update', rowId, payload: updatePayload });
    }

    private normalizeForCompare(payload: Record<string, unknown>): Record<string, unknown> {
        const p = structuredClone(payload);
        delete p['id'];
        delete p['mergedTools'];
        delete p['mergedConfigs'];
        delete p['tools'];
        delete p['fullFcmLlmConfig'];
        delete p['fullLlmConfig'];
        delete p['selected_knowledge_source'];

        for (const k of Object.keys(p)) {
            if (k.endsWith('Warning')) delete p[k];
        }

        p['configured_tools'] = Array.isArray(p['configured_tools']) ? [...p['configured_tools']].sort() : [];
        p['python_code_tools'] = Array.isArray(p['python_code_tools']) ? [...p['python_code_tools']].sort() : [];
        p['mcp_tools'] = Array.isArray(p['mcp_tools']) ? [...p['mcp_tools']].sort() : [];
        p['tool_ids'] = Array.isArray(p['tool_ids']) ? [...p['tool_ids']].sort() : [];
        p['tags'] = Array.isArray(p['tags']) ? [...p['tags']].sort() : [];
        p['cache'] = p['cache'] ?? false;
        p['allow_code_execution'] = p['allow_code_execution'] ?? false;
        p['respect_context_window'] = p['respect_context_window'] ?? false;

        return p;
    }

    private isSpareEmptyTempRow(row: TableFullAgent): boolean {
        const id = String(row?.id ?? '');
        if (!id.startsWith('temp_')) return false;

        return (
            !this.isTempRowTouched(row) &&
            !this.pending.has(id) &&
            !this.draftTempRows.has(id) &&
            !this.requiredErrorsRows.has(id) &&
            !this.invalidTempRows.has(id)
        );
    }

    private ensureSingleSpareEmptyRow(): void {
        const spareIndexes: number[] = [];

        for (let i = 0; i < this.rowData.length; i++) {
            if (this.isSpareEmptyTempRow(this.rowData[i])) spareIndexes.push(i);
        }

        if (spareIndexes.length === 0) {
            this.rowData.push(this.createEmptyFullAgent());
            return;
        }

        for (let i = spareIndexes.length - 2; i >= 0; i--) {
            this.rowData.splice(spareIndexes[i], 1);
        }
    }

    private shouldBlockInteraction(): boolean {
        return this.isSaving;
    }

    @HostListener('document:mousedown', ['$event'])
    onDocumentMouseDown(ev: MouseEvent): void {
        if (!this.activeRowId) return;
        const target = ev.target as HTMLElement | null;
        if (!target) return;
        if (this.isClickInsideRow(target, this.activeRowId)) return;
        this.applyRequiredErrorsOnRowExit(this.activeRowId);
    }
}
