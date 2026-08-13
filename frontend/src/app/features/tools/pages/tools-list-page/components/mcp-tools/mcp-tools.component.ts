import { Dialog, DialogModule } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    effect,
    inject,
    OnInit,
    signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
    AppIncludeExcludeDialogComponent,
    AppIncludeExcludeDialogData,
    AppIncludeExcludeDialogResult,
    ConfirmationDialogService,
    IncludeExcludeTab,
    LoadingSpinnerComponent,
} from '@shared/components';
import { LABELS_STORE } from '@shared/services';
import { map } from 'rxjs/operators';

import { ToastService } from '../../../../../../services/notifications';
import { downloadBlob } from '../../../../../../shared/utils/download-blob.util';
import { McpToolDialogComponent } from '../../../../components/mcp-tool-dialog/mcp-tool-dialog.component';
import { ToolUsageDialogComponent } from '../../../../components/tool-usage-dialog/tool-usage-dialog.component';
import { GetMcpToolRequest } from '../../../../models/mcp-tool.model';
import { GetBulkToolUsageItem } from '../../../../models/tool-config.model';
import { McpToolsService } from '../../../../services/mcp-tools/mcp-tools.service';
import { ToolsEventsService } from '../../../../services/tools-events.service';
import { ToolsLabelsStorageService } from '../../../../services/tools-labels-storage.service';
import { ToolsSearchService } from '../../../../services/tools-search.service';
import { ToolsBulkActionEvent, ToolsViewStateService } from '../../../../services/tools-view-state.service';
import { runBulkDeleteWithConfirm, runDeleteUnused, runSettledBulk } from '../../../../utils/bulk-tool-op.util';
import {
    compareTools,
    matchesToolFilter,
    ToolFilterAdapter,
    toUsageVmFields,
} from '../../../../utils/tools-cards.util';
import { ToolCardComponent } from '../tool-card/tool-card.component';
import { ToolCardMenuAction, ToolCardVM } from '../tool-card/tool-card.model';

const MCP_TOOL_ADAPTER: ToolFilterAdapter<GetMcpToolRequest> = {
    idOf: (t) => t.id,
    nameOf: (t) => t.name,
    labelIdsOf: (t) => t.labels ?? [],
    favoriteOf: (t) => t.is_favorite,
    searchableTextOf: (t) => [t.name, t.tool_name, t.transport],
};

@Component({
    selector: 'app-mcp-tools',
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
    private readonly labelsStorage = inject(ToolsLabelsStorageService);
    public readonly viewState = inject(ToolsViewStateService);

    public searchTerm = signal<string>('');

    // Local state management
    private readonly allTools = signal<GetMcpToolRequest[]>([]);
    private readonly usageById = signal<Map<number, GetBulkToolUsageItem>>(new Map());

    public readonly error = signal<string | null>(null);
    public readonly isLoaded = signal<boolean>(false);

    constructor() {
        effect(() => {
            const needsUsage = this.viewState.needsUsageData();
            const ids = this.allTools().map((t) => t.id);
            if (!needsUsage || ids.length === 0) return;
            this.mcpToolsService
                .getBulkUsageDetailById(ids)
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe({
                    next: (items) => this.usageById.set(new Map(items.map((i) => [i.id, i]))),
                    error: (err: HttpErrorResponse) => {
                        this.toastService.error(err.error?.message || 'Failed to load usage for MCP tools.');
                    },
                });
        });
    }

    public readonly cards = computed<ToolCardVM[]>(() => {
        const usage = this.usageById();
        const showUsage = this.viewState.showUsageAndUnused();
        const ctx = {
            filter: this.viewState.filter(),
            sidebarLabelFilter: this.labelsStorage.activeLabelFilter(),
            labelNameById: new Map(this.labelsStorage.labels().map((l) => [l.id, l.name] as const)),
            searchTerm: this.searchTerm().trim().toLowerCase(),
            usage,
        };

        return this.allTools()
            .filter((t) => matchesToolFilter(t, ctx, MCP_TOOL_ADAPTER))
            .slice()
            .sort((a, b) => compareTools(a, b, ctx.filter.sortOrder, usage, MCP_TOOL_ADAPTER))
            .map((t) => ({
                id: t.id,
                kind: 'mcp' as const,
                name: t.name,
                description: `${t.tool_name} · ${t.transport}${t.timeout ? ` · ${t.timeout}s` : ''}`,
                labelIds: t.labels ?? [],
                favorite: t.is_favorite,
                builtIn: false,
                ...toUsageVmFields(usage, t.id, showUsage),
            }));
    });

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
        switch (payload.action) {
            case 'delete':
                this.onCardDelete(payload.tool);
                return;
            case 'duplicate':
                this.mcpToolsService
                    .copyMcpTool(payload.tool.id, { name: payload.tool.name })
                    .pipe(takeUntilDestroyed(this.destroyRef))
                    .subscribe({
                        next: (copy) => this.addNewTool(copy),
                        error: (err) => {
                            this.toastService.error(
                                err.error?.message || `Failed to duplicate "${payload.tool.name}".`
                            );
                        },
                    });
                return;
            case 'export':
                this.mcpToolsService
                    .exportMcpTool(payload.tool.id)
                    .pipe(takeUntilDestroyed(this.destroyRef))
                    .subscribe({
                        next: (blob) => downloadBlob(blob, `${payload.tool.name}.json`),
                        error: (err: HttpErrorResponse) => {
                            this.toastService.error(err.error?.message || `Failed to export "${payload.tool.name}".`);
                        },
                    });
                return;
            case 'show_used_places':
                this.mcpToolsService
                    .getUsageDetailById(payload.tool.id)
                    .pipe(takeUntilDestroyed(this.destroyRef))
                    .subscribe({
                        next: (usage) => {
                            this.dialog.open<void>(ToolUsageDialogComponent, {
                                data: { toolName: payload.tool.name, usage },
                                width: 'calc(100vw - 2rem)',
                                height: 'calc(100vh - 2rem)',
                                hasBackdrop: true,
                            });
                        },
                        error: (err: HttpErrorResponse) => {
                            this.toastService.error(
                                err.error?.message || `Failed to load usage for "${payload.tool.name}".`
                            );
                        },
                    });
                return;
        }
    }

    public onCardSelectedChange(payload: { tool: ToolCardVM; selected: boolean }): void {
        this.viewState.setSelected(payload.tool.id, payload.selected);
    }

    public onCardLabelsChange(payload: { tool: ToolCardVM; labelIds: number[] }): void {
        this.mcpToolsService
            .patchMcpTool(payload.tool.id, { labels: payload.labelIds })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (updated) => this.replaceToolInState(updated),
                error: (err) => {
                    this.toastService.error(
                        err.error?.message || `Failed to update labels for "${payload.tool.name}".`
                    );
                },
            });
    }

    public onCardFavoriteChange(payload: { tool: ToolCardVM; favorite: boolean }): void {
        const req$ = payload.favorite
            ? this.mcpToolsService.addToFavoritesMcpTool(payload.tool.id)
            : this.mcpToolsService.deleteFromFavoritesMcpTool(payload.tool.id);
        req$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
            next: () => this.setFavoriteInState([payload.tool.id], payload.favorite),
            error: (err: HttpErrorResponse) => {
                this.toastService.error(err.error?.message || `Failed to update favorite for "${payload.tool.name}".`);
            },
        });
    }

    public ngOnInit(): void {
        this.loadTools();

        this.toolsEventsService.mcpToolCreated$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((newTool) => {
            this.addNewTool(newTool);
        });

        this.toolsSearchService.searchTerm$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((term) => {
            this.searchTerm.set(term);
        });

        this.viewState.action$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((event) => {
            this.handleBulkAction(event);
        });
    }

    private handleBulkAction(event: ToolsBulkActionEvent): void {
        switch (event.kind) {
            case 'select-all':
                this.viewState.selectMany(this.cards().map((c) => c.id));
                return;
            case 'delete-unused':
                runDeleteUnused(
                    this.cards().map((c) => c.id),
                    {
                        destroyRef: this.destroyRef,
                        toast: this.toastService,
                        confirmation: this.confirmationDialogService,
                        viewState: this.viewState,
                        allTools: this.allTools,
                        getBulkUsage: (ids) => this.mcpToolsService.getBulkUsageDetailById(ids),
                        bulkDelete: (ids) => this.mcpToolsService.bulkDeleteMcpTool(ids),
                        entityLabel: 'MCP tool',
                    }
                );
                return;
            case 'favorite':
                this.handleBulkFavorite();
                return;
            case 'duplicate':
                this.handleBulkDuplicate();
                return;
            case 'delete-selected':
                runBulkDeleteWithConfirm(Array.from(this.viewState.selectedIds()), {
                    destroyRef: this.destroyRef,
                    toast: this.toastService,
                    confirmation: this.confirmationDialogService,
                    viewState: this.viewState,
                    allTools: this.allTools,
                    bulkDelete: (ids) => this.mcpToolsService.bulkDeleteMcpTool(ids),
                    entityLabel: 'MCP tool',
                    scopeLabel: 'selected',
                });
                return;
            case 'add-labels':
                this.handleBulkAddLabels(event.labelIds ?? []);
                return;
            case 'open-include-exclude':
                this.openIncludeExcludeDialog(event.initialTab ?? 'primary');
                return;
            case 'export-selected':
                this.handleBulkExport(Array.from(this.viewState.selectedIds()));
                return;
            case 'open-import':
                this.handleImport();
                return;
        }
    }

    private handleImport(): void {
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = '.json,application/json';
        input.onchange = (event: Event) => {
            const file = (event.target as HTMLInputElement).files?.[0];
            if (!file) return;
            this.mcpToolsService
                .importMcpTool(file)
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe({
                    next: () => {
                        this.toastService.success('MCP tools imported successfully.');
                        this.loadTools();
                    },
                    error: (err: HttpErrorResponse) => {
                        this.toastService.error(err.error?.message || 'Failed to import MCP tools.');
                    },
                });
        };
        input.click();
    }

    public handleBulkExport(ids: number[]): void {
        if (ids.length === 0) {
            this.toastService.info('Select at least one tool to export.');
            return;
        }
        this.mcpToolsService
            .bulkExportMcpTool(ids)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (blob) => downloadBlob(blob, `mcp-tools-export-${Date.now()}.json`),
                error: (err: HttpErrorResponse) => {
                    this.toastService.error(err.error?.message || 'Failed to export selected MCP tools.');
                },
            });
    }

    private openIncludeExcludeDialog(initialTab: IncludeExcludeTab): void {
        this.labelsStorage.loadLabels().subscribe(() => {
            const current = this.viewState.filter();
            const data: AppIncludeExcludeDialogData = {
                initialTab,
                primaryTab: {
                    label: 'Tools',
                    icon: 'tools',
                    searchPlaceholder: 'Search tool...',
                    emptyText: 'No tools match the search.',
                },
                items: this.allTools().map((t) => ({ id: t.id, name: t.name })),
                selectedItemIds: current.includedToolIds,
                selectedLabelIds: current.includedLabelIds,
            };
            const ref = this.dialog.open<AppIncludeExcludeDialogResult | undefined>(AppIncludeExcludeDialogComponent, {
                data,
                panelClass: 'tools-filter-dialog-panel',
                hasBackdrop: true,
                providers: [{ provide: LABELS_STORE, useExisting: ToolsLabelsStorageService }],
            });
            ref.closed.subscribe((result) => {
                if (!result) return;
                this.viewState.patchFilter({
                    includedToolIds: result.includedItemIds,
                    includedLabelIds: result.includedLabelIds,
                });
            });
        });
    }

    private handleBulkDuplicate(): void {
        const ids = Array.from(this.viewState.selectedIds());
        const requests = ids.map((id) => {
            const source = this.findToolById(id);
            return this.mcpToolsService.copyMcpTool(id, { name: source?.name ?? '' });
        });
        runSettledBulk(requests, {
            destroyRef: this.destroyRef,
            toast: this.toastService,
            viewState: this.viewState,
            applySuccess: (copies) => this.allTools.update((list) => [...copies, ...list]),
            successMessage: (n) => `Duplicated ${n} MCP tool(s).`,
            failureMessage: (n) => `Failed to duplicate ${n} MCP tool(s).`,
        });
    }

    private handleBulkFavorite(): void {
        const ids = Array.from(this.viewState.selectedIds());
        const requests = ids.map((id) => this.mcpToolsService.addToFavoritesMcpTool(id).pipe(map(() => id)));
        runSettledBulk(requests, {
            destroyRef: this.destroyRef,
            toast: this.toastService,
            viewState: this.viewState,
            applySuccess: (succeededIds) => this.setFavoriteInState(succeededIds, true),
            successMessage: (n) => `Marked ${n} MCP tool(s) as favorite.`,
            failureMessage: (n) => `Failed to update ${n} MCP tool(s).`,
        });
    }

    private handleBulkAddLabels(labelIdsToAdd: number[]): void {
        const selectedIds = Array.from(this.viewState.selectedIds());
        if (selectedIds.length === 0 || labelIdsToAdd.length === 0) return;
        const requests = selectedIds.map((id) => {
            const tool = this.findToolById(id);
            const union = new Set<number>(tool?.labels ?? []);
            for (const l of labelIdsToAdd) union.add(l);
            return this.mcpToolsService.patchMcpTool(id, { labels: Array.from(union) });
        });
        runSettledBulk(requests, {
            destroyRef: this.destroyRef,
            toast: this.toastService,
            viewState: this.viewState,
            applySuccess: (updated) => this.replaceManyInState(updated),
            successMessage: (n) => `Updated labels for ${n} MCP tool(s).`,
            failureMessage: (n) => `Failed to update labels for ${n} MCP tool(s).`,
        });
    }

    private replaceToolInState(updated: GetMcpToolRequest): void {
        this.allTools.update((list) => list.map((t) => (t.id === updated.id ? updated : t)));
    }

    private replaceManyInState(updated: GetMcpToolRequest[]): void {
        const byId = new Map(updated.map((t) => [t.id, t]));
        this.allTools.update((list) => list.map((t) => byId.get(t.id) ?? t));
    }

    private setFavoriteInState(ids: number[], value: boolean): void {
        const idSet = new Set(ids);
        this.allTools.update((list) => list.map((t) => (idSet.has(t.id) ? { ...t, is_favorite: value } : t)));
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
                    this.error.set(err.error?.message || 'Failed to load MCP tools. Please try again later.');
                    this.isLoaded.set(true);
                },
            });
    }

    public onConfigure(tool: GetMcpToolRequest): void {
        const dialogRef = this.dialog.open<GetMcpToolRequest>(McpToolDialogComponent, {
            data: { selectedTool: tool },
            maxWidth: '95vw',
            maxHeight: '90vh',
            autoFocus: true,
        });

        dialogRef.closed.subscribe((result) => {
            if (result) this.replaceToolInState(result);
        });
    }

    public onDelete(tool: GetMcpToolRequest): void {
        this.confirmationDialogService
            .confirmDelete(tool.name)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((result) => {
                if (result !== true) return;
                this.mcpToolsService
                    .deleteMcpTool(tool.id)
                    .pipe(takeUntilDestroyed(this.destroyRef))
                    .subscribe({
                        next: () => {
                            this.allTools.update((list) => list.filter((t) => t.id !== tool.id));
                            this.toastService.success(`MCP tool "${tool.name}" has been deleted successfully.`);
                        },
                        error: (err: HttpErrorResponse) => {
                            this.toastService.error(
                                err.error?.message || `Failed to delete MCP tool "${tool.name}". Please try again.`
                            );
                        },
                    });
            });
    }

    public refreshTools(): void {
        this.isLoaded.set(false);
        this.error.set(null);
        this.loadTools();
    }

    public addNewTool(tool: GetMcpToolRequest): void {
        this.allTools.update((current) => [tool, ...current]);
    }
}
