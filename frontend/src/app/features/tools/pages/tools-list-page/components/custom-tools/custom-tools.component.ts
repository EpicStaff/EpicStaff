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
import { ConfirmationDialogService, LoadingSpinnerComponent } from '@shared/components';
import { tap } from 'rxjs/operators';

import { ToastService } from '../../../../../../services/notifications';
import { CreateCustomToolDialogComponent } from '../../../../../../user-settings-page/tools/custom-tool-editor/create-custom-tool-dialog/create-custom-tool-dialog.component';
import {
    IncludeExcludeTab,
    ToolsIncludeExcludeDialogComponent,
    ToolsIncludeExcludeDialogData,
    ToolsIncludeExcludeDialogResult,
} from '../../../../components/filter/tools-include-exclude-dialog/tools-include-exclude-dialog.component';
import { GetPythonCodeToolRequest } from '../../../../models/python-code-tool.model';
import { GetBulkToolUsageItem } from '../../../../models/tool-config.model';
import { evaluateCustomCondition } from '../../../../models/tool-filter.model';
import { CustomToolsService } from '../../../../services/custom-tools/custom-tools.service';
import { ToolsEventsService } from '../../../../services/tools-events.service';
import { ToolsLabelsStorageService } from '../../../../services/tools-labels-storage.service';
import { ToolsSearchService } from '../../../../services/tools-search.service';
import { ToolsBulkActionEvent, ToolsViewStateService } from '../../../../services/tools-view-state.service';
import { partitionSettled, settleAll } from '../../../../utils/settle-all';
import { ToolCardComponent } from '../tool-card/tool-card.component';
import { ToolCardMenuAction, ToolCardVM } from '../tool-card/tool-card.model';

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
        const term = this.searchTerm().trim().toLowerCase();
        const showUsage = this.viewState.showUsageAndUnused();
        const usage = this.usageById();
        const labelFilter = this.labelsStorage.activeLabelFilter();
        const labels = this.labelsStorage.labels();
        const filter = this.viewState.filter();

        const labelNameById = new Map(labels.map((l) => [l.id, l.name] as const));

        const passesAll = (t: GetPythonCodeToolRequest): boolean => {
            // Sidebar single-label filter.
            if (labelFilter === 'unlabeled' && (t.labels ?? []).length > 0) return false;
            if (typeof labelFilter === 'number' && !(t.labels ?? []).includes(labelFilter)) return false;
            // Favorite-only.
            if (filter.showFavoriteOnly && !t.favorite) return false;
            // Include/Exclude sets.
            if (filter.includedToolIds && !filter.includedToolIds.includes(t.id)) return false;
            if (filter.includedLabelIds) {
                const has = (t.labels ?? []).some((id) => filter.includedLabelIds!.includes(id));
                if (!has) return false;
            }
            // Custom filter.
            if (filter.customFilter) {
                if (filter.customFilter.scope === 'tool_name') {
                    if (!evaluateCustomCondition(t.name, filter.customFilter)) return false;
                } else {
                    const toolLabelNames = (t.labels ?? []).map((id) => labelNameById.get(id) ?? '');
                    const anyMatch = toolLabelNames.some((n) => evaluateCustomCondition(n, filter.customFilter));
                    if (!anyMatch) return false;
                }
            }
            // Free-text search.
            if (term && !t.name.toLowerCase().includes(term) && !t.description.toLowerCase().includes(term)) {
                return false;
            }
            return true;
        };

        const filtered = this.allTools().filter(passesAll);

        const usageOf = (id: number) => usage.get(id);
        const usageSum = (id: number) => {
            const u = usageOf(id);
            return u ? u.projects_count + u.staff_count : 0;
        };

        const sorted = filtered.slice().sort((a, b) => {
            switch (filter.sortOrder) {
                case 'name_asc':
                    return a.name.localeCompare(b.name);
                case 'name_desc':
                    return b.name.localeCompare(a.name);
                case 'used_in_projects':
                    return (usageOf(b.id)?.projects_count ?? 0) - (usageOf(a.id)?.projects_count ?? 0);
                case 'used_in_agents':
                    return (usageOf(b.id)?.staff_count ?? 0) - (usageOf(a.id)?.staff_count ?? 0);
                case 'most_used':
                    return usageSum(b.id) - usageSum(a.id);
                case 'unused_first':
                    return usageSum(a.id) - usageSum(b.id);
                default:
                    // Newest first (matches previous behaviour).
                    return b.id - a.id;
            }
        });

        return sorted.map((t) => {
            const u = showUsage ? usage.get(t.id) : undefined;
            return {
                id: t.id,
                kind: 'custom' as const,
                name: t.name,
                description: t.description,
                labelIds: t.labels ?? [],
                favorite: t.favorite,
                builtIn: t.built_in,
                projectsUsage: u?.projects_count || undefined,
                agentsUsage: u?.staff_count || undefined,
                unused: u?.projects_count === 0 && u?.staff_count === 0,
            };
        });
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
                    .copyPythonCodeTool(payload.tool.id)
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
            case 'show_used_places':
                // TODO: open a "used in" side panel once its component is defined.
                return;
        }
    }

    public onCardSelectedChange(payload: { tool: ToolCardVM; selected: boolean }): void {
        this.viewState.setSelected(payload.tool.id, payload.selected);
    }

    public onCardFavoriteChange(payload: { tool: ToolCardVM; favorite: boolean }): void {
        this.customToolsService
            .patchPythonCodeTool(payload.tool.id, { favorite: payload.favorite })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (updated) => this.replaceToolInState(updated),
                error: (err: HttpErrorResponse) => {
                    this.toastService.error(
                        err.error?.message || `Failed to update favorite for "${payload.tool.name}".`
                    );
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
                this.handleDeleteUnused();
                return;
            case 'favorite':
                this.handleBulkFavorite();
                return;
            case 'duplicate':
                this.handleBulkDuplicate();
                return;
            case 'delete-selected':
                this.handleBulkDeleteSelected();
                return;
            case 'add-labels':
                this.handleBulkAddLabels(event.labelIds ?? []);
                return;
            case 'open-include-exclude':
                this.openIncludeExcludeDialog(event.initialTab ?? 'tools');
                return;
        }
    }

    private openIncludeExcludeDialog(initialTab: IncludeExcludeTab): void {
        this.labelsStorage.loadLabels().subscribe(() => {
            const current = this.viewState.filter();
            const data: ToolsIncludeExcludeDialogData = {
                initialTab,
                tools: this.allTools().map((t) => ({ id: t.id, name: t.name })),
                selectedToolIds: current.includedToolIds,
                selectedLabelIds: current.includedLabelIds,
            };
            const ref = this.dialog.open<ToolsIncludeExcludeDialogResult | undefined>(
                ToolsIncludeExcludeDialogComponent,
                {
                    data,
                    panelClass: 'tools-filter-dialog-panel',
                    hasBackdrop: true,
                }
            );
            ref.closed.subscribe((result) => {
                if (!result) return;
                this.viewState.patchFilter({
                    includedToolIds: result.includedToolIds,
                    includedLabelIds: result.includedLabelIds,
                });
            });
        });
    }

    private handleDeleteUnused(): void {
        const filteredIds = this.cards().map((c) => c.id);
        if (filteredIds.length === 0) return;

        this.customToolsService
            .getBulkUsageDetailById(filteredIds)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (items) => {
                    const unusedIds = items
                        .filter((i) => i.projects_count === 0 && i.staff_count === 0 && !i.is_built_in)
                        .map((i) => i.id);
                    if (unusedIds.length === 0) {
                        this.toastService.info('No unused custom tools to delete.');
                        return;
                    }
                    this.confirmationDialogService
                        .confirm({
                            title: 'Delete unused tools',
                            message: `Are you sure you want to delete <strong>${unusedIds.length}</strong> unused custom tool(s)? <br> This action cannot be undone.`,
                            confirmText: 'Delete',
                            cancelText: 'Cancel',
                            type: 'danger',
                        })
                        .pipe(takeUntilDestroyed(this.destroyRef))
                        .subscribe((result) => {
                            if (result !== true) return;
                            this.bulkDelete(unusedIds, 'unused');
                        });
                },
                error: (err: HttpErrorResponse) => {
                    this.toastService.error(err.error?.message || 'Failed to load usage data.');
                },
            });
    }

    private handleBulkFavorite(): void {
        const ids = Array.from(this.viewState.selectedIds());
        if (ids.length === 0) return;
        const requests = ids.map((id) => this.customToolsService.patchPythonCodeTool(id, { favorite: true }));
        settleAll(requests)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((results) => {
                const { successes, failures } = partitionSettled(results);
                if (successes.length > 0) {
                    this.replaceManyInState(successes);
                    this.viewState.clear();
                    this.toastService.success(`Marked ${successes.length} tool(s) as favorite.`);
                }
                if (failures.length > 0) {
                    this.toastService.error(`Failed to update ${failures.length} tool(s).`);
                }
            });
    }

    private handleBulkDuplicate(): void {
        const ids = Array.from(this.viewState.selectedIds());
        if (ids.length === 0) return;
        const requests = ids.map((id) => this.customToolsService.copyPythonCodeTool(id));
        settleAll(requests)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((results) => {
                const { successes, failures } = partitionSettled(results);
                if (successes.length > 0) {
                    this.allTools.update((list) => [...successes, ...list]);
                    this.viewState.clear();
                    this.toastService.success(`Duplicated ${successes.length} tool(s).`);
                }
                if (failures.length > 0) {
                    this.toastService.error(`Failed to duplicate ${failures.length} tool(s).`);
                }
            });
    }

    private handleBulkDeleteSelected(): void {
        const ids = Array.from(this.viewState.selectedIds());
        if (ids.length === 0) return;
        this.confirmationDialogService
            .confirm({
                title: 'Confirm Deletion',
                message: `Are you sure you want to delete <strong>${ids.length}</strong> custom tool(s)? <br> This action cannot be undone.`,
                confirmText: 'Delete',
                cancelText: 'Cancel',
                type: 'danger',
            })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((result) => {
                if (result !== true) return;
                this.bulkDelete(ids, 'selected');
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
        settleAll(requests)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((results) => {
                const { successes, failures } = partitionSettled(results);
                if (successes.length > 0) {
                    this.replaceManyInState(successes);
                    this.viewState.clear();
                    this.toastService.success(`Updated labels for ${successes.length} tool(s).`);
                }
                if (failures.length > 0) {
                    this.toastService.error(`Failed to update labels for ${failures.length} tool(s).`);
                }
            });
    }

    private bulkDelete(ids: number[], scopeLabel: 'unused' | 'selected'): void {
        this.customToolsService
            .bulkDeletePythonCode(ids)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => {
                    const idSet = new Set(ids);
                    this.allTools.update((list) => list.filter((t) => !idSet.has(t.id)));
                    this.viewState.clear();
                    this.toastService.success(`Deleted ${ids.length} ${scopeLabel} tool(s).`);
                },
                error: (err: HttpErrorResponse) => {
                    this.toastService.error(err.error?.message || `Failed to delete ${scopeLabel} tools.`);
                },
            });
    }

    private replaceToolInState(updated: GetPythonCodeToolRequest): void {
        this.allTools.update((list) => list.map((t) => (t.id === updated.id ? updated : t)));
    }

    private replaceManyInState(updated: GetPythonCodeToolRequest[]): void {
        const byId = new Map(updated.map((t) => [t.id, t]));
        this.allTools.update((list) => list.map((t) => byId.get(t.id) ?? t));
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
                    if (!result) {
                        return;
                    }

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
        const currentTools = this.allTools();
        this.allTools.set([tool, ...currentTools]);
    }
}
