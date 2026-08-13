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
import { ToolUsageDialogComponent } from '../../../../components/tool-usage-dialog/tool-usage-dialog.component';
import { GetBulkToolUsageItem } from '../../../../models/tool-config.model';
import { ToolsLabelsStorageService } from '../../../../services/tools-labels-storage.service';
import { ToolsSearchService } from '../../../../services/tools-search.service';
import { ToolsBulkActionEvent, ToolsViewStorageService } from '../../../../services/tools-view-storage.service';
import {
    buildBulkSelectedDeleteDialog,
    buildSingleDeleteWithUsageDialog,
    runBulkDeleteWithConfirm,
    runDeleteUnused,
    runSettledBulk,
} from '../../../../utils/bulk-tool-op.util';
import { compareTools, matchesToolFilter, toUsageVmFields } from '../../../../utils/tools-cards.util';
import { ToolCardComponent } from '../tool-card/tool-card.component';
import { ToolCardMenuAction, ToolCardVM } from '../tool-card/tool-card.model';
import { TOOLS_LIST_PORT, ToolsListPort } from './tools-list-port';

/** Minimal shape shared by all tool DTOs the port supplies. */
interface Tool {
    id: number;
    name: string;
    labels: number[];
    is_favorite: boolean;
}

@Component({
    selector: 'app-tools-list',
    changeDetection: ChangeDetectionStrategy.OnPush,
    templateUrl: './tools-list.component.html',
    styleUrls: ['./tools-list.component.scss'],
    imports: [LoadingSpinnerComponent, ToolCardComponent, DialogModule, CommonModule],
})
export class ToolsListComponent implements OnInit {
    private readonly destroyRef = inject(DestroyRef);
    private readonly dialog = inject(Dialog);
    private readonly toastService = inject(ToastService);
    private readonly confirmationDialogService = inject(ConfirmationDialogService);
    private readonly toolsSearchService = inject(ToolsSearchService);
    private readonly labelsStorage = inject(ToolsLabelsStorageService);
    private readonly port = inject<ToolsListPort<Tool>>(TOOLS_LIST_PORT);

    public readonly viewState = inject(ToolsViewStorageService);

    public readonly searchTerm = signal<string>('');
    public readonly error = signal<string | null>(null);
    public readonly isLoaded = signal<boolean>(false);

    private readonly allTools = signal<Tool[]>([]);
    private readonly usageById = signal<Map<number, GetBulkToolUsageItem>>(new Map());

    public readonly loadingMessage = computed(() => `Loading ${this.port.entityLabelPlural}...`);
    public readonly emptyMessage = computed(() => `No ${this.port.entityLabelPlural} found.`);

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
            .filter((t) => matchesToolFilter(t, ctx, this.port.filterAdapter))
            .slice()
            .sort((a, b) => compareTools(a, b, ctx.filter.sortOrder, usage, this.port.filterAdapter))
            .map<ToolCardVM>((t) => ({
                id: t.id,
                kind: this.port.kind,
                name: t.name,
                description: this.port.descriptionOf(t),
                labelIds: t.labels ?? [],
                favorite: t.is_favorite,
                builtIn: this.port.isBuiltIn(t),
                ...toUsageVmFields(usage, t.id, showUsage),
            }));
    });

    constructor() {
        effect(() => {
            const needsUsage = this.viewState.needsUsageData();
            const ids = this.allTools().map((t) => t.id);
            if (!needsUsage || ids.length === 0) return;
            this.port
                .getBulkUsage(ids)
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe({
                    next: (items) => this.usageById.set(new Map(items.map((i) => [i.id, i]))),
                    error: (err: HttpErrorResponse) => {
                        this.toastService.error(
                            err.error?.message || `Failed to load usage for ${this.port.entityLabelPlural}.`
                        );
                    },
                });
        });

        effect(() => {
            this.viewState.setVisibleToolIds(this.cards().map((c) => c.id));
        });
    }

    public ngOnInit(): void {
        this.loadTools();

        this.port.createdEvent$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((newTool) => {
            this.addNewTool(newTool);
        });

        this.toolsSearchService.searchTerm$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((term) => {
            this.searchTerm.set(term);
        });

        this.viewState.action$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((event) => {
            this.handleBulkAction(event);
        });
    }

    // --------------------------------------------------------------------- //
    // Card interactions
    // --------------------------------------------------------------------- //

    public onCardConfigure(vm: ToolCardVM): void {
        const tool = this.findToolById(vm.id);
        if (tool) this.onConfigure(tool);
    }

    public onCardDelete(vm: ToolCardVM): void {
        const tool = this.findToolById(vm.id);
        if (tool) this.onDelete(tool);
    }

    public onCardSelectedChange(payload: { tool: ToolCardVM; selected: boolean }): void {
        this.viewState.setSelected(payload.tool.id, payload.selected);
    }

    public onCardFavoriteChange(payload: { tool: ToolCardVM; favorite: boolean }): void {
        const req$ = payload.favorite ? this.port.addFav(payload.tool.id) : this.port.delFav(payload.tool.id);
        req$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
            next: () => this.setFavoriteInState([payload.tool.id], payload.favorite),
            error: (err: HttpErrorResponse) => {
                this.toastService.error(err.error?.message || `Failed to update favorite for "${payload.tool.name}".`);
            },
        });
    }

    public onCardLabelsChange(payload: { tool: ToolCardVM; labelIds: number[] }): void {
        this.port
            .patchLabels(payload.tool.id, payload.labelIds)
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

    public onCardMenuAction(payload: { tool: ToolCardVM; action: ToolCardMenuAction }): void {
        switch (payload.action) {
            case 'delete':
                this.onCardDelete(payload.tool);
                return;
            case 'duplicate':
                this.port
                    .copy(payload.tool.id, { name: payload.tool.name })
                    .pipe(takeUntilDestroyed(this.destroyRef))
                    .subscribe({
                        next: (copy) => this.addNewTool(copy),
                        error: (err: HttpErrorResponse) => {
                            this.toastService.error(
                                err.error?.message || `Failed to duplicate "${payload.tool.name}".`
                            );
                        },
                    });
                return;
            case 'export':
                this.port
                    .exportOne(payload.tool.id)
                    .pipe(takeUntilDestroyed(this.destroyRef))
                    .subscribe({
                        next: (blob) => downloadBlob(blob, this.port.exportFileName(payload.tool.name)),
                        error: (err: HttpErrorResponse) => {
                            this.toastService.error(err.error?.message || `Failed to export "${payload.tool.name}".`);
                        },
                    });
                return;
            case 'show_used_places':
                this.port
                    .getUsageDetail(payload.tool.id)
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

    // --------------------------------------------------------------------- //
    // Bulk action bus
    // --------------------------------------------------------------------- //

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
                        getBulkUsage: (ids) => this.port.getBulkUsage(ids),
                        bulkDelete: (ids) => this.port.bulkDelete(ids),
                        entityLabel: this.port.entityLabel,
                        entityLabelPlural: this.port.entityLabelPlural,
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
                const deletable = selected.filter((id) => {
                    const t = this.findToolById(id);
                    return !!t && !this.port.isBuiltIn(t);
                });
                const skipped = selected.length - deletable.length;
                if (skipped > 0) {
                    this.toastService.info(
                        `${skipped} built-in ${this.port.entityLabel}(s) cannot be deleted and will be skipped.`
                    );
                }
                if (deletable.length === 0) return;
                this.runBulkSelectedDelete(deletable);
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
            this.port
                .importFile(file)
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe({
                    next: () => {
                        this.toastService.success(`${capitalise(this.port.entityLabelPlural)} imported successfully.`);
                        this.loadTools();
                    },
                    error: (err: HttpErrorResponse) => {
                        this.toastService.error(
                            err.error?.message || `Failed to import ${this.port.entityLabelPlural}.`
                        );
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
        this.port
            .bulkExport(ids)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (blob) => downloadBlob(blob, this.port.bulkExportFileName()),
                error: (err: HttpErrorResponse) => {
                    this.toastService.error(
                        err.error?.message || `Failed to export selected ${this.port.entityLabelPlural}.`
                    );
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
        const requests = ids.map((id) => this.port.addFav(id).pipe(map(() => id)));
        runSettledBulk(requests, {
            destroyRef: this.destroyRef,
            toast: this.toastService,
            viewState: this.viewState,
            applySuccess: (succeededIds) => this.setFavoriteInState(succeededIds, true),
            successMessage: (n) => `Marked ${n} ${this.port.entityLabel}(s) as favorite.`,
            failureMessage: (n) => `Failed to update ${n} ${this.port.entityLabel}(s).`,
        });
    }

    private handleBulkDuplicate(): void {
        const ids = Array.from(this.viewState.selectedIds());
        const requests = ids.map((id) => {
            const source = this.findToolById(id);
            return this.port.copy(id, { name: source?.name ?? '' });
        });
        runSettledBulk(requests, {
            destroyRef: this.destroyRef,
            toast: this.toastService,
            viewState: this.viewState,
            applySuccess: (copies) => this.allTools.update((list) => [...copies, ...list]),
            successMessage: (n) => `Duplicated ${n} ${this.port.entityLabel}(s).`,
            failureMessage: (n) => `Failed to duplicate ${n} ${this.port.entityLabel}(s).`,
        });
    }

    private handleBulkAddLabels(labelIdsToAdd: number[]): void {
        const selectedIds = Array.from(this.viewState.selectedIds());
        if (selectedIds.length === 0 || labelIdsToAdd.length === 0) return;
        const requests = selectedIds.map((id) => {
            const tool = this.findToolById(id);
            const union = new Set<number>(tool?.labels ?? []);
            for (const l of labelIdsToAdd) union.add(l);
            return this.port.patchLabels(id, Array.from(union));
        });
        runSettledBulk(requests, {
            destroyRef: this.destroyRef,
            toast: this.toastService,
            viewState: this.viewState,
            applySuccess: (updated) => this.replaceManyInState(updated),
            successMessage: (n) => `Updated labels for ${n} ${this.port.entityLabel}(s).`,
            failureMessage: (n) => `Failed to update labels for ${n} ${this.port.entityLabel}(s).`,
        });
    }

    // --------------------------------------------------------------------- //
    // Single-tool ops
    // --------------------------------------------------------------------- //

    public onConfigure(tool: Tool): void {
        const dialogRef = this.port.openConfigureDialog(this.dialog, tool, this.allTools());
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

    public onDelete(tool: Tool): void {
        this.port
            .getBulkUsage([tool.id])
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (items) => {
                    const usage = items.find((i) => i.id === tool.id);
                    const staffCount = usage?.staff_count ?? 0;
                    const projectsCount = usage?.projects_count ?? 0;
                    const confirm$ =
                        staffCount + projectsCount > 0
                            ? this.confirmationDialogService.confirm(
                                  buildSingleDeleteWithUsageDialog(tool.name, staffCount, projectsCount)
                              )
                            : this.confirmationDialogService.confirmDelete(tool.name);
                    confirm$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((result) => {
                        if (result !== true) return;
                        this.performSingleDelete(tool);
                    });
                },
                error: (err: HttpErrorResponse) => {
                    this.toastService.error(err.error?.message || 'Failed to load usage data.');
                },
            });
    }

    private performSingleDelete(tool: Tool): void {
        this.port
            .delete(tool.id)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => {
                    this.allTools.update((list) => list.filter((t) => t.id !== tool.id));
                    this.toastService.success(
                        `${capitalise(this.port.entityLabel)} "${tool.name}" has been deleted successfully.`
                    );
                },
                error: (err: HttpErrorResponse) => {
                    this.toastService.error(
                        err.error?.message ||
                            `Failed to delete ${this.port.entityLabel} "${tool.name}". Please try again.`
                    );
                },
            });
    }

    private runBulkSelectedDelete(ids: number[]): void {
        this.port
            .getBulkUsage(ids)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (items) => {
                    const usageById = new Map(items.map((i) => [i.id, i]));
                    const tools = ids.map((id) => {
                        const tool = this.findToolById(id);
                        const usage = usageById.get(id);
                        return {
                            id,
                            name: tool?.name ?? '',
                            staffCount: usage?.staff_count ?? 0,
                            projectsCount: usage?.projects_count ?? 0,
                        };
                    });
                    runBulkDeleteWithConfirm(ids, {
                        destroyRef: this.destroyRef,
                        toast: this.toastService,
                        confirmation: this.confirmationDialogService,
                        viewState: this.viewState,
                        allTools: this.allTools,
                        bulkDelete: (deleteIds) => this.port.bulkDelete(deleteIds),
                        entityLabel: this.port.entityLabel,
                        scopeLabel: 'selected',
                        dialogData: buildBulkSelectedDeleteDialog(tools),
                    });
                },
                error: (err: HttpErrorResponse) => {
                    this.toastService.error(err.error?.message || 'Failed to load usage data.');
                },
            });
    }

    // --------------------------------------------------------------------- //
    // Local state helpers
    // --------------------------------------------------------------------- //

    private findToolById(id: number): Tool | undefined {
        return this.allTools().find((t) => t.id === id);
    }

    private replaceToolInState(updated: Tool): void {
        this.allTools.update((list) => list.map((t) => (t.id === updated.id ? updated : t)));
    }

    private replaceManyInState(updated: Tool[]): void {
        const byId = new Map(updated.map((t) => [t.id, t]));
        this.allTools.update((list) => list.map((t) => byId.get(t.id) ?? t));
    }

    private setFavoriteInState(ids: number[], value: boolean): void {
        const idSet = new Set(ids);
        this.allTools.update((list) => list.map((t) => (idSet.has(t.id) ? { ...t, is_favorite: value } : t)));
    }

    private addNewTool(tool: Tool): void {
        this.allTools.update((current) => [tool, ...current]);
    }

    private loadTools(): void {
        this.isLoaded.set(false);
        this.error.set(null);
        this.port
            .getAll()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (tools) => {
                    this.allTools.set(tools);
                    this.isLoaded.set(true);
                },
                error: (err: HttpErrorResponse) => {
                    this.error.set(
                        err.error?.message || `Failed to load ${this.port.entityLabelPlural}. Please try again later.`
                    );
                    this.isLoaded.set(true);
                },
            });
    }

    public reload(): void {
        this.loadTools();
    }
}

function capitalise(s: string): string {
    return s.length === 0 ? s : s[0].toUpperCase() + s.slice(1);
}
