import {
  Component,
  OnInit,
  OnDestroy,
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Input,
  OnChanges,
  SimpleChanges,
  Output,
  EventEmitter,
  ViewChild,
  ElementRef,
  AfterViewInit,
} from '@angular/core';
import { forkJoin, Subject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';
import { NgClass, NgFor, NgIf } from '@angular/common';
import { animate, style, transition, trigger } from '@angular/animations';
import { FormsModule } from '@angular/forms';

import { GetPythonCodeToolRequest } from '../../../../../features/tools/models/python-code-tool.model';
import { GetMcpToolRequest } from '../../../../../features/tools/models/mcp-tool.model';
import { BuiltinToolsService } from '../../../../../features/tools/services/builtin-tools/builtin-tools.service';
import { ToolConfigService } from '../../../../../services/tool_config.service';
import {
  FullToolConfig,
  FullToolConfigService,
} from '../../../../../services/full-tool-config.service';
import { PythonCodeToolService } from '../../../../../user-settings-page/tools/custom-tool-editor/services/pythonCodeToolService.service';
import { GetToolConfigRequest } from '../../../../../features/tools/models/tool_config.model';
import { ToastService } from '../../../../../services/notifications/toast.service';
import { ToolItemComponent } from './tool-item/tool-item.component';
import { PythonToolItemComponent } from './python-tool-item/python-tool-item.component';
import { McpToolItemComponent } from './mcp-tool-item/mcp-tool-item.component';
import { ButtonComponent } from '../../../../../shared/components/buttons/button/button.component';
import { CustomToolDialogComponent } from '../../../../../user-settings-page/tools/custom-tool-editor/custom-tool-dialog.component';
import { McpToolDialogComponent } from '../../../../../features/tools/components/mcp-tool-dialog/mcp-tool-dialog.component';
import { Dialog } from '@angular/cdk/dialog';
import { CustomToolsService } from '../../../../../features/tools/services/custom-tools/custom-tools.service';
import { McpToolsService } from '../../../../../features/tools/services/mcp-tools/mcp-tools.service';
import { Router } from '@angular/router';

@Component({
  selector: 'app-tools-list',
  standalone: true,
  imports: [
    NgFor,
    NgIf,

    FormsModule,
    ToolItemComponent,
    PythonToolItemComponent,
    McpToolItemComponent,

    ButtonComponent,
  ],
  templateUrl: './tools-popup.component.html',
  styleUrls: ['./tools-popup.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
  animations: [
    trigger('expandCollapse', [
      transition(':enter', [
        style({ height: '0', opacity: 0 }),
        animate(
          '300ms cubic-bezier(0.34, 1.56, 0.64, 1)',
          style({ height: '*', opacity: 1 })
        ),
      ]),
      transition(':leave', [
        style({ height: '*', opacity: 1 }),
        animate('200ms ease-out', style({ height: '0', opacity: 0 })),
      ]),
    ]),
  ],
})
export class ToolsPopupComponent
  implements OnInit, OnChanges, OnDestroy, AfterViewInit {
  @ViewChild('searchInput') private searchInput!: ElementRef;
  @Input() public mergedTools: {
    id: number;
    configName: string;
    toolName: string;
    type: string;
  }[] = [];
  @Output() public mergedToolsUpdated = new EventEmitter<
    { id: number; configName: string; toolName: string; type: string }[]
  >();

  @Output() public cancel = new EventEmitter<void>();

  public menuItems: { type: 'builtin' | 'custom' | 'mcp'; label: string }[] = [
    { type: 'builtin', label: 'Built-in Tools' },
    { type: 'custom', label: 'Custom Tools' },
    { type: 'mcp', label: 'MCP Tools' },
  ];
  public selectedMenu: 'builtin' | 'custom' | 'mcp' = 'builtin';
  public searchTerm = '';
  public loading = true;

  public tools: FullToolConfig[] = [];
  public pythonTools: GetPythonCodeToolRequest[] = [];
  public mcpTools: GetMcpToolRequest[] = [];

  public selectedToolConfigs = new Set<number>();
  public selectedPythonTools = new Set<number>();
  public selectedMcpTools = new Set<number>();

  public showPythonTools = false;
  public expandedToolConfigs = new Set<number>();

  private readonly _destroyed$ = new Subject<void>();

  constructor(
    private readonly _toolsService: BuiltinToolsService,
    private readonly _toolConfigService: ToolConfigService,
    private readonly _pythonCodeToolService: PythonCodeToolService,
    private readonly _fullToolConfigService: FullToolConfigService,
    private readonly _cdr: ChangeDetectorRef,
    private readonly toastService: ToastService,
    private readonly cdkDialog: Dialog,
    private readonly customToolsService: CustomToolsService,
    private readonly mcpToolsService: McpToolsService,
    private readonly router: Router,
    private readonly cdr: ChangeDetectorRef,


  ) { }

  public ngOnInit(): void {
    console.log('ToolsPopupComponent initialized.');
    this.loadToolsData();
  }

  public ngAfterViewInit(): void {
    if (this.searchInput) {
      this.searchInput.nativeElement.focus();
    }
  }

  public ngOnChanges(changes: SimpleChanges): void {
    if (changes['mergedTools']) {
      this._preselectMergedTools();
    }
  }
  public onCancel(): void {
    this.cancel.emit();
  }
  public ngOnDestroy(): void {
    console.log('ToolsPopupComponent destroyed.');
    this._destroyed$.next();
    this._destroyed$.complete();
  }

  public loadToolsData(): void {
    console.log('Loading tools data...');
    this.loading = true;
    forkJoin({
      fullTools: this._fullToolConfigService.getFullToolConfigs(),
      pythonTools: this._pythonCodeToolService.getPythonCodeTools(),
      mcpTools: this.mcpToolsService.getMcpTools(),
    })
      .pipe(takeUntil(this._destroyed$))
      .subscribe({
        next: ({ fullTools, pythonTools, mcpTools }) => {
          console.log('Full tools data received:', fullTools);
          console.log('Python tools data received:', pythonTools);
          console.log('MCP tools data received:', mcpTools);

          this.tools = this._sortToolsBySelection(fullTools);
          this.pythonTools = this._sortPythonToolsBySelection(pythonTools);
          this.mcpTools = this._sortMcpToolsBySelection(mcpTools);

          this._preselectMergedTools();
          this.loading = false;
          this._cdr.markForCheck();
        },
        error: (err) => {
          console.error('Error loading tools data:', err);
          this.loading = false;
          this._cdr.markForCheck();
        },
      });
  }

  public get filteredTools(): FullToolConfig[] {
    let toolsToFilter = this.tools;

    if (this.searchTerm) {
      const query = this.searchTerm.toLowerCase();
      toolsToFilter = toolsToFilter.filter(
        (tool) =>
          tool.name.toLowerCase().includes(query) ||
          tool.toolConfigs.some((config) =>
            config.name.toLowerCase().includes(query)
          )
      );
    }

    return this._sortToolsBySelection(toolsToFilter);
  }

  // Computed getter for filtering python/custom tools based on searchTerm
  public get filteredPythonTools(): GetPythonCodeToolRequest[] {
    let toolsToFilter = this.pythonTools;

    if (this.searchTerm) {
      const query = this.searchTerm.toLowerCase();
      toolsToFilter = toolsToFilter.filter((pTool) =>
        pTool.name.toLowerCase().includes(query)
      );
    }

    return this._sortPythonToolsBySelection(toolsToFilter);
  }

  // Computed getter for filtering MCP tools based on searchTerm
  public get filteredMcpTools(): GetMcpToolRequest[] {
    let toolsToFilter = this.mcpTools;

    if (this.searchTerm) {
      const query = this.searchTerm.toLowerCase();
      toolsToFilter = toolsToFilter.filter((mcpTool) =>
        mcpTool.name.toLowerCase().includes(query) ||
        mcpTool.tool_name.toLowerCase().includes(query)
      );
    }

    return this._sortMcpToolsBySelection(toolsToFilter);
  }

  // Helper method to sort tools with selected items at the top
  private _sortToolsBySelection(tools: FullToolConfig[]): FullToolConfig[] {
    return tools.sort((a, b) => {
      const aSelected = this.isToolSelected(a);
      const bSelected = this.isToolSelected(b);

      if (aSelected && !bSelected) return -1;
      if (!aSelected && bSelected) return 1;
      return 0;
    });
  }

  // Helper method to sort python tools with selected items at the top
  private _sortPythonToolsBySelection(
    tools: GetPythonCodeToolRequest[]
  ): GetPythonCodeToolRequest[] {
    return tools.sort((a, b) => {
      const aSelected = this.selectedPythonTools.has(a.id);
      const bSelected = this.selectedPythonTools.has(b.id);

      if (aSelected && !bSelected) return -1;
      if (!aSelected && bSelected) return 1;
      return 0;
    });
  }

  // Helper method to sort MCP tools with selected items at the top
  private _sortMcpToolsBySelection(
    tools: GetMcpToolRequest[]
  ): GetMcpToolRequest[] {
    return tools.sort((a, b) => {
      const aSelected = this.selectedMcpTools.has(a.id);
      const bSelected = this.selectedMcpTools.has(b.id);

      if (aSelected && !bSelected) return -1;
      if (!aSelected && bSelected) return 1;
      return 0;
    });
  }

  private _preselectMergedTools(): void {
    if (this.mergedTools && this.mergedTools.length) {
      const preselectedToolConfigIds = this.mergedTools
        .filter((item) => item.type === 'tool-config')
        .map((item) => item.id);
      this.selectedToolConfigs = new Set(preselectedToolConfigIds);
      const preselectedPythonToolIds = this.mergedTools
        .filter((item) => item.type === 'python-tool')
        .map((item) => item.id);
      this.selectedPythonTools = new Set(preselectedPythonToolIds);
      const preselectedMcpToolIds = this.mergedTools
        .filter((item) => item.type === 'mcp-tool')
        .map((item) => item.id);
      this.selectedMcpTools = new Set(preselectedMcpToolIds);

      // Re-sort tools after preselection
      this.tools = this._sortToolsBySelection(this.tools);
      this.pythonTools = this._sortPythonToolsBySelection(this.pythonTools);
      this.mcpTools = this._sortMcpToolsBySelection(this.mcpTools);
    }
  }

  public toggleToolType(type: 'builtin' | 'custom' | 'mcp'): void {
    this.selectedMenu = type;
    this.showPythonTools = type === 'custom';
    this._cdr.markForCheck();
  }

  public onSelectMenu(type: 'builtin' | 'custom' | 'mcp'): void {
    this.selectedMenu = type;
    this.showPythonTools = type === 'custom';
    this._cdr.markForCheck();
  }

  public save(): void {
    // Build tools map for getting actual tool names
    const toolsMap = new Map<number, string>();
    this.tools.forEach((tool) => {
      toolsMap.set(tool.id, tool.name);
    });

    const mergedToolConfigs = this.tools
      .flatMap((tool) => tool.toolConfigs)
      .filter((config) => this.selectedToolConfigs.has(config.id))
      .map((config) => ({
        id: config.id,
        configName: config.name, // This is the config name
        toolName: toolsMap.get(config.tool) || 'Unknown Tool', // This is the actual tool name
        type: 'tool-config',
      }));
    const mergedPythonTools = this.pythonTools
      .filter((pTool) => this.selectedPythonTools.has(pTool.id))
      .map((pTool) => ({
        id: pTool.id,
        configName: pTool.name, // For python tools, the name is both config and tool name
        toolName: pTool.name, // Python tools have the same name for both
        type: 'python-tool',
      }));

    const mergedMcpTools = this.mcpTools
      .filter((mcpTool) => this.selectedMcpTools.has(mcpTool.id))
      .map((mcpTool) => ({
        id: mcpTool.id,
        configName: mcpTool.name, // MCP tool configuration name
        toolName: mcpTool.tool_name, // MCP tool name
        type: 'mcp-tool',
      }));

    const updatedMergedTools = [...mergedToolConfigs, ...mergedPythonTools, ...mergedMcpTools];
    this.mergedToolsUpdated.emit(updatedMergedTools);
  }

  public onCheckboxToggle(tool: FullToolConfig): void {
    // For tools with empty tool_fields (simple tools that don't need configuration)
    if (tool.tool_fields.length === 0) {
      if (tool.toolConfigs.length > 0) {
        const firstConfig = tool.toolConfigs[0];
        const isToolSelected = this.isToolSelected(tool);

        if (isToolSelected) {
          this.selectedToolConfigs.delete(firstConfig.id);
        } else {
          this.selectedToolConfigs.add(firstConfig.id);
        }
      }
      this._cdr.markForCheck();
      return;
    }

    // For tools with tool_fields (complex tools that need configuration)
    // Select/deselect only the first config, not all configs
    if (tool.toolConfigs.length > 0) {
      const firstConfig = tool.toolConfigs[0];
      const isToolSelected = this.isToolSelected(tool);

      if (isToolSelected) {
        this.selectedToolConfigs.delete(firstConfig.id);
      } else {
        this.selectedToolConfigs.add(firstConfig.id);
      }
    }

    this._cdr.markForCheck();
  }

  public onPythonToolToggle(pTool: GetPythonCodeToolRequest): void {
    if (this.selectedPythonTools.has(pTool.id)) {
      this.selectedPythonTools.delete(pTool.id);
    } else {
      this.selectedPythonTools.add(pTool.id);
    }
    this._cdr.markForCheck();
  }

  public onMcpToolToggle(mcpTool: GetMcpToolRequest): void {
    if (this.selectedMcpTools.has(mcpTool.id)) {
      this.selectedMcpTools.delete(mcpTool.id);
    } else {
      this.selectedMcpTools.add(mcpTool.id);
    }
    this._cdr.markForCheck();
  }

  public isToolSelected(tool: FullToolConfig): boolean {
    return tool.toolConfigs.some((config) =>
      this.selectedToolConfigs.has(config.id)
    );
  }

  public toggleToolConfigs(tool: FullToolConfig): void {
    if (this.expandedToolConfigs.has(tool.id)) {
      this.expandedToolConfigs.delete(tool.id);
    } else {
      this.expandedToolConfigs.add(tool.id);
    }
    this._cdr.markForCheck();
  }

  public onConfigToggle(config: GetToolConfigRequest): void {
    if (this.selectedToolConfigs.has(config.id)) {
      this.selectedToolConfigs.delete(config.id);
    } else {
      this.selectedToolConfigs.add(config.id);
    }
    this._cdr.markForCheck();
  }

  public openCustomToolDialog(): void {
    // Load tools fresh for the dialog
    this.customToolsService.getPythonCodeTools().subscribe(tools => {
      const dialogRef = this.cdkDialog.open(CustomToolDialogComponent, {
        data: { pythonTools: tools },
      });
      dialogRef.closed.subscribe((result) => {
        if (result) {
          console.log('New tool created:', result);
        }
        this.cdr.markForCheck();
      });
    });
  }

  public openMcpToolDialog(): void {
    const dialogRef = this.cdkDialog.open(McpToolDialogComponent, {
      data: {},
    });
    
    dialogRef.closed.subscribe((result) => {
      if (result) {
        console.log('New MCP tool created:', result);
        // Reload the MCP tools list to include the newly created tool
        this.loadToolsData();
      }
    });
  }

  // This method is commented out as per the requirement
  /* public onCreateConfig(tool: FullToolConfig): void {
    if (!tool) return;
    
    this.toastService.showToast({
      title: "Create Config",
      message: `Creating a new configuration for tool: ${tool.name}`,
    });
    
    // Additional logic for creating a configuration would go here
  } */
}
