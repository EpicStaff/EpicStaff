import { animate, style, transition, trigger } from '@angular/animations';
import { Dialog } from '@angular/cdk/dialog';
import { NgFor, NgIf } from '@angular/common';
import {
    AfterViewInit,
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    ElementRef,
    EventEmitter,
    Input,
    OnChanges,
    OnDestroy,
    OnInit,
    Output,
    SimpleChanges,
    ViewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ButtonComponent } from '@shared/components';
import { forkJoin, Subject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';

import { McpToolDialogComponent } from '../../../../../features/tools/components/mcp-tool-dialog/mcp-tool-dialog.component';
import { GetMcpToolRequest } from '../../../../../features/tools/models/mcp-tool.model';
import { GetPythonCodeToolRequest } from '../../../../../features/tools/models/python-code-tool.model';
import { McpToolsService } from '../../../../../features/tools/services/mcp-tools/mcp-tools.service';
import { CreateCustomToolDialogComponent } from '../../../../../user-settings-page/tools/custom-tool-editor/create-custom-tool-dialog/create-custom-tool-dialog.component';
import { PythonCodeToolService } from '../../../../../user-settings-page/tools/custom-tool-editor/services/pythonCodeToolService.service';
import { McpToolItemComponent } from './mcp-tool-item/mcp-tool-item.component';
import { PythonToolItemComponent } from './python-tool-item/python-tool-item.component';

@Component({
    selector: 'app-tools-list',
    imports: [NgFor, NgIf, FormsModule, PythonToolItemComponent, McpToolItemComponent, ButtonComponent],
    templateUrl: './tools-popup.component.html',
    styleUrls: ['./tools-popup.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    animations: [
        trigger('expandCollapse', [
            transition(':enter', [
                style({ height: '0', opacity: 0 }),
                animate('300ms cubic-bezier(0.34, 1.56, 0.64, 1)', style({ height: '*', opacity: 1 })),
            ]),
            transition(':leave', [
                style({ height: '*', opacity: 1 }),
                animate('200ms ease-out', style({ height: '0', opacity: 0 })),
            ]),
        ]),
    ],
})
export class ToolsPopupComponent implements OnInit, OnChanges, OnDestroy, AfterViewInit {
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
    @Output() public childDialogOpenChange = new EventEmitter<boolean>();

    public selectedMenu: 'custom' | 'mcp' = 'custom';
    public searchTerm = '';
    public loading = true;

    public pythonTools: GetPythonCodeToolRequest[] = [];
    public mcpTools: GetMcpToolRequest[] = [];

    public selectedPythonTools = new Set<number>();
    public selectedMcpTools = new Set<number>();

    public showPythonTools = false;

    private readonly _destroyed$ = new Subject<void>();

    constructor(
        private readonly _pythonCodeToolService: PythonCodeToolService,
        private readonly _cdr: ChangeDetectorRef,
        private readonly cdkDialog: Dialog,
        private readonly mcpToolsService: McpToolsService
    ) {}

    public ngOnInit(): void {
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
        this._destroyed$.next();
        this._destroyed$.complete();
    }

    public loadToolsData(): void {
        this.loading = true;
        forkJoin({
            pythonTools: this._pythonCodeToolService.getPythonCodeTools(),
            mcpTools: this.mcpToolsService.getMcpTools(),
        })
            .pipe(takeUntil(this._destroyed$))
            .subscribe({
                next: ({ pythonTools, mcpTools }) => {
                    this.pythonTools = this._sortPythonToolsBySelection(pythonTools);
                    this.mcpTools = this._sortMcpToolsBySelection(mcpTools);

                    this._preselectMergedTools();
                    this.loading = false;
                    this._cdr.markForCheck();
                },
                error: () => {
                    this.loading = false;
                    this._cdr.markForCheck();
                },
            });
    }

    // Computed getter for filtering python/custom tools based on searchTerm
    public get filteredPythonTools(): GetPythonCodeToolRequest[] {
        let toolsToFilter = this.pythonTools;

        if (this.searchTerm) {
            const query = this.searchTerm.toLowerCase();
            toolsToFilter = toolsToFilter.filter((pTool) => pTool.name.toLowerCase().includes(query));
        }

        return this._sortPythonToolsBySelection(toolsToFilter);
    }

    // Computed getter for filtering MCP tools based on searchTerm
    public get filteredMcpTools(): GetMcpToolRequest[] {
        let toolsToFilter = this.mcpTools;

        if (this.searchTerm) {
            const query = this.searchTerm.toLowerCase();
            toolsToFilter = toolsToFilter.filter(
                (mcpTool) =>
                    mcpTool.name.toLowerCase().includes(query) || mcpTool.tool_name.toLowerCase().includes(query)
            );
        }

        return this._sortMcpToolsBySelection(toolsToFilter);
    }

    // Helper method to sort python tools with selected items at the top
    private _sortPythonToolsBySelection(tools: GetPythonCodeToolRequest[]): GetPythonCodeToolRequest[] {
        return tools.sort((a, b) => {
            const aSelected = this.selectedPythonTools.has(a.id);
            const bSelected = this.selectedPythonTools.has(b.id);

            if (aSelected && !bSelected) return -1;
            if (!aSelected && bSelected) return 1;
            return 0;
        });
    }

    // Helper method to sort MCP tools with selected items at the top
    private _sortMcpToolsBySelection(tools: GetMcpToolRequest[]): GetMcpToolRequest[] {
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
            const preselectedPythonToolIds = this.mergedTools
                .filter((item) => item.type === 'python-tool')
                .map((item) => item.id);
            this.selectedPythonTools = new Set(preselectedPythonToolIds);
            const preselectedMcpToolIds = this.mergedTools
                .filter((item) => item.type === 'mcp-tool')
                .map((item) => item.id);
            this.selectedMcpTools = new Set(preselectedMcpToolIds);

            // Re-sort tools after preselection
            this.pythonTools = this._sortPythonToolsBySelection(this.pythonTools);
            this.mcpTools = this._sortMcpToolsBySelection(this.mcpTools);
        }
    }

    public toggleToolType(type: 'custom' | 'mcp'): void {
        this.selectedMenu = type;
        this.showPythonTools = type === 'custom';
        this._cdr.markForCheck();
    }

    public save(): void {
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

        const updatedMergedTools = [...mergedPythonTools, ...mergedMcpTools];
        this.mergedToolsUpdated.emit(updatedMergedTools);
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

    public openCustomToolDialog(): void {
        this.childDialogOpenChange.emit(true);
        const dialogRef = this.cdkDialog.open<GetPythonCodeToolRequest>(CreateCustomToolDialogComponent);

        dialogRef.closed.pipe(takeUntil(this._destroyed$)).subscribe((result) => {
            if (result) {
                // Auto-select the newly created tool, preserving existing selections.
                this.selectedPythonTools.add(result.id);
                this.pythonTools = this._sortPythonToolsBySelection([result, ...this.pythonTools]);
                this._cdr.markForCheck();
            }
            this._notifyChildDialogClosed();
        });
    }

    public openMcpToolDialog(): void {
        this.childDialogOpenChange.emit(true);
        const dialogRef = this.cdkDialog.open<GetMcpToolRequest>(McpToolDialogComponent, {
            data: {},
        });

        dialogRef.closed.pipe(takeUntil(this._destroyed$)).subscribe((result) => {
            if (result) {
                this.selectedMcpTools.add(result.id);
                this.mcpTools = this._sortMcpToolsBySelection([result, ...this.mcpTools]);
                this._cdr.markForCheck();
            }
            this._notifyChildDialogClosed();
        });
    }

    private _notifyChildDialogClosed(): void {
        setTimeout(() => this.childDialogOpenChange.emit(false));
    }
}
