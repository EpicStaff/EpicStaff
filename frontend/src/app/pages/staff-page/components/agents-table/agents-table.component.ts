import {
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  Inject,
  Input,
  Renderer2,
  signal,
  SimpleChanges,
  ViewChild,
} from '@angular/core';
import { AgGridAngular, AgGridModule } from 'ag-grid-angular';
import {
  CellClickedEvent,
  CellContextMenuEvent,
  CellEditingStartedEvent,
  CellKeyDownEvent,
  CellMouseOutEvent,
  CellMouseOverEvent,
  CellValueChangedEvent,
  ColDef,
  GridApi,
  GridOptions,
  GridReadyEvent,
  ICellRendererParams,
  RowDragEndEvent,
} from 'ag-grid-community';
import { AllCommunityModule, ModuleRegistry } from 'ag-grid-community';

import { themeQuartz } from 'ag-grid-community';

import { ConnectedPosition, Overlay, OverlayRef } from '@angular/cdk/overlay';
import { ComponentPortal } from '@angular/cdk/portal';
import { LLMPopupComponent } from '../cell-popups-and-modals/llm-selector-popup/llm-popup.component';

import { ToolsPopupComponent } from '../cell-popups-and-modals/tools-selector-popup/tools-popup.component';
import { TagsPopupComponent } from '../cell-popups-and-modals/tags-popup/tags-popup.component';
import {
  FullAgent,
  FullAgentService,
  TableFullAgent,
} from '../../../../services/full-agent.service';
import { IndexCellRendererComponent } from '../cell-renderers/index-row-cell-renderer/custom-row-height.component';
import { MemoryHeaderComponent } from '../header-renderers/memory-header.component';
import { DelegationHeaderComponent } from '../header-renderers/delegation-header.component';
import {
  AdvancedSettingsData,
  AdvancedSettingsDialogComponent,
} from '../advanced-settings-dialog.component.ts/advanced-settings-dialog.component';
import {
  Dialog,
  DIALOG_DATA,
  DialogModule,
  DialogRef,
} from '@angular/cdk/dialog';
import { AgentsService } from '../../../../services/staff.service';
import {
  CreateAgentRequest,
  ToolUniqueName,
  UpdateAgentRequest,
} from '../../../../shared/models/agent.model';
import { NgClass, NgIf, NgStyle } from '@angular/common';
import { PreventContextMenuDirective } from '../directives/prevent-context-menu.directive';
import { AgGridContextMenuComponent } from '../context-menu/ag-grid-context-menu.component';
import { ClickOutsideDirective } from '../../../../shared/directives/click-outside.directive';
import { ToastService } from '../../../../services/notifications/toast.service';
import { SpinnerComponent } from '../../../../shared/components/spinner/spinner.component';
import { buildToolIdsArray } from '../../../../shared/utils/tool-ids-builder.util';
import { ConfigCellRendererComponent } from '../cell-renderers/llm-cell-renderer/realtime-config-cell-renderer.component';
import { map, switchMap } from 'rxjs';
import { CreateRealtimeAgentRequest } from '../../../../shared/models/realtime-agent.model';
import { RealtimeAgentService } from '../../../../services/realtime-agent.service';

ModuleRegistry.registerModules([AllCommunityModule]);

interface CellInfo {
  columnId: string;
  rowIndex: number;
}
type PopupEvent = CellClickedEvent<any, any> | CellKeyDownEvent<any, any>;

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
  private currentPopupCell: any = null;
  private currentCellElement: HTMLElement | null = null;
  private globalClickUnlistener: (() => void) | null = null;
  private globalKeydownUnlistener: (() => void) | null = null;

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
        this.rowData.push(this.createEmptyFullAgent());
        console.log(this.rowData);

        this.cdr.markForCheck();
      },
      error: (err) => {
        console.error('Error fetching agents:', err);
        this.cdr.markForCheck();
      },
    });
  }
  ngOnChanges(changes: SimpleChanges): void {
    if (
      changes['newAgent'] &&
      changes['newAgent'].currentValue &&
      !changes['newAgent'].firstChange
    ) {
      const newAgent = changes['newAgent'].currentValue as FullAgent;
      console.log('New agent detected:', newAgent);

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

    this.cdr.markForCheck();
  }
  private createEmptyFullAgent(): TableFullAgent {
    const tempId = `temp_${Date.now()}_${Math.random()
      .toString(36)
      .substr(2, 9)}`;

    return {
      id: tempId,
      role: '',
      goal: '',
      backstory: '',
      configured_tools: [],
      python_code_tools: [],
      llm_config: null,
      fcm_llm_config: null,
      allow_delegation: false,
      memory: false,
      max_iter: 20,
      max_rpm: 0,
      max_execution_time: 0,
      cache: false,
      allow_code_execution: false,
      max_retry_limit: 0,
      respect_context_window: false,
      default_temperature: 0,
      tags: [],
      knowledge_collection: null,
      tools: [],
      // Replace realtime_config with realtime_agent object using provided defaults
      realtime_agent: {
        distance_threshold: '0.65',
        search_limit: 3,
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
      cellClass: 'agent-role-cell',
      cellEditor: 'agLargeTextCellEditor',
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
        'cell-warning': (params) => !!params.data.roleWarning,
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
      editable: true,
    },
    {
      headerName: 'Goal',
      field: 'goal',
      cellEditor: 'agLargeTextCellEditor',
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
        'cell-warning': (params) => !!params.data.goalWarning,
      },
      cellStyle: {
        'white-space': 'normal',
        'text-align': 'left',
        'font-size': '14px',
      },
      flex: 1,
      minWidth: 280,

      editable: true,
    },
    {
      headerName: 'Backstory',
      field: 'backstory',
      cellEditor: 'agLargeTextCellEditor',
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
        'cell-warning': (params) => !!params.data.backstoryWarning,
      },
      cellStyle: {
        'white-space': 'normal',
        'text-align': 'left',
        'font-size': '14px',
      },
      flex: 1,
      minWidth: 280,

      editable: true,
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
      cellRenderer: (params: { value: any[] }) => {
        const tools = params.value || [];

        if (!tools || tools.length === 0) {
          return '<div class="no-tools">No tools assigned</div>';
        }

        const toolsHtml = tools
          .map((tool: { configName: any; toolName: any }) => {
            return `
              <div class="tool-item">
                <i class="tool-icon">🔧</i>
                <span class="tool-name-text" title="${tool.toolName}">${tool.toolName}</span>
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
      cellRenderer: (params: ICellRendererParams) => {
        return `<i class="ti ti-settings action-icon"></i>`;
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

    suppressColumnVirtualisation: false, // Enable column virtualization for performance
    stopEditingWhenCellsLoseFocus: true,

    onFirstDataRendered: (params) => {
      this.isLoading.set(false);
    },
    getRowId: (params) => {
      // If the ID exists and is not null, use it
      if (params.data.id) {
        return params.data.id.toString();
      }

      // For new rows with temporary IDs, use the temporary ID
      if (params.data.id && params.data.id.toString().startsWith('temp_')) {
        return params.data.id.toString();
      }

      return `temp_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    },
    onCellClicked: (event: CellClickedEvent<any, any>) =>
      this.onCellClicked(event),
    onCellKeyDown: (event: CellKeyDownEvent) => this.onCellKeyDown(event),
    onCellValueChanged: (event) => this.onCellValueChanged(event),
    onRowDragEnd: (event) => this.onRowDragEnd(event),
  };

  onRowDragEnd(event: RowDragEndEvent) {
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

  private onCellValueChanged(event: any): void {
    const colId = event.column.getColId();
    const fieldsToValidate = ['role', 'goal', 'backstory']; // List of fields to validate

    // Function to parse the necessary fields (merged tools and config)
    const parseAgentData = (agentData: any) => {
      // Extract LLM config ID and realtime config ID from mergedConfigs
      let llmConfigId = null;
      let realtimeConfigId = null;

      // Check if mergedConfigs exist and process them
      if (agentData.mergedConfigs && Array.isArray(agentData.mergedConfigs)) {
        // Find LLM config
        const llmConfig = agentData.mergedConfigs.find(
          (config: any) => config.type === 'llm'
        );
        if (llmConfig) {
          llmConfigId = llmConfig.id;
        }

        // Find realtime config
        const realtimeConfig = agentData.mergedConfigs.find(
          (config: any) => config.type === 'realtime'
        );
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
        distance_threshold: agentData.realtime_agent?.distance_threshold,
        search_limit: agentData.realtime_agent?.search_limit,
        wake_word: agentData.realtime_agent?.wake_word,
        stop_prompt: agentData.realtime_agent?.stop_prompt,
        language: agentData.realtime_agent?.language,
        voice_recognition_prompt:
          agentData.realtime_agent?.voice_recognition_prompt,
        voice: agentData.realtime_agent?.voice,
        realtime_transcription_config:
          agentData.realtime_agent?.realtime_transcription_config,
      };

      return {
        ...agentData,
        llm_config: llmConfigId,
        fcm_llm_config: agentData.fcm_llm_config || llmConfigId, // Maintain existing logic
        realtime_agent: realtime_agent, // Use the properly structured realtime_agent object
        configured_tools: mergedTools
          .filter((tool: any) => tool.type === 'tool-config')
          .map((tool: any) => tool.id),
        python_code_tools: mergedTools
          .filter((tool: any) => tool.type === 'python-tool')
          .map((tool: any) => tool.id),
      };
    };

    // If the row has a temporary ID (starts with 'temp_') or null id, create a new agent after validation
    const isTempRow =
      !event.data.id ||
      (typeof event.data.id === 'string' && event.data.id.startsWith('temp_'));

    if (isTempRow) {
      if (fieldsToValidate.includes(colId)) {
        const newValue = event.data[colId] ? event.data[colId].trim() : '';
        event.data[`${colId}Warning`] = !newValue; // Dynamically set warning for the field
      }

      // Validate the required fields (role, goal, backstory)
      const isValid = fieldsToValidate.every((field) => {
        const fieldValue = event.data[field] ? event.data[field].trim() : '';
        return fieldValue !== ''; // Check if all fields are non-empty
      });

      // If any field is invalid, log a warning and prevent agent creation
      if (!isValid) {
        console.warn(
          'Warning: One or more required fields (role, goal, backstory) are empty.'
        );
        return; // Prevent creating the agent
      }

      // Parse the agent data
      const parsedData = parseAgentData(event.data);
      console.log(parsedData);

      // Build tool_ids array
      const configuredToolIds = parsedData.configured_tools || [];
      const pythonToolIds = parsedData.python_code_tools || [];
      const toolIds = buildToolIdsArray(configuredToolIds, pythonToolIds);

      // Create the new agent by sending the full row data
      const createAgentData: CreateAgentRequest = {
        role: parsedData.role,
        goal: parsedData.goal,
        backstory: parsedData.backstory,
        configured_tools: configuredToolIds,
        python_code_tools: pythonToolIds,
        llm_config: parsedData.llm_config,
        fcm_llm_config: parsedData.fcm_llm_config,
        realtime_agent: parsedData.realtime_agent, // Use the nested structure
        allow_delegation: parsedData.allow_delegation ?? false,
        memory: parsedData.memory ?? false,
        max_iter: parsedData.max_iter ?? undefined,
        max_rpm: parsedData.max_rpm ?? undefined,
        max_execution_time: parsedData.max_execution_time ?? undefined,
        cache: parsedData.cache ?? null,
        allow_code_execution: parsedData.allow_code_execution ?? null,
        max_retry_limit: parsedData.max_retry_limit ?? null,
        respect_context_window: parsedData.respect_context_window ?? null,
        default_temperature: parsedData.default_temperature ?? null,
        knowledge_collection: parsedData.knowledge_collection ?? null,
        tool_ids: toolIds,
      };

      // Use the new syntax with next, error, and complete
      this.agentsService.createAgent(createAgentData).subscribe({
        next: (newAgent) => {
          console.log('New agent created:', newAgent);
          this.toastService.success(`Agent created successfully`);

          // First find the row's position
          const rowIndex = this.rowData.findIndex((row) => row === event.data);
          if (rowIndex !== -1) {
            // Get the original temp ID before changing it
            const tempId = this.rowData[rowIndex].id;

            // Create a new full agent object with the new ID
            const updatedRow = {
              ...this.rowData[rowIndex],
              id: newAgent.id,
            };

            // Replace the row in our data array
            this.rowData[rowIndex] = updatedRow;

            // Instead of trying to update an existing node, remove and add the row
            this.gridApi.applyTransaction({
              remove: [{ id: tempId }],
              add: [updatedRow],
              addIndex: rowIndex,
            });

            // Create an empty agent
            const emptyAgent = this.createEmptyFullAgent();

            // Add it to the end using transaction API
            this.rowData.push(emptyAgent);
            this.gridApi.applyTransaction({ add: [emptyAgent] });
          }

          this.cdr.markForCheck();
        },
        error: (error) => {
          console.error('Error creating agent:', error);
          this.toastService.error(
            'Error creating agent: ' + (error.message || 'Unknown error')
          );
        },
        complete: () => {
          console.log('Agent creation process completed.');
        },
      });
      return;
    }
    // For rows with a valid id, validate all fields that require validation
    let allValid = true; // Flag to check if all fields are valid
    fieldsToValidate.forEach((field) => {
      const fieldValue = event.data[field] ? event.data[field].trim() : '';
      event.data[`${field}Warning`] = !fieldValue; // Dynamically set warning flag

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
    const parsedUpdateData = parseAgentData(event.data);
    console.log(parsedUpdateData);

    // Build tool_ids array for update
    const updateConfiguredToolIds = parsedUpdateData.configured_tools || [];
    const updatePythonToolIds = parsedUpdateData.python_code_tools || [];
    const updateToolIds = buildToolIdsArray(
      updateConfiguredToolIds,
      updatePythonToolIds
    );

    // Update the agent using the id if all fields are valid
    const updateAgentData: UpdateAgentRequest = {
      id: parsedUpdateData.id,
      role: parsedUpdateData.role,
      goal: parsedUpdateData.goal,
      backstory: parsedUpdateData.backstory,
      configured_tools: updateConfiguredToolIds,
      python_code_tools: updatePythonToolIds,
      llm_config: parsedUpdateData.llm_config,
      fcm_llm_config: parsedUpdateData.fcm_llm_config,
      realtime_agent: parsedUpdateData.realtime_agent, // Use the nested structure instead of realtime_config
      allow_delegation: parsedUpdateData.allow_delegation ?? false,
      memory: parsedUpdateData.memory ?? false,
      max_iter: parsedUpdateData.max_iter ?? undefined,
      max_rpm: parsedUpdateData.max_rpm ?? undefined,
      max_execution_time: parsedUpdateData.max_execution_time ?? undefined,
      cache: parsedUpdateData.cache ?? undefined,
      allow_code_execution: parsedUpdateData.allow_code_execution ?? false,
      max_retry_limit: parsedUpdateData.max_retry_limit ?? undefined,
      respect_context_window: parsedUpdateData.respect_context_window ?? false,
      default_temperature: parsedUpdateData.default_temperature ?? undefined,
      knowledge_collection: parsedUpdateData.knowledge_collection ?? null,
      tool_ids: updateToolIds,
    };

    this.agentsService.updateAgent(updateAgentData).subscribe({
      next: (updatedAgent) => {
        this.toastService.success(`Agent updated successfully`);
        console.log('Agent updated:', updatedAgent);
      },
      error: (error) => {
        console.error('Error updating agent:', error);
      },
      complete: () => {
        console.log('Agent update process completed.');
      },
    });
  }

  ngOnDestroy(): void {
    this.closePopup();
  }

  openSettingsDialog(agentData: TableFullAgent) {
    const dialogRef = this.dialog.open(AdvancedSettingsDialogComponent, {
      data: {
        agentRole: agentData.role,
        fullFcmLlmConfig: agentData.fullFcmLlmConfig,
        max_iter: agentData.max_iter ?? 20,
        max_rpm: agentData.max_rpm ?? null,
        max_execution_time: agentData.max_execution_time ?? null,
        cache: agentData.cache ?? false,
        allow_code_execution: agentData.allow_code_execution ?? false,
        max_retry_limit: agentData.max_retry_limit ?? null,
        respect_context_window: agentData.respect_context_window ?? false,
        default_temperature: agentData.default_temperature ?? null,
        knowledge_collection: agentData.knowledge_collection ?? null, // Changed parameter name
      },
    });

    dialogRef.closed.subscribe((updatedData: unknown) => {
      const data = updatedData as AdvancedSettingsData | undefined;
      if (data) {
        this.updateAgentDataInRow(data, agentData);
      }
    });
  }
  updateAgentDataInRow(
    updatedData: Partial<TableFullAgent>,
    agentData: TableFullAgent
  ): void {
    const index = this.rowData.findIndex((agent) => agent.id === agentData.id);
    if (index === -1) {
      console.error('Agent not found in rowData for update:', agentData);
      return;
    }

    console.log('Temperature:', updatedData.default_temperature);

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
    const isTempRow =
      !updatedAgent.id ||
      (typeof updatedAgent.id === 'string' &&
        updatedAgent.id.startsWith('temp_'));

    if (isTempRow) {
      console.warn(
        'Cannot update agent in the backend because it has a temporary ID:',
        updatedAgent
      );
      return;
    }

    // Get realtime config ID
    let realtimeConfigId = null;

    // First check if fullRealtimeConfig is directly available
    if (updatedAgent.fullRealtimeConfig?.id) {
      realtimeConfigId = updatedAgent.fullRealtimeConfig.id;
    }
    // Then check mergedConfigs if available
    else if (
      updatedAgent.mergedConfigs &&
      Array.isArray(updatedAgent.mergedConfigs)
    ) {
      const realtimeConfig = updatedAgent.mergedConfigs.find(
        (config) => config.type === 'realtime'
      );
      if (realtimeConfig) {
        realtimeConfigId = realtimeConfig.id;
      }
    }
    // Finally check the realtime_agent.realtime_config field directly
    else if (updatedAgent.realtime_agent?.realtime_config) {
      realtimeConfigId = updatedAgent.realtime_agent.realtime_config;
    }

    // Create or update the realtime_agent object
    const realtime_agent = {
      ...(updatedAgent.realtime_agent || {
        distance_threshold: '0.65',
        search_limit: 3,
        wake_word: '',
        stop_prompt: 'stop',
        language: null,
        voice_recognition_prompt: null,
        voice: 'alloy',
        realtime_transcription_config: null,
      }),
      realtime_config: realtimeConfigId,
    };

    // Build tool_ids array for settings update
    const settingsConfiguredToolIds = updatedAgent.configured_tools || [];
    const settingsPythonToolIds = updatedAgent.python_code_tools || [];
    const settingsToolIds = buildToolIdsArray(
      settingsConfiguredToolIds,
      settingsPythonToolIds
    );

    // Prepare the payload for the backend update request
    const updateAgentData: UpdateAgentRequest = {
      id: +updatedAgent.id,
      role: updatedAgent.role,
      goal: updatedAgent.goal,
      backstory: updatedAgent.backstory,
      configured_tools: settingsConfiguredToolIds,
      python_code_tools: settingsPythonToolIds,
      llm_config: updatedAgent.llm_config ?? null,
      fcm_llm_config: updatedAgent.fullFcmLlmConfig?.id
        ? updatedAgent.fullFcmLlmConfig?.id
        : updatedAgent.fcm_llm_config ?? null,
      realtime_agent: realtime_agent, // Use the nested structure instead of realtime_config
      allow_delegation: updatedAgent.allow_delegation ?? false,
      memory: updatedAgent.memory ?? false,
      max_iter: updatedAgent.max_iter ?? 20,
      max_rpm: updatedAgent.max_rpm ?? null,
      max_execution_time: updatedAgent.max_execution_time ?? null,
      cache: updatedAgent.cache ?? null,
      allow_code_execution: updatedAgent.allow_code_execution ?? null,
      max_retry_limit: updatedAgent.max_retry_limit ?? null,
      respect_context_window: updatedAgent.respect_context_window ?? null,
      default_temperature: updatedAgent.default_temperature ?? null,
      knowledge_collection: updatedAgent.knowledge_collection ?? null,
      tool_ids: settingsToolIds,
    };

    // Make the API call directly instead of trying to reuse onCellValueChanged
    this.agentsService.updateAgent(updateAgentData).subscribe({
      next: (updatedResponse) => {
        console.log('Agent updated successfully:', updatedResponse);
        this.toastService.success(`Agent updated successfully`);
      },
      error: (error) => {
        console.error('Error updating agent:', error);
      },
      complete: () => {
        console.log('Agent update process completed.');
      },
    });
  }

  public onCellContextMenu(event: CellContextMenuEvent) {
    if (!event.event) return;
    event.event.preventDefault();

    this.selectedRowData = event.data;
    const mouseEvent = event.event as MouseEvent;

    // Get the available space at the bottom of the screen
    const spaceBelow = window.innerHeight - mouseEvent.clientY;
    const spaceAbove = mouseEvent.clientY;

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
    // Make sure we have a selected row
    if (!this.selectedRowData) {
      console.log('No row selected');
      return;
    }

    const rowId = this.selectedRowData.id;
    console.log('Selected row ID for deletion:', rowId, 'Type:', typeof rowId);

    const isTempRow = typeof rowId === 'string' && rowId.startsWith('temp_');

    if (isTempRow) {
      console.log('Deleting temporary row:', rowId);

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

        console.log('Temporary row removed from grid');
        this.cdr.markForCheck();
      } else {
        console.warn('Temporary row not found in data array');
      }

      this.closeContextMenu();
      return;
    }

    // For permanent rows (with numeric IDs)
    const numericId =
      typeof rowId === 'number' ? rowId : parseInt(rowId as string, 10);

    if (isNaN(numericId)) {
      console.error('Invalid ID for deletion:', rowId);
      this.toastService.error('Cannot delete agent: Invalid ID');
      this.closeContextMenu();
      return;
    }

    // Call the API to delete the agent
    this.agentsService.deleteAgent(numericId).subscribe({
      next: () => {
        console.log('Agent deleted successfully on backend:', numericId);
        this.toastService.success('Agent deleted successfully');

        // Find the row in our local data array
        const index = this.rowData.findIndex((row) => {
          const rowIdNum =
            typeof row.id === 'number'
              ? row.id
              : parseInt(row.id as string, 10);
          return rowIdNum === numericId;
        });

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

          console.log(
            'Row removed from grid, new row count:',
            this.rowData.length
          );
          this.cdr.markForCheck();
        } else {
          console.warn('Row not found in data array after successful delete');
        }
      },
      error: (error) => {
        console.error('Error deleting agent:', error);
        this.toastService.error('Failed to delete agent');
      },
      complete: () => {
        this.closeContextMenu();
      },
    });
  }
  public handleCopy(): void {
    if (!this.selectedRowData) return;
    // Deep clone the selected row (to avoid mutating references)
    this.copiedRowData = JSON.parse(JSON.stringify(this.selectedRowData));
    console.log('Copied row:', this.copiedRowData);
    this.closeContextMenu();
  }

  public handlePasteBelow(): void {
    if (!this.selectedRowData || !this.copiedRowData) return;
    const index = this.rowData.findIndex((row) => row === this.selectedRowData);
    if (index === -1) return;
    this.pasteNewAgentAt(index + 1);
  }

  public handlePasteAbove(): void {
    if (!this.selectedRowData || !this.copiedRowData) return;
    const index = this.rowData.findIndex((row) => row === this.selectedRowData);
    if (index === -1) return;
    this.pasteNewAgentAt(index);
  }

  public closeContextMenu(): void {
    this.contextMenuVisible.set(false);
  }
  private pasteNewAgentAt(insertIndex: number): void {
    const tempId = `temp_${Date.now()}_${Math.random()
      .toString(36)
      .substr(2, 9)}`;

    // Create a deep copy of the copied row data
    const newAgentData: TableFullAgent = {
      ...JSON.parse(JSON.stringify(this.copiedRowData)),
      id: tempId, // Use temporary ID
    };

    // Add the new agent to our local data array at the correct position
    this.rowData.splice(insertIndex, 0, newAgentData);

    // Apply the transaction to add the row to the grid
    this.gridApi.applyTransaction({
      add: [newAgentData],
      addIndex: insertIndex,
    });

    // Refresh the index column
    this.gridApi.refreshCells({
      force: true,
      columns: ['index'],
    });

    this.cdr.markForCheck();

    // Get realtime config ID
    let realtimeConfigId = null;

    // First check if fullRealtimeConfig is directly available
    if (newAgentData.fullRealtimeConfig?.id) {
      realtimeConfigId = newAgentData.fullRealtimeConfig.id;
    }
    // Then check mergedConfigs if available
    else if (
      newAgentData.mergedConfigs &&
      Array.isArray(newAgentData.mergedConfigs)
    ) {
      const realtimeConfig = newAgentData.mergedConfigs.find(
        (config) => config.type === 'realtime'
      );
      if (realtimeConfig) {
        realtimeConfigId = realtimeConfig.id;
      }
    }
    // Finally check the realtime_agent.realtime_config field directly
    else if (newAgentData.realtime_agent?.realtime_config) {
      realtimeConfigId = newAgentData.realtime_agent.realtime_config;
    }

    // Create or update the realtime_agent object
    const realtime_agent = {
      ...(newAgentData.realtime_agent || {
        distance_threshold: '0.65',
        search_limit: 3,
        wake_word: '',
        stop_prompt: 'stop',
        language: null,
        voice_recognition_prompt: null,
        voice: 'alloy',
        realtime_transcription_config: null,
      }),
      realtime_config: realtimeConfigId,
    };

    const configuredToolIds = newAgentData.configured_tools || [];
    const pythonToolIds = newAgentData.python_code_tools || [];
    const toolIds = buildToolIdsArray(configuredToolIds, pythonToolIds);

    const createAgentData: CreateAgentRequest = {
      role: newAgentData.role,
      goal: newAgentData.goal,
      backstory: newAgentData.backstory,
      configured_tools: configuredToolIds,
      python_code_tools: pythonToolIds,
      llm_config: newAgentData.llm_config ?? null,
      fcm_llm_config: newAgentData.fcm_llm_config ?? null,
      realtime_agent: realtime_agent, // Use the nested structure instead of realtime_config
      allow_delegation: newAgentData.allow_delegation ?? false,
      memory: newAgentData.memory ?? false,
      max_iter: newAgentData.max_iter ?? 20,
      max_rpm: newAgentData.max_rpm ?? null,
      max_execution_time: newAgentData.max_execution_time ?? null,
      cache: newAgentData.cache ?? null,
      allow_code_execution: newAgentData.allow_code_execution ?? null,
      max_retry_limit: newAgentData.max_retry_limit ?? null,
      respect_context_window: newAgentData.respect_context_window ?? null,
      default_temperature: newAgentData.default_temperature ?? null,
      knowledge_collection: newAgentData.knowledge_collection ?? null,
      tool_ids: toolIds as ToolUniqueName[],
    };

    this.agentsService.createAgent(createAgentData).subscribe({
      next: (createdAgent) => {
        console.log('New agent created from pasted row:', createdAgent);

        // Find the row in our local data array
        const rowIndex = this.rowData.findIndex((row) => row.id === tempId);

        if (rowIndex !== -1) {
          // Get the original temp ID before changing it
          const tempRowId = this.rowData[rowIndex].id;

          // Update the ID in our local data array
          this.rowData[rowIndex].id = createdAgent.id;

          // Get the row node using the original temp ID
          const rowNode = this.gridApi.getRowNode(tempRowId.toString());

          if (rowNode) {
            // Update the node's data directly
            rowNode.setData({ ...this.rowData[rowIndex] });
          }

          // Refresh the grid to show the changes
          this.gridApi.refreshCells({ force: true });
        }

        this.toastService.success(`Agent created successfully`);
      },
      error: (error) => {
        console.error('Error creating agent from pasted row:', error);

        // Find and remove the row with temp ID from our data array
        const rowIndex = this.rowData.findIndex((row) => row.id === tempId);
        if (rowIndex !== -1) {
          this.rowData.splice(rowIndex, 1);
        }

        // Remove from the grid
        this.gridApi.setGridOption('rowData', [...this.rowData]);

        this.toastService.error('Failed to create agent');
      },
    });

    this.closeContextMenu();
  }
  public handleAddEmptyAgentAbove(): void {
    if (!this.selectedRowData) return;
    const index = this.rowData.findIndex((row) => row === this.selectedRowData);
    if (index === -1) return;
    this.insertEmptyAgentAt(index);
  }

  public handleAddEmptyAgentBelow(): void {
    if (!this.selectedRowData) return;
    const index = this.rowData.findIndex((row) => row === this.selectedRowData);
    if (index === -1) return;
    this.insertEmptyAgentAt(index + 1);
  }

  private insertEmptyAgentAt(insertIndex: number): void {
    const emptyAgent = this.createEmptyFullAgent();

    // Add to internal data array
    this.rowData.splice(insertIndex, 0, emptyAgent);

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
  private onCellClicked(event: CellClickedEvent<any, any>): void {
    if (event.colDef.field === 'actions') {
      const agentData = event.data;
      this.closePopup();

      this.openSettingsDialog(agentData);
    }
    const columnId = event.column.getColId();
    // Process only specific columns.
    if (
      columnId !== 'mergedConfigs' &&
      columnId !== 'mergedTools' &&
      columnId !== 'tags'
    ) {
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

  private onCellKeyDown(event: CellKeyDownEvent<any, any>): void {
    const keyboardEvent = event.event as KeyboardEvent;

    if (keyboardEvent?.key === 'Enter') {
      const { rowIndex, column } = event;
      const columnId = column.getColId();
      if (event.colDef.field === 'actions') {
        const agentData = event.data;
        this.closePopup();

        this.openSettingsDialog(agentData);
        return;
      }
      // Process only specific columns
      if (
        columnId === 'mergedConfigs' ||
        columnId === 'mergedTools' ||
        columnId === 'tags'
      ) {
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
    this.currentPopupCell = cell;

    // Get the container cell element.
    let target = (event.event!.target as HTMLElement).closest(
      '.ag-cell'
    ) as HTMLElement;
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
      popupRef.instance.configsSelected.subscribe((mergedConfigs: any[]) => {
        console.log('Selected configs:', mergedConfigs);

        if (this.currentPopupCell) {
          const rowIndex = this.currentPopupCell.rowIndex;
          const rowNode = this.gridApi.getDisplayedRowAtIndex(rowIndex);

          if (rowNode) {
            // Update the mergedConfigs in the row data
            rowNode.setDataValue('mergedConfigs', mergedConfigs);
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
      popupRef.instance.mergedToolsUpdated.subscribe(
        (updatedMergedTools: string[]) => {
          console.log('Returned from tools popup:', updatedMergedTools);
          if (this.currentPopupCell) {
            const rowIndex = this.currentPopupCell.rowIndex;

            // Get the row node using the row index
            const rowNode = this.gridApi.getDisplayedRowAtIndex(rowIndex);
            if (rowNode) {
              // Use setDataValue to update the mergedTools cell
              rowNode.setDataValue('mergedTools', updatedMergedTools);
            }
          }

          // Close the popup after saving
          this.closePopup();
        }
      );

      // Handle cancel event
      popupRef.instance.cancel.subscribe(() => {
        this.closePopup();
      });
    } else if (cell.columnId === 'tags') {
      const portal = new ComponentPortal(TagsPopupComponent);
      const popupRef = this.popupOverlayRef.attach(portal);
      popupRef.instance.cellTags = event.data?.tags || [];

      popupRef.instance.tagsSaved.subscribe((updatedTags: string[]) => {
        console.log('Updated tags:', updatedTags);

        if (this.currentPopupCell) {
          const rowIndex = this.currentPopupCell.rowIndex;

          // Get the row node using the row index
          const rowNode = this.gridApi.getDisplayedRowAtIndex(rowIndex);
          if (rowNode) {
            // Use setDataValue to update the tags cell
            rowNode.setDataValue('tags', updatedTags);
          }
        }

        // Close the popup after saving
        this.closePopup();
      });
    }
    // Use Renderer2 to attach a global click listener.
    this.globalClickUnlistener = this.renderer.listen(
      'document',
      'click',
      (evt: MouseEvent) => this.onDocumentClick(evt)
    );

    // Attach a global keydown listener to close the popup on Escape key.
    this.globalKeydownUnlistener = this.renderer.listen(
      'document',
      'keydown',
      (evt: KeyboardEvent) => {
        if (evt.key === 'Escape') {
          this.closePopup();
        }
      }
    );
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
}
