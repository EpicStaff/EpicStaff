import { Dialog, DialogModule } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ConfirmationDialogService, LoadingSpinnerComponent } from '@shared/components';

import { ToastService } from '../../../../../../services/notifications';
import { McpToolDialogComponent } from '../../../../components/mcp-tool-dialog/mcp-tool-dialog.component';
import { GetMcpToolRequest } from '../../../../models/mcp-tool.model';
import { McpToolsService } from '../../../../services/mcp-tools/mcp-tools.service';
import { ToolsEventsService } from '../../../../services/tools-events.service';
import { ToolsSearchService } from '../../../../services/tools-search.service';
import { ToolCardComponent } from '../tool-card/tool-card.component';
import { ToolCardMenuAction, ToolCardVM } from '../tool-card/tool-card.model';

@Component({
    selector: 'app-mcp-tools',
    standalone: true,
    changeDetection: ChangeDetectionStrategy.OnPush,
    templateUrl: './mcp-tools.component.html',
    styleUrls: ['./mcp-tools.component.scss'],
    imports: [LoadingSpinnerComponent, ToolCardComponent, DialogModule, CommonModule],
})
export class McpToolsComponent implements OnInit {
    private readonly mcpToolsService = inject(McpToolsService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly dialog = inject(Dialog);
    private readonly toastService = inject(ToastService);
    private readonly confirmationDialogService = inject(ConfirmationDialogService);
    private readonly toolsEventsService = inject(ToolsEventsService);
    private readonly toolsSearchService = inject(ToolsSearchService);

    public searchTerm = signal<string>('');

    // Local state management
    private readonly allTools = signal<GetMcpToolRequest[]>([]);

    public readonly error = signal<string | null>(null);
    public readonly isLoaded = signal<boolean>(false);

    //TODO refactor into one computed
    public readonly tools = computed(() => {
        const tools = this.allTools()
            .slice()
            .sort((a, b) => b.id - a.id);
        const term = this.searchTerm();

        if (!term || term.trim() === '') {
            return tools;
        }

        const searchLower = term.toLowerCase();
        return tools.filter(
            (tool) =>
                tool.name.toLowerCase().includes(searchLower) ||
                tool.tool_name.toLowerCase().includes(searchLower) ||
                tool.transport.toLowerCase().includes(searchLower)
        );
    });

    public readonly cards = computed<ToolCardVM[]>(() =>
        this.tools().map((t) => ({
            id: t.id,
            kind: 'mcp' as const,
            name: t.name,
            // MCP DTO has no description; surface tool_name + transport as a compact summary.
            description: `${t.tool_name} · ${t.transport}${t.timeout ? ` · ${t.timeout}s` : ''}`,
            labelIds: [],
            favorite: false,
            builtIn: false,
        }))
    );

    private findToolById(id: number): GetMcpToolRequest | undefined {
        return this.allTools().find((t) => t.id === id);
    }

    public onCardConfigure(vm: ToolCardVM): void {
        const tool = this.findToolById(vm.id);
        if (tool) this.onConfigure(tool);
    }

    public onCardDelete(vm: ToolCardVM): void {
        const tool = this.findToolById(vm.id);
        if (tool) this.onDelete(tool);
    }

    public onCardMenuAction(payload: { tool: ToolCardVM; action: ToolCardMenuAction }): void {
        if (payload.action === 'delete') {
            this.onCardDelete(payload.tool);
            return;
        }
        // TODO: wire duplicate / add_label / show_used_places once endpoints are defined.
    }

    public ngOnInit(): void {
        this.loadTools();

        // Listen for new tool creation events
        this.toolsEventsService.mcpToolCreated$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((newTool) => {
            this.addNewTool(newTool);
        });

        // Listen for search term changes
        this.toolsSearchService.searchTerm$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((term) => {
            this.searchTerm.set(term);
        });
    }

    private loadTools(): void {
        this.mcpToolsService
            .getMcpTools()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (tools) => {
                    this.allTools.set(tools);
                    this.isLoaded.set(true);
                },
                error: (err: HttpErrorResponse) => {
                    this.error.set('Failed to load MCP tools. Please try again later.');
                    this.isLoaded.set(true);
                    console.error('❌ Error loading MCP tools:', err);
                },
            });
    }

    public onConfigure(tool: GetMcpToolRequest): void {
        const dialogRef = this.dialog.open<GetMcpToolRequest>(McpToolDialogComponent, {
            data: {
                selectedTool: tool,
            },
            maxWidth: '95vw',
            maxHeight: '90vh',
            autoFocus: true,
        });

        dialogRef.closed.subscribe((result) => {
            if (result) {
                // Update local state with the updated tool
                const currentTools = this.allTools();
                const index = currentTools.findIndex((t) => t.id === result.id);
                if (index !== -1) {
                    const updatedTools = [...currentTools];
                    updatedTools[index] = result;
                    this.allTools.set(updatedTools);
                }
            }
        });
    }

    public onDelete(tool: GetMcpToolRequest): void {
        this.confirmationDialogService
            .confirmDelete(tool.name)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((result) => {
                // Only proceed if result is exactly true (user clicked confirm)
                if (result === true) {
                    this.mcpToolsService
                        .deleteMcpTool(tool.id)
                        .pipe(takeUntilDestroyed(this.destroyRef))
                        .subscribe({
                            next: () => {
                                // Remove from local state
                                const currentTools = this.allTools();
                                this.allTools.set(currentTools.filter((t) => t.id !== tool.id));

                                this.toastService.success(`MCP tool "${tool.name}" has been deleted successfully.`);
                            },
                            error: (err: HttpErrorResponse) => {
                                this.toastService.error(`Failed to delete MCP tool "${tool.name}". Please try again.`);
                                console.error('❌ Error deleting MCP tool:', err);
                            },
                        });
                }
                // If result is false or 'close', the action is cancelled (do nothing)
            });
    }

    public refreshTools(): void {
        this.isLoaded.set(false);
        this.error.set(null);
        this.loadTools();
    }

    public addNewTool(tool: GetMcpToolRequest): void {
        const currentTools = this.allTools();
        this.allTools.set([tool, ...currentTools]);
    }
}
