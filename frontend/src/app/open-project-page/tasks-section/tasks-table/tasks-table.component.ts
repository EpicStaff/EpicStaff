import {
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  EventEmitter,
  Inject,
  Input,
  Output,
  Renderer2,
  signal,
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
  ICellRendererParams,
  RowDragEndEvent,
} from 'ag-grid-community';
import { AllCommunityModule, ModuleRegistry } from 'ag-grid-community';

import { themeQuartz } from 'ag-grid-community';

import { ConnectedPosition, Overlay, OverlayRef } from '@angular/cdk/overlay';
import { ComponentPortal } from '@angular/cdk/portal';
import { DialogModule, Dialog } from '@angular/cdk/dialog';
import {
  AdvancedSettingsDialogComponent,
  AdvancedSettingsData,
} from '../../../pages/staff-page/components/advanced-settings-dialog.component.ts/advanced-settings-dialog.component';
import { LLMPopupComponent } from '../../../pages/staff-page/components/cell-popups-and-modals/llm-selector-popup/llm-popup.component';
import { TagsPopupComponent } from '../../../pages/staff-page/components/cell-popups-and-modals/tags-popup/tags-popup.component';
import { IndexCellRendererComponent } from '../../../pages/staff-page/components/cell-renderers/index-row-cell-renderer/custom-row-height.component';
import { ToolsPopupComponent } from '../../../pages/staff-page/components/cell-popups-and-modals/tools-selector-popup/tools-popup.component';
import { AgGridContextMenuComponent } from '../../../pages/staff-page/components/context-menu/ag-grid-context-menu.component';
import { PreventContextMenuDirective } from '../../../pages/staff-page/components/directives/prevent-context-menu.directive';
import { DelegationHeaderComponent } from '../../../pages/staff-page/components/header-renderers/delegation-header.component';
import { MemoryHeaderComponent } from '../../../pages/staff-page/components/header-renderers/memory-header.component';
import {
  TableFullAgent,
  FullAgentService,
  FullAgent,
} from '../../../services/full-agent.service';
import { AgentsService } from '../../../services/staff.service';
import { ClickOutsideDirective } from '../../../shared/directives/click-outside.directive';
import {
  CreateAgentRequest,
  UpdateAgentRequest,
} from '../../../shared/models/agent.model';
import { FullTask } from '../../../shared/models/full-task.model';
import {
  CreateTaskRequest,
  GetTaskRequest,
  TableFullTask,
  UpdateTaskRequest,
} from '../../../shared/models/task.model';
import { FullTaskService } from '../../../services/full-task.service';
import { buildToolIdsArray } from '../../../shared/utils/tool-ids-builder.util';
import { AgentSelectionPopupComponent } from './popups/agent-select-popup/agent-selection-popup.component';
import { GetProjectRequest } from '../../../features/projects/models/project.model';
import { TasksService } from '../../../services/tasks.service';
import { ProjectStateService } from '../../services/project-state.service';
import {
  AdvancedTaskSettingsData,
  AdvancedTaskSettingsDialogComponent,
} from './advanced-task-settings-dialog/advanced-task-settings-dialog.component';
import { AsyncHeaderComponent } from './header-renderers/async-exec-header/async-header.component';
import { HumanInputHeaderComponent } from './header-renderers/human-input-header/human-input.component';
import { forkJoin, Observable } from 'rxjs';
import { ToastService } from '../../../services/notifications/toast.service';

ModuleRegistry.registerModules([AllCommunityModule]);

interface CellInfo {
  columnId: string;
  rowIndex: number;
}
type PopupEvent = CellClickedEvent<any, any> | CellKeyDownEvent<any, any>;

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
export class TasksTableComponent {
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
  private currentPopupCell: any = null;
  private currentCellElement: HTMLElement | null = null;
  private globalClickUnlistener: (() => void) | null = null;
  private globalKeydownUnlistener: (() => void) | null = null;

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
    this.rowData = [
      ...this.tasks,
      this.createEmptyFullTask(),
      this.createEmptyFullTask(),
    ];
    this.isLoaded = true;
    this.cdr.markForCheck();
  }

  onGridReady(event: any): void {
    this.gridApi = event.api;
  }
  private createEmptyFullTask(): TableFullTask {
    // Create a temporary ID for new tasks
    const tempId = `temp_${Date.now()}_${Math.random()
      .toString(36)
      .substr(2, 9)}`;

    return {
      id: tempId, // Use temp ID instead of null
      name: '',
      instructions: '',
      expected_output: '',
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
      cellClass: 'agent-role-cell',
      cellEditor: 'agLargeTextCellEditor',
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
      cellEditor: 'agLargeTextCellEditor',
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
      field: 'expected_output',
      cellEditor: 'agLargeTextCellEditor',
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
    {
      headerName: 'Assigned Agent',
      field: 'agentData', // Reference the agentData field
      editable: false,
      minWidth: 240,
      maxWidth: 260,
      cellRenderer: (params: any) => {
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
      cellRenderer: (params: ICellRendererParams) => {
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

      if (
        params.data.id &&
        typeof params.data.id === 'string' &&
        params.data.id.startsWith('temp_')
      ) {
        return params.data.id;
      }

      const tempId = `temp_${Date.now()}_${Math.random()
        .toString(36)
        .substr(2, 9)}`;
      params.data.id = tempId;
      return tempId;
    },

    onCellClicked: (event: CellClickedEvent<any, any>) =>
      this.onCellClicked(event),
    onCellKeyDown: (event: CellKeyDownEvent) => this.onCellKeyDown(event),
    onCellValueChanged: (event) => this.onCellValueChanged(event),
    onRowDragEnd: (event) => this.onRowDragEnd(event),
  };
  // Event handler for rowDragEnd
  onRowDragEnd(event: RowDragEndEvent) {
    // Get the moved data
    const movedData = event.node.data;
    const index = this.rowData.findIndex((row) => row === movedData);

    if (index !== -1) {
      // Remove the row from its old position
      this.rowData.splice(index, 1);
      // Insert it into the new position
      this.rowData.splice(event.overIndex, 0, movedData);

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
  }
  private parseTaskData(taskData: FullTask) {
    const agentData = taskData.agentData || null;
    const agentId = agentData ? agentData.id : null;
    const crew = this.project ? this.project.id : null;

    // Process merged tools similar to agents table
    const mergedTools = (taskData as any).mergedTools || [];

    return {
      ...taskData,
      agent: agentId,
      crew: crew,
      configured_tools: mergedTools
        .filter((tool: any) => tool.type === 'tool-config')
        .map((tool: any) => tool.id),
      python_code_tools: mergedTools
        .filter((tool: any) => tool.type === 'python-tool')
        .map((tool: any) => tool.id),
    };
  }

  private onCellValueChanged(event: CellValueChangedEvent): void {
    const colId = event.column.getColId();
    const fieldsToValidate = ['name', 'instructions', 'expected_output'];

    // Check if this is a temporary task
    const isTempTask =
      !event.data.id ||
      (typeof event.data.id === 'string' && event.data.id.startsWith('temp_'));

    if (isTempTask) {
      // Validate the required fields
      const isValid = fieldsToValidate.every((field) => {
        const fieldValue = event.data[field] ? event.data[field].trim() : '';
        event.data[`${field}Warning`] = !fieldValue;
        return fieldValue !== '';
      });

      if (!isValid) {
        console.warn('Warning: One or more required fields are empty.');
        return;
      }

      // Parse the task data
      const parsedData = this.parseTaskData(event.data);

      // Build tool_ids array for task creation
      const configuredToolIds = parsedData.configured_tools || [];
      const pythonToolIds = parsedData.python_code_tools || [];
      const toolIds = buildToolIdsArray(configuredToolIds, pythonToolIds);

      // Create the new task
      const createTaskData: CreateTaskRequest = {
        name: parsedData.name,
        instructions: parsedData.instructions,
        expected_output: parsedData.expected_output,
        order: parsedData.order ?? null,
        human_input: parsedData.human_input ?? false,
        async_execution: parsedData.async_execution ?? false,
        config: parsedData.config ?? null,
        output_model: parsedData.output_model ?? null,
        crew: parsedData.crew,
        agent: parsedData.agent,
        task_context_list: parsedData.task_context_list ?? [],
        tool_ids: toolIds,
      };

      this.tasksService.createTask(createTaskData).subscribe({
        next: (newTask: GetTaskRequest) => {
          console.log('Task created successfully:', newTask);

          event.data.id = newTask.id;

          this.gridApi.refreshCells({
            rowNodes: [event.node],
            force: true,
          });

          const agentData = this.agents.find(
            (agent) => agent.id === newTask.agent
          );

          const fullTask: FullTask = {
            ...newTask,
            agentData: agentData || null,
          };

          this.projectStateService.addTask(fullTask);

          const emptyTask = this.createEmptyFullTask();

          this.rowData.push(emptyTask);
          this.gridApi.applyTransaction({ add: [emptyTask] });

          this.toastService.success('Task added successfully');

          this.cdr.markForCheck();

          this.updateTaskOrders();
        },
        error: (err) => console.error('Error creating task:', err),
      });

      return;
    }

    let allValid = true;
    fieldsToValidate.forEach((field) => {
      const fieldValue = event.data[field] ? event.data[field].trim() : '';
      event.data[`${field}Warning`] = !fieldValue;
      if (!fieldValue) {
        allValid = false;
      }
    });

    this.gridApi.refreshCells({
      rowNodes: [event.node],
      columns: [colId],
    });

    if (!allValid) {
      console.warn('Warning: One or more required fields are empty.');
      return;
    }

    const parsedUpdateData = this.parseTaskData(event.data);

    // Build tool_ids array for task update
    const updateConfiguredToolIds = parsedUpdateData.configured_tools || [];
    const updatePythonToolIds = parsedUpdateData.python_code_tools || [];
    const updateToolIds = buildToolIdsArray(
      updateConfiguredToolIds,
      updatePythonToolIds
    );

    if (typeof parsedUpdateData.id === 'string') {
      parsedUpdateData.id = +parsedUpdateData.id;
    }

    // Create update request with tool_ids
    const updateTaskRequest: UpdateTaskRequest = {
      ...parsedUpdateData,
      tool_ids: updateToolIds,
    };

    this.tasksService.updateTask(updateTaskRequest).subscribe({
      next: (updatedResponse) => {
        console.log('Task updated successfully:', updatedResponse);
        this.toastService.success('Task updated successfully');
        this.projectStateService.updateTask(parsedUpdateData);
      },
      error: (error) => {
        console.error('Error updating task:', error);
      },
      complete: () => {
        console.log('Task update process completed.');
      },
    });
  }

  ngOnDestroy(): void {
    this.closePopup();
  }

  openSettingsDialog(taskData: TableFullTask) {
    // Filter tasks with normal IDs (numeric IDs), non-null orders, and orders less than current task
    const normalTasks: TableFullTask[] = this.rowData.filter((task) => {
      // Check if the ID is a number or a string that can be parsed as a number
      const hasNormalId =
        typeof task.id === 'number' ||
        (typeof task.id === 'string' && !task.id.startsWith('temp'));

      // Remove tasks with null order
      if (task.order === null) {
        return false;
      }

      // Remove tasks with order greater than or equal to current task's order
      // Only keep tasks with order < taskData.order (strictly less than)
      const hasValidOrder =
        taskData.order !== null && task.order < taskData.order;

      return hasNormalId && hasValidOrder;
    });

    console.log('Filtered tasks (normal IDs & valid order):', normalTasks);

    const dialogRef = this.dialog.open(AdvancedTaskSettingsDialogComponent, {
      data: {
        config: taskData.config,
        output_model: taskData.output_model,
        task_context_list: taskData.task_context_list,
        taskName: taskData.name,
        availableTasks: normalTasks, // Pass filtered tasks to dialog
      },
      width: '100%', // Set minimum width
      maxWidth: '650px', // Allow it to be responsive but not too wide
      height: '100%', // Set height to 90% of viewport height
      maxHeight: '90vh', // Ensure maximum height
    });

    dialogRef.closed.subscribe((updatedData: unknown) => {
      const data: AdvancedTaskSettingsData | undefined = updatedData as
        | AdvancedTaskSettingsData
        | undefined;
      if (data) {
        this.updateTaskDataInRow(data, taskData);
      }
    });
  }

  updateTaskDataInRow(
    updatedData: Partial<TableFullTask>,
    taskData: TableFullTask
  ): void {
    const index = this.rowData.findIndex((task) => task === taskData);
    if (index === -1) {
      console.error('Task not found in rowData for update:', taskData);
      return;
    }

    // Create an updated version of the task
    const updatedTask: TableFullTask = {
      ...this.rowData[index],
      ...updatedData,
    };

    // Update our local row data
    this.rowData[index] = updatedTask;

    // Use transaction API to update the grid
    this.gridApi.applyTransaction({ update: [updatedTask] });

    // Mark for change detection
    this.cdr.markForCheck();

    // Check if this is a temporary task
    const isTempTask =
      !updatedTask.id ||
      (typeof updatedTask.id === 'string' &&
        updatedTask.id.startsWith('temp_'));

    if (isTempTask) {
      console.warn(
        'Task has a temporary ID, not updating backend:',
        updatedTask
      );
      return;
    }

    // Parse the task data to extract tools
    const parsedTaskData = this.parseTaskData(updatedTask as any);

    // Build tool_ids array for settings update
    const settingsConfiguredToolIds = parsedTaskData.configured_tools || [];
    const settingsPythonToolIds = parsedTaskData.python_code_tools || [];
    const settingsToolIds = buildToolIdsArray(
      settingsConfiguredToolIds,
      settingsPythonToolIds
    );

    // Prepare the payload for the backend update request
    const updateTaskData = {
      id: +updatedTask.id,
      name: updatedTask.name,
      instructions: updatedTask.instructions,
      expected_output: updatedTask.expected_output,
      order: updatedTask.order,
      human_input: updatedTask.human_input,
      async_execution: updatedTask.async_execution,
      config: updatedTask.config,
      output_model: updatedTask.output_model,
      crew: updatedTask.crew,
      agent: updatedTask.agent,
      task_context_list: updatedTask.task_context_list,
      tool_ids: settingsToolIds,
    };

    // Call the update service
    this.tasksService.updateTask(updateTaskData).subscribe({
      next: (updatedResponse) => {
        console.log('Task updated successfully:', updatedResponse);

        // Create a properly typed version of the task for the project state service
        const taskForState: FullTask = {
          ...updatedTask,
          id: +updatedTask.id, // Convert to number
        };

        // Update the project state
        this.projectStateService.updateTask(taskForState);

        // Notify user of success
        this.toastService.success('Task updated successfully');
      },
      error: (error) => {
        console.error('Error updating task:', error);
        // Optionally show error toast
        this.toastService.error('Failed to update task');
      },
      complete: () => {
        console.log('Task update process completed.');
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
    const index = this.rowData.findIndex(
      (row: TableFullTask) => row === this.selectedRowData
    );
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
      (typeof this.selectedRowData.id === 'string' &&
        this.selectedRowData.id.startsWith('temp_'));

    if (isTempRow) {
      // For temporary rows, remove directly without backend call
      const localIndex = this.rowData.findIndex(
        (row) => row === this.selectedRowData
      );

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

        console.log('Deleted temporary row:', this.selectedRowData);
        this.cdr.markForCheck();
      } else {
        console.warn('Row not found for local deletion.');
      }

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
    let removedRow = this.rowData.splice(index, 1)[0];

    // Refresh the grid with the updated data
    this.gridApi.setGridOption('rowData', [...this.rowData]);

    // Refresh index column
    this.gridApi.refreshCells({
      force: true,
      columns: ['index'],
    });

    this.cdr.markForCheck();

    // Convert ID to number if it's a string
    const idToDelete =
      typeof rowToDelete.id === 'string' ? +rowToDelete.id : rowToDelete.id;

    this.tasksService.deleteTask(idToDelete).subscribe({
      next: () => {
        // Convert ID to number for project state service
        const idForState =
          typeof rowToDelete.id === 'string' ? +rowToDelete.id : rowToDelete.id;
        this.projectStateService.deleteTask(idForState);

        this.updateTaskOrders();
        this.toastService.success('Task deleted successfully');
      },
      error: (error) => {
        console.error('Error deleting task:', error);

        // Revert the deletion if the API call fails
        if (removedRow && index !== -1) {
          this.rowData.splice(index, 0, removedRow);

          // Refresh the grid with the restored data
          this.gridApi.setGridOption('rowData', [...this.rowData]);

          // Refresh index column after restoring
          this.gridApi.refreshCells({
            force: true,
            columns: ['index'],
          });

          this.cdr.markForCheck();
          this.toastService.error('Failed to delete task');
        }
      },
      complete: () => {
        this.closeContextMenu();
      },
    });
  }
  public closeContextMenu(): void {
    this.contextMenuVisible.set(false);
  }
  private pasteNewTaskAt(insertIndex: number): void {
    // Create a temporary ID for the new task
    const tempId = `temp_${Date.now()}_${Math.random()
      .toString(36)
      .substr(2, 9)}`;

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
    const pasteToolIds = buildToolIdsArray(
      pasteConfiguredToolIds,
      pastePythonToolIds
    );

    const createTaskData: CreateTaskRequest = {
      name: newTaskData.name,
      instructions: newTaskData.instructions,
      expected_output: newTaskData.expected_output,
      order: newTaskData.order ?? null,
      human_input: newTaskData.human_input ?? false,
      async_execution: newTaskData.async_execution ?? false,
      config: newTaskData.config ?? null,
      output_model: newTaskData.output_model ?? null,
      crew: newTaskData.crew ?? null,
      agent: newTaskData.agent ?? null,
      task_context_list: newTaskData.task_context_list ?? [],
      tool_ids: pasteToolIds,
    };

    this.tasksService.createTask(createTaskData).subscribe({
      next: (newTask: GetTaskRequest) => {
        console.log('Task created successfully:', newTask);

        // Update the ID in our task data
        newTaskData.id = newTask.id;

        // Update the grid without re-rendering entirely
        this.gridApi.applyTransaction({ update: [newTaskData] });

        // Map agent data from the agents array based on agent id
        const agentData = this.agents.find(
          (agent) => agent.id === newTask.agent
        );

        // Create a FullTask by merging GetTaskRequest and agent data
        const fullTask: FullTask = {
          ...newTask,
          agentData: agentData || null,
        };

        this.projectStateService.addTask(fullTask);
        this.toastService.success('Task created successfully');
        this.updateTaskOrders();
      },
      error: (err) => {
        console.error('Error creating task:', err);

        // Remove the row if there was an error
        this.gridApi.applyTransaction({ remove: [newTaskData] });
        this.toastService.error('Failed to create task');
      },
      complete: () => {
        console.log('Task creation completed');
      },
    });

    this.closeContextMenu();
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

    // Update the order for all tasks
    this.rowData.forEach((row, i) => {
      row.order = i;
    });

    // Refresh order cells
    this.gridApi.refreshCells({
      force: true,
      columns: ['order'],
    });

    // Mark for change detection
    this.cdr.markForCheck();

    this.closeContextMenu();
  }

  updateTaskOrders(): void {
    // Filter out rows with null or temporary IDs to get only existing tasks
    const tasksWithIds = this.rowData.filter((task: TableFullTask) => {
      // Filter out null IDs
      if (task.id === null) return false;

      // Filter out temporary IDs
      if (typeof task.id === 'string' && task.id.startsWith('temp_'))
        return false;

      // Keep only tasks with valid IDs
      return true;
    });

    // Create an array of update requests with new order values
    const updateRequests: Observable<GetTaskRequest>[] = tasksWithIds.map(
      (task, index) => {
        console.log('updating task order', task);

        // Ensure ID is a number
        const taskId = typeof task.id === 'string' ? +task.id : task.id;

        // Use PATCH method to update only the order
        return this.tasksService.patchTaskOrder(taskId, index + 1);
      }
    );

    // Execute all update requests in parallel using forkJoin
    if (updateRequests.length > 0) {
      forkJoin(updateRequests).subscribe({
        next: (results) => {
          console.log('All task orders updated successfully:', results);

          // Update local state to reflect the new orders
          results.forEach((updatedTask) => {
            const index = this.rowData.findIndex((row) => {
              // Handle case where row.id might be a string
              if (typeof row.id === 'string') {
                return +row.id === updatedTask.id;
              }
              return row.id === updatedTask.id;
            });

            if (index !== -1) {
              this.rowData[index].order = updatedTask.order;
            }
          });

          // Refresh order cells to reflect updates
          this.gridApi.refreshCells({
            force: true,
            columns: ['order'],
          });

          // Notify the state service with proper FullTask objects
          results.forEach((updatedTask) => {
            // Find the corresponding row to get the agentData
            const rowWithAgentData = this.rowData.find((row) => {
              if (typeof row.id === 'string') {
                return +row.id === updatedTask.id;
              }
              return row.id === updatedTask.id;
            });

            if (rowWithAgentData) {
              // Create a FullTask object with the agentData from our original row
              const fullTask: FullTask = {
                ...updatedTask,
                agentData: rowWithAgentData.agentData,
              };
              this.projectStateService.updateTask(fullTask);
            }
          });

          this.cdr.markForCheck();
        },
        error: (error) => {
          console.error('Error updating task orders:', error);
          this.toastService.error('Failed to update task orders');
        },
      });
    }
  }
  private onCellClicked(event: CellClickedEvent<any, any>): void {
    if (event.colDef.field === 'actions') {
      const taskData: TableFullTask = event.data;
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

  private onCellKeyDown(event: CellKeyDownEvent<any, any>): void {
    const keyboardEvent = event.event as KeyboardEvent;

    if (keyboardEvent?.key === 'Enter') {
      const { rowIndex, column } = event;
      const columnId = column.getColId();
      if (event.colDef.field === 'actions') {
        const taskData = event.data;
        console.log(event.data);
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
      popupRef.instance.agentSelected.subscribe((selectedAgent: FullAgent) => {
        console.log('Selected agent:', selectedAgent);

        if (this.currentPopupCell) {
          const rowIndex = this.currentPopupCell.rowIndex;
          const rowNode = this.gridApi.getDisplayedRowAtIndex(rowIndex);
          if (rowNode) {
            // Update the agentData cell value with the selected agent
            rowNode.setDataValue('agentData', selectedAgent); // Set the selected agent in the cell
          }
        }
        // Close the popup after selecting an agent
        this.closePopup();
      });
    }

    if (cell.columnId === 'mergedTools') {
      const portal = new ComponentPortal(ToolsPopupComponent);
      const popupRef = this.popupOverlayRef.attach(portal);
      popupRef.instance.mergedTools = event.data?.mergedTools || [];

      popupRef.instance.mergedToolsUpdated.subscribe(
        (
          updatedMergedTools: {
            id: number;
            configName: string;
            toolName: string;
            type: string;
          }[]
        ) => {
          if (this.currentPopupCell) {
            const rowIndex = this.currentPopupCell.rowIndex;
            const rowNode = this.gridApi.getDisplayedRowAtIndex(rowIndex);
            if (rowNode) {
              rowNode.setDataValue('mergedTools', updatedMergedTools);
            }
          }
          this.closePopup();
        }
      );

      // Handle cancel event
      popupRef.instance.cancel.subscribe(() => {
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
}
