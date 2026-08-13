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
import { map, tap } from 'rxjs/operators';

import { ToastService } from '../../../../../../services/notifications';
import { downloadBlob } from '../../../../../../shared/utils/download-blob.util';
import { CreateCustomToolDialogComponent } from '../../../../../../user-settings-page/tools/custom-tool-editor/create-custom-tool-dialog/create-custom-tool-dialog.component';
import { ToolUsageDialogComponent } from '../../../../components/tool-usage-dialog/tool-usage-dialog.component';
import { GetPythonCodeToolRequest } from '../../../../models/python-code-tool.model';
import { GetBulkToolUsageItem } from '../../../../models/tool-config.model';
import { CustomToolsService } from '../../../../services/custom-tools/custom-tools.service';
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

const CUSTOM_TOOL_ADAPTER: ToolFilterAdapter<GetPythonCodeToolRequest> = {
    idOf: (t) => t.id,
    nameOf: (t) => t.name,
    labelIdsOf: (t) => t.labels ?? [],
    favoriteOf: (t) => t.is_favorite,
    searchableTextOf: (t) => [t.name, t.description],
};

@Component({
    selector: 'app-custom-tools',
    changeDetection: ChangeDetectionStrategy.OnPush,
    templateUrl: './custom-tools.component.html',
    styleUrls: ['./custom-tools.component.scss'],
    imports: [LoadingSpinnerComponent, ToolCardComponent, DialogModule, CommonModule],
})
export class CustomToolsComponent implements OnInit {
    private readonly customToolsService = inject(CustomToolsService);
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
    private readonly allTools = signal<GetPythonCodeToolRequest[]>([]);
    private readonly usageById = signal<Map<number, GetBulkToolUsageItem>>(new Map());

    public readonly error = signal<string | null>(null);
    public readonly isLoaded = signal<boolean>(false);

    constructor() {
        effect(() => {
            const needsUsage = this.viewState.needsUsageData();
            const ids = this.allTools().map((t) => t.id);
            if (!needsUsage || ids.length === 0) return;
            this.customToolsService
                .getBulkUsageDetailById(ids)
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe({
                    next: (items) => this.usageById.set(new Map(items.map((i) => [i.id, i]))),
                    error: (err: HttpErrorResponse) => {
                        this.toastService.error(err.error?.message || 'Failed to load usage for custom tools.');
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
            .filter((t) => matchesToolFilter(t, ctx, CUSTOM_TOOL_ADAPTER))
            .slice()
            .sort((a, b) => compareTools(a, b, ctx.filter.sortOrder, usage, CUSTOM_TOOL_ADAPTER))
            .map((t) => ({
                id: t.id,
                kind: 'custom' as const,
                name: t.name,
                description: t.description,
                labelIds: t.labels ?? [],
                favorite: t.is_favorite,
                builtIn: t.built_in,
                ...toUsageVmFields(usage, t.id, showUsage),
            }));
    });

    private findToolById(id: number): GetPythonCodeToolRequest | undefined {
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
                this.customToolsService
                    .copyPythonCodeTool(payload.tool.id, { name: payload.tool.name })
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
                this.customToolsService
                    .exportPythonCodeTool(payload.tool.id)
                    .pipe(takeUntilDestroyed(this.destroyRef))
                    .subscribe({
                        next: (blob) => downloadBlob(blob, `${payload.tool.name}.json`),
                        error: (err: HttpErrorResponse) => {
                            this.toastService.error(err.error?.message || `Failed to export "${payload.tool.name}".`);
                        },
                    });
                return;
            case 'show_used_places':
                this.customToolsService
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

    public onCardFavoriteChange(payload: { tool: ToolCardVM; favorite: boolean }): void {
        const req$ = payload.favorite
            ? this.customToolsService.addToFavoritesPythonCodeTool(payload.tool.id)
            : this.customToolsService.deleteFromFavoritesPythonCodeTool(payload.tool.id);
        req$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
            next: () => this.setFavoriteInState([payload.tool.id], payload.favorite),
            error: (err: HttpErrorResponse) => {
                this.toastService.error(err.error?.message || `Failed to update favorite for "${payload.tool.name}".`);
            },
        });
    }

    public onCardLabelsChange(payload: { tool: ToolCardVM; labelIds: number[] }): void {
        this.customToolsService
            .patchPythonCodeTool(payload.tool.id, { labels: payload.labelIds })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (updated) => this.replaceToolInState(updated),
                error: (err: HttpErrorResponse) => {
                    this.toastService.error(
                        err.error?.message || `Failed to update labels for "${payload.tool.name}".`
                    );
                },
            });
    }

    public ngOnInit(): void {
        this.loadTools();

        this.toolsEventsService.customToolCreated$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((newTool) => {
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
                        getBulkUsage: (ids) => this.customToolsService.getBulkUsageDetailById(ids),
                        bulkDelete: (ids) => this.customToolsService.bulkDeletePythonCodeTool(ids),
                        entityLabel: 'custom tool',
                    }
                );
                return;
            case 'favorite':
                this.handleBulkFavorite();
                return;
            case 'duplicate':
                this.handleBulkDuplicate();
                return;
            case 'delete-selected': {
                const selected = Array.from(this.viewState.selectedIds());

                const deletable = selected.filter((id) => !this.findToolById(id)?.built_in);
                const skipped = selected.length - deletable.length;
                if (skipped > 0) {
                    this.toastService.info(`${skipped} built-in tool(s) cannot be deleted and will be skipped.`);
                }
                runBulkDeleteWithConfirm(deletable, {
                    destroyRef: this.destroyRef,
                    toast: this.toastService,
                    confirmation: this.confirmationDialogService,
                    viewState: this.viewState,
                    allTools: this.allTools,
                    bulkDelete: (ids) => this.customToolsService.bulkDeletePythonCodeTool(ids),
                    entityLabel: 'custom tool',
                    scopeLabel: 'selected',
                });
                return;
            }
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
            this.customToolsService
                .importPythonCodeTool(file)
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe({
                    next: () => {
                        this.toastService.success('Custom tools imported successfully.');
                        this.loadTools();
                    },
                    error: (err: HttpErrorResponse) => {
                        this.toastService.error(err.error?.message || 'Failed to import custom tools.');
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
        this.customToolsService
            .bulkExportPythonCodeTool(ids)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (blob) => downloadBlob(blob, `python-code-tools-export-${Date.now()}.json`),
                error: (err: HttpErrorResponse) => {
                    this.toastService.error(err.error?.message || 'Failed to export selected tools.');
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

    private handleBulkFavorite(): void {
        const ids = Array.from(this.viewState.selectedIds());
        const requests = ids.map((id) => this.customToolsService.addToFavoritesPythonCodeTool(id).pipe(map(() => id)));
        runSettledBulk(requests, {
            destroyRef: this.destroyRef,
            toast: this.toastService,
            viewState: this.viewState,
            applySuccess: (succeededIds) => this.setFavoriteInState(succeededIds, true),
            successMessage: (n) => `Marked ${n} tool(s) as favorite.`,
            failureMessage: (n) => `Failed to update ${n} tool(s).`,
        });
    }

    private handleBulkDuplicate(): void {
        const ids = Array.from(this.viewState.selectedIds());
        const requests = ids.map((id) => {
            const source = this.findToolById(id);
            return this.customToolsService.copyPythonCodeTool(id, { name: source?.name ?? '' });
        });
        runSettledBulk(requests, {
            destroyRef: this.destroyRef,
            toast: this.toastService,
            viewState: this.viewState,
            applySuccess: (copies) => this.allTools.update((list) => [...copies, ...list]),
            successMessage: (n) => `Duplicated ${n} tool(s).`,
            failureMessage: (n) => `Failed to duplicate ${n} tool(s).`,
        });
    }

    private handleBulkAddLabels(labelIdsToAdd: number[]): void {
        const selectedIds = Array.from(this.viewState.selectedIds());
        if (selectedIds.length === 0 || labelIdsToAdd.length === 0) return;
        const requests = selectedIds.map((id) => {
            const tool = this.findToolById(id);
            const union = new Set<number>(tool?.labels ?? []);
            for (const l of labelIdsToAdd) union.add(l);
            return this.customToolsService.patchPythonCodeTool(id, { labels: Array.from(union) });
        });
        runSettledBulk(requests, {
            destroyRef: this.destroyRef,
            toast: this.toastService,
            viewState: this.viewState,
            applySuccess: (updated) => this.replaceManyInState(updated),
            successMessage: (n) => `Updated labels for ${n} tool(s).`,
            failureMessage: (n) => `Failed to update labels for ${n} tool(s).`,
        });
    }

    private replaceToolInState(updated: GetPythonCodeToolRequest): void {
        this.allTools.update((list) => list.map((t) => (t.id === updated.id ? updated : t)));
    }

    private replaceManyInState(updated: GetPythonCodeToolRequest[]): void {
        const byId = new Map(updated.map((t) => [t.id, t]));
        this.allTools.update((list) => list.map((t) => byId.get(t.id) ?? t));
    }

    private setFavoriteInState(ids: number[], value: boolean): void {
        const idSet = new Set(ids);
        this.allTools.update((list) => list.map((t) => (idSet.has(t.id) ? { ...t, is_favorite: value } : t)));
    }

    private loadTools(): void {
        this.customToolsService
            .getPythonCodeTools()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (tools) => {
                    this.allTools.set(tools);
                    this.isLoaded.set(true);
                },
                error: (err: HttpErrorResponse) => {
                    this.error.set(err.error?.message || 'Failed to load custom tools. Please try again later.');
                    this.isLoaded.set(true);
                },
            });
    }

    public onConfigure(tool: GetPythonCodeToolRequest): void {
        const dialogRef = this.dialog.open<GetPythonCodeToolRequest>(CreateCustomToolDialogComponent, {
            data: {
                pythonTools: this.allTools(),
                selectedTool: tool,
            },
        });

        dialogRef.closed
            .pipe(
                tap((result) => {
                    if (!result) return;
                    const currentTools = this.allTools();
                    const index = currentTools.findIndex((t) => t.id === result.id);
                    if (index !== -1) {
                        const updatedTools = [...currentTools];
                        updatedTools[index] = result;
                        this.allTools.set(updatedTools);
                    } else {
                        this.addNewTool(result);
                    }
                }),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe();
    }

    public onDelete(tool: GetPythonCodeToolRequest): void {
        this.confirmationDialogService
            .confirmDelete(tool.name)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((result) => {
                if (result === true) {
                    this.customToolsService
                        .deletePythonCodeTool(tool.id)
                        .pipe(takeUntilDestroyed(this.destroyRef))
                        .subscribe({
                            next: () => {
                                const currentTools = this.allTools();
                                this.allTools.set(currentTools.filter((t) => t.id !== tool.id));
                                this.toastService.success(`Tool "${tool.name}" has been deleted successfully.`);
                            },
                            error: (err: HttpErrorResponse) => {
                                this.toastService.error(
                                    err.error?.message || `Failed to delete tool "${tool.name}". Please try again.`
                                );
                            },
                        });
                }
            });
    }

    public addNewTool(tool: GetPythonCodeToolRequest): void {
        this.allTools.update((current) => [tool, ...current]);
    }
}
