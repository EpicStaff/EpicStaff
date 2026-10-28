import { Dialog } from '@angular/cdk/dialog';
import { OverlayModule } from '@angular/cdk/overlay';
import { HttpErrorResponse } from '@angular/common/http';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    computed,
    DestroyRef,
    effect,
    inject,
    OnDestroy,
    OnInit,
    signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ActivatedRoute, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import {
    AppSvgIconComponent,
    BulkSelectDropdownComponent,
    ButtonComponent,
    LabelSidebarComponent,
    SearchComponent,
    TabButtonComponent,
} from '@shared/components';
import {
    CollapseOnOverflowDirective,
    HasPermissionDirective,
    HideInlineSubtitleOnOverflowDirective,
    ResizableSidebarDirective,
} from '@shared/directives';
import { ActionCode, LabelTreeNode, ResourceCode } from '@shared/models';
import {
    AppStorageService,
    BulkDeleteService,
    EmbeddingConfigStorageService,
    EmbeddingModelsStorageService,
    LABELS_STORE,
    LlmConfigStorageService,
    LlmModelsStorageService,
    LlmProvidersStorageService,
    RealtimeConfigStorageService,
    RealtimeModelsStorageService,
    SidebarWidthOptions,
    SidebarWidthService,
    StorageService,
    TranscriptionConfigStorageService,
    TranscriptionModelsStorageService,
} from '@shared/services';
import {
    buildPreviewImportResult,
    enrichImportResult,
    extractHttpErrorMessage,
    ImportFileData,
    JsonObject,
    showExportExclusionWarning,
} from '@shared/utils';
import { EMPTY, forkJoin, from, Observable, of, Subject } from 'rxjs';
import {
    catchError,
    debounceTime,
    distinctUntilChanged,
    filter,
    finalize,
    map,
    switchMap,
    take,
    tap,
} from 'rxjs/operators';

import { ImportFlowRequestOptions, ImportResult } from '../../../../core/models/import-result.model';
import {
    FlowNodesByFile,
    hasReviewableItems,
    ImportReviewDialogCloseResult,
    toFileNodeId,
} from '../../../../core/models/review-item.model';
import { ImportExportService } from '../../../../core/services/import-export.service';
import { ToastService } from '../../../../services/notifications';
import { RecycleBinSettingsService } from '../../../../services/recycle-bin';
import { isUsableCondition } from '../../../audit/models/audit-filter.models';
import { CreateFlowDialogComponent } from '../../components/create-flow-dialog/create-flow-dialog.component';
import { ImportFlowOptionsPopoverComponent } from '../../components/import-flow-options-popover/import-flow-options-popover.component';
import { ImportResultDialogComponent } from '../../components/import-result-dialog/import-result-dialog.component';
import { ImportReviewDialogComponent } from '../../components/import-review-dialog/import-review-dialog.component';
import { EMPTY_FLOWS_FILTER, FlowsFilterState, FlowSortOrder } from '../../models/flow-filter.model';
import { GraphDto } from '../../models/graph.model';
import { FlowCopyImportFacadeService } from '../../services/flow-copy-import-facade.service';
import { FlowsStorageService } from '../../services/flows-storage.service';
import { ImportFlowSettingsService } from '../../services/import-flow-settings.service';
import { LabelsStorageService } from '../../services/labels-storage.service';
import { parseFilterFromParams, serializeFilterToParams } from '../../utils/flow-filter-url.utils';
import { flowsBulkDeleteGroup } from '../../utils/flows-bulk-delete.util';
import { FlowsFilterSidebarComponent } from './components/flows-filter-sidebar/flows-filter-sidebar.component';
import { FLOWS_SORT_MENU_ITEMS, FlowsSortMenuComponent } from './components/flows-sort-menu/flows-sort-menu.component';

const FILTER_PANEL_WIDTH_KEY = 'flows-filter-panel';
const FILTER_PANEL_WIDTH_OPTIONS = { defaultWidth: 360, minWidth: 280, maxWidth: 640 } satisfies SidebarWidthOptions;

@Component({
    templateUrl: './flows-list-page.component.html',
    styleUrls: ['./flows-list-page.component.scss'],
    imports: [
        RouterOutlet,
        RouterLink,
        RouterLinkActive,
        ButtonComponent,
        BulkSelectDropdownComponent,
        TabButtonComponent,
        FormsModule,
        AppSvgIconComponent,
        LabelSidebarComponent,
        HideInlineSubtitleOnOverflowDirective,
        CollapseOnOverflowDirective,
        ImportFlowOptionsPopoverComponent,
        OverlayModule,
        HasPermissionDirective,
        MatTooltipModule,
        SearchComponent,
        FlowsFilterSidebarComponent,
        FlowsSortMenuComponent,
        ResizableSidebarDirective,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
    providers: [{ provide: LABELS_STORE, useExisting: LabelsStorageService }],
})
export class FlowsListPageComponent implements OnInit, OnDestroy {
    public tabs = [
        { label: 'My Flows', link: 'my' },
        { label: 'Templates', link: 'templates' },
    ];

    public searchTerm: string = '';
    private searchTerms = new Subject<string>();

    private dialog = inject(Dialog);
    private flowStorageService = inject(FlowsStorageService);
    private router = inject(Router);
    private activatedRoute = inject(ActivatedRoute);
    private cdr = inject(ChangeDetectorRef);
    private importExportService = inject(ImportExportService);
    private flowCopyImport = inject(FlowCopyImportFacadeService);
    private toastService = inject(ToastService);
    private labelsStorage = inject(LabelsStorageService);
    private importFlowSettings = inject(ImportFlowSettingsService);
    private destroyRef = inject(DestroyRef);
    private appStorage = inject(AppStorageService);
    private bulkDeleteService = inject(BulkDeleteService);
    private recycleBinSettings = inject(RecycleBinSettingsService);

    private readonly storageInvalidationMap: Record<string, StorageService[]> = {
        LLMModel: [inject(LlmModelsStorageService), inject(LlmProvidersStorageService)],
        LLMConfig: [inject(LlmConfigStorageService)],
        EmbeddingModel: [inject(EmbeddingModelsStorageService), inject(LlmProvidersStorageService)],
        EmbeddingConfig: [inject(EmbeddingConfigStorageService)],
        RealtimeModel: [inject(RealtimeModelsStorageService), inject(LlmProvidersStorageService)],
        RealtimeConfig: [inject(RealtimeConfigStorageService)],
        RealtimeTranscriptionModel: [inject(TranscriptionModelsStorageService), inject(LlmProvidersStorageService)],
        RealtimeTranscriptionConfig: [inject(TranscriptionConfigStorageService)],
    };

    public importOptionsOpen = signal(false);

    public selectMode = this.flowStorageService.selectMode;
    public selectedFlowIds = this.flowStorageService.selectedFlowIds;
    public isDeleting = this.flowStorageService.isDeleting;

    public readonly filterState = this.flowStorageService.filter;

    // --- Filter sidebar & sort menu ---
    public showSidebar = signal<boolean>(true);
    public showFilterSidebar = signal<boolean>(false);
    public sortMenuOpen = signal<boolean>(false);

    protected readonly filterPanelWidthKey = FILTER_PANEL_WIDTH_KEY;
    protected readonly filterPanelWidthOptions = FILTER_PANEL_WIDTH_OPTIONS;
    protected readonly filterPanelWidth = inject(SidebarWidthService).getWidth(
        FILTER_PANEL_WIDTH_KEY,
        FILTER_PANEL_WIDTH_OPTIONS
    );

    private readonly sortDropdownOrders: readonly FlowSortOrder[] = FLOWS_SORT_MENU_ITEMS.map((i) => i.value);

    public readonly activeSort = computed<FlowSortOrder>(() => {
        const order = this.filterState().sortOrder;
        return this.sortDropdownOrders.includes(order) ? order : 'default';
    });

    public readonly sortTriggerLabel = computed<string>(() => {
        const order = this.activeSort();
        if (order === 'default') return 'Sort';
        return FLOWS_SORT_MENU_ITEMS.find((i) => i.value === order)?.label ?? 'Sort';
    });

    public readonly activeFilterCount = computed<number>(() => {
        const f = this.filterState();
        let n = 0;
        if (f.includedFlowIds !== null) n++;
        if (f.includedLabelIds !== null) n++;
        if (f.customConditions.some((group) => group.conditions.some((c) => isUsableCondition(c)))) n++;
        return n;
    });

    public readonly activeLabelFilterDisplay = computed(() => {
        const filter = this.labelsStorage.activeLabelFilter();
        if (filter === 'all') return 'all';
        if (filter === 'unlabeled') return 'Unlabeled';
        const label = this.labelsStorage.labels().find((l) => l.id === filter);
        return label && label.parent ? label.full_path : label?.name;
    });

    public toggleSidebar(): void {
        this.showSidebar.update((v) => !v);
    }

    public readonly deleteMessageForLabel = (label: LabelTreeNode): string => {
        return `Are you sure you want to delete <strong>${label.name}</strong> label? This will remove it from all flows and sublabels.`;
    };

    public readonly deleteCautionForLabel = (label: LabelTreeNode): string | undefined => {
        const flows = this.flowStorageService.flows();
        const sublabelCount = this.countAllDescendants(label);
        const sublabelIds = this.getAllDescendantIds(label);

        const directFlowCount = flows.filter((f) => (f.label_ids || []).includes(label.id)).length;
        const sublabelFlowCount =
            sublabelIds.length > 0
                ? flows.filter((f) => (f.label_ids || []).some((id) => sublabelIds.includes(id))).length
                : 0;

        if (directFlowCount === 0 && sublabelCount === 0) return undefined;

        const parts: string[] = [];
        if (directFlowCount > 0) {
            parts.push(`<strong>${directFlowCount} flow${directFlowCount !== 1 ? 's' : ''}</strong>`);
        }
        if (sublabelCount > 0) {
            const sublabelPart = `<strong>${sublabelCount} sublabel${sublabelCount !== 1 ? 's' : ''}</strong>`;
            if (sublabelFlowCount > 0) {
                parts.push(
                    `${sublabelPart} containing <strong>${sublabelFlowCount} flow${sublabelFlowCount !== 1 ? 's' : ''}</strong>`
                );
            } else {
                parts.push(sublabelPart);
            }
        }
        return `The label is used in ${parts.join(' and ')}.`;
    };

    public onLabelDeleted(): void {
        this.flowStorageService.getFlows(true).subscribe();
    }

    private countAllDescendants(node: LabelTreeNode): number {
        return node.children.reduce((acc, child) => acc + 1 + this.countAllDescendants(child), 0);
    }

    private getAllDescendantIds(node: LabelTreeNode): number[] {
        const ids: number[] = [];
        const collect = (n: LabelTreeNode) => {
            for (const child of n.children) {
                ids.push(child.id);
                collect(child);
            }
        };
        collect(node);
        return ids;
    }

    public selectAllLabels(): void {
        this.labelsStorage.setActiveLabelFilter('all');
    }

    constructor() {
        this.searchTerms
            .pipe(debounceTime(300), distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
            .subscribe((term) => {
                this.updateSearch(term);
            });

        effect(() => {
            const state = this.filterState();
            this.syncFilterToUrl(state);
        });
    }

    ngOnInit(): void {
        this.activatedRoute.queryParamMap.pipe(take(1)).subscribe((paramMap) => {
            const params: Record<string, string> = {};
            for (const key of paramMap.keys) {
                const value = paramMap.get(key);
                if (value !== null) params[key] = value;
            }
            const initial = parseFilterFromParams(params);
            this.searchTerm = initial.searchTerm;
            this.flowStorageService.setFilter(initial);
            this.cdr.markForCheck();

            forkJoin({
                flows: this.flowStorageService.getFlows(),
                labels: this.labelsStorage.loadLabels(),
            }).subscribe(({ labels }) => {
                const knownLabelIds = new Set(labels.map((l) => l.id));

                const validatedLabelIds =
                    initial.includedLabelIds === null
                        ? null
                        : initial.includedLabelIds.filter((id) => knownLabelIds.has(id));

                const labelsChanged =
                    validatedLabelIds !== null &&
                    initial.includedLabelIds !== null &&
                    validatedLabelIds.length !== initial.includedLabelIds.length;

                if (!labelsChanged) return;

                this.applyFilterPatch({
                    includedLabelIds: validatedLabelIds && validatedLabelIds.length > 0 ? validatedLabelIds : null,
                });
            });
        });
    }

    ngOnDestroy(): void {
        this.searchTerm = '';
        this.flowStorageService.resetFilter();
        this.flowStorageService.setSelectMode(false);
    }

    public onSearchTermChange(term: string): void {
        this.searchTerms.next(term);
    }

    public clearSearch(): void {
        this.searchTerm = '';
        this.updateSearch('');
    }

    private updateSearch(searchTerm: string): void {
        this.applyFilterPatch({ searchTerm });
    }

    private applyFilterPatch(patch: Partial<FlowsFilterState>): void {
        const next: FlowsFilterState = { ...this.flowStorageService.getCurrentFilter(), ...patch };
        this.flowStorageService.setFilter(next);
        this.syncFilterToUrl(next);
        this.cdr.markForCheck();
    }

    private syncFilterToUrl(state: FlowsFilterState): void {
        const queryParams = serializeFilterToParams(state);
        this.router.navigate([], {
            relativeTo: this.activatedRoute,
            queryParams,
            queryParamsHandling: 'merge',
            replaceUrl: true,
        });
    }

    // --- Filter sidebar ---
    public toggleFilterSidebar(): void {
        this.showFilterSidebar.update((v) => !v);
    }

    // --- Sort menu ---
    public toggleSortMenu(): void {
        this.sortMenuOpen.update((v) => !v);
    }

    public closeSortMenu(): void {
        this.sortMenuOpen.set(false);
    }

    public onSortMenuAction(sort: FlowSortOrder): void {
        this.closeSortMenu();
        const next = this.filterState().sortOrder === sort ? 'default' : sort;
        this.applyFilterPatch({ sortOrder: next });
    }

    public clearAllFilters(event?: MouseEvent): void {
        event?.stopPropagation();
        this.applyFilterPatch({
            sortOrder: this.filterState().sortOrder,
            includedLabelIds: EMPTY_FLOWS_FILTER.includedLabelIds,
            customConditions: EMPTY_FLOWS_FILTER.customConditions,
        });
    }

    public openCreateFlowDialog(): void {
        const dialogRef = this.dialog.open<GraphDto | undefined>(CreateFlowDialogComponent, {
            width: '500px',
            providers: [{ provide: LABELS_STORE, useExisting: LabelsStorageService }],
        });

        dialogRef.closed.subscribe((result: GraphDto | undefined) => {
            if (result) {
                this.router.navigate(['/flows', result.id]);
            }
        });
    }

    public toggleImportOptions(): void {
        this.importOptionsOpen.update((v) => !v);
    }

    public closeImportOptions(): void {
        this.importOptionsOpen.set(false);
    }

    public onImportClick(): void {
        const settings = this.importFlowSettings.requestSettings();

        const input = document.createElement('input');
        input.type = 'file';
        input.accept = '.json';
        input.onchange = (event: Event) => {
            const file = (event.target as HTMLInputElement).files?.[0];
            if (!file) return;

            from(file.text())
                .pipe(
                    map((text) => this._parseFileData(text)),
                    switchMap((fileData) => this._importFlowFile(file, fileData, settings)),
                    catchError((error: HttpErrorResponse) => {
                        this.toastService.error(
                            extractHttpErrorMessage(
                                error,
                                'Failed to read the flow file. Please check the file and try again.'
                            )
                        );
                        return EMPTY;
                    }),
                    takeUntilDestroyed(this.destroyRef)
                )
                .subscribe(({ result, fileData }) => this._finishFlowImport(result, fileData));
        };
        input.click();
    }

    private _parseFileData(text: string): ImportFileData {
        try {
            return JSON.parse(text) as ImportFileData;
        } catch {
            return {};
        }
    }

    private _importFlowFile(
        file: File,
        fileData: ImportFileData,
        settings: ImportFlowRequestOptions
    ): Observable<{ result: ImportResult; fileData: ImportFileData }> {
        return this.importExportService.inspectFlow(file).pipe(
            switchMap((inspection) => {
                if (!hasReviewableItems(inspection.review_items)) {
                    // A refusal over trigger nodes is explained by the facade and emits nothing: no toast here.
                    return this.flowCopyImport.importFlow(file, settings).pipe(
                        map((result) => ({ result, fileData })),
                        catchError((error: HttpErrorResponse) => {
                            this.toastService.error(
                                extractHttpErrorMessage(
                                    error,
                                    'Failed to import flow. Please check the file and try again.'
                                )
                            );
                            return EMPTY;
                        })
                    );
                }

                const reviewRef = this.dialog.open<ImportReviewDialogCloseResult>(ImportReviewDialogComponent, {
                    width: 'calc(100vw - 2rem)',
                    height: 'calc(100vh - 2rem)',
                    autoFocus: false,
                    data: {
                        importResult: buildPreviewImportResult(fileData),
                        reviewItems: inspection.review_items,
                        allFlowNodes: this._extractFlowNodesFromFile(fileData),
                        // On a refusal over trigger nodes nothing is emitted, so the review dialog stays open.
                        importFn: () => this.flowCopyImport.importFlow(file, settings),
                    },
                });

                return reviewRef.closed.pipe(
                    switchMap((closeResult) =>
                        closeResult?.action === 'imported'
                            ? of({ result: closeResult.result as ImportResult, fileData })
                            : EMPTY
                    )
                );
            }),
            catchError((error: HttpErrorResponse) => {
                this.toastService.error(
                    extractHttpErrorMessage(error, 'Failed to read the flow file. Please check the file and try again.')
                );
                return EMPTY;
            })
        );
    }

    private _finishFlowImport(result: ImportResult, fileData: ImportFileData): void {
        const enriched = enrichImportResult(result, fileData);

        this.dialog.open(ImportResultDialogComponent, {
            width: 'calc(100vw - 2rem)',
            height: 'calc(100vh - 2rem)',
            data: { importResult: enriched },
        });

        this.invalidateStorages(result);
        this.labelsStorage.setActiveLabelFilter('all');
        this.flowStorageService.getFlows(true).pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
        this.labelsStorage.loadLabels(true).pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
    }

    private invalidateStorages(result: ImportResult): void {
        const storagesToInvalidate = Object.entries(this.storageInvalidationMap)
            .filter(([entityType]) => (result[entityType]?.total ?? 0) > 0)
            .flatMap(([, storages]) => storages);

        this.appStorage.invalidate(storagesToInvalidate);
    }

    private static readonly EXCLUDED_NODE_TYPES = new Set(['StartNode', 'EndNode']);

    private _extractFlowNodesFromFile(fileData: ImportFileData): FlowNodesByFile {
        const result: FlowNodesByFile = {};
        const flows = fileData['Flow'];
        if (!flows) return result;

        for (const flow of flows) {
            const flowName = String(flow['name'] ?? '');
            const rawNodes = flow['nodes'];
            if (!flowName || !Array.isArray(rawNodes)) continue;

            result[flowName] = rawNodes
                .filter((node): node is JsonObject => typeof node === 'object' && node !== null && !Array.isArray(node))
                .filter((node) => !FlowsListPageComponent.EXCLUDED_NODE_TYPES.has(String(node['node_type'] ?? '')))
                .map((node) => ({
                    id: toFileNodeId(node['id']),
                    name: String(node['node_name'] ?? node['node_type'] ?? 'Node'),
                    node_type: String(node['node_type'] ?? ''),
                }));
        }
        return result;
    }

    public onSelectClick(): void {
        this.flowStorageService.setSelectMode(true);
    }

    public cancelSelection(): void {
        this.flowStorageService.setSelectMode(false);
    }

    public confirmExport(): void {
        const ids = this.selectedFlowIds();
        if (ids.length === 0) {
            return;
        }

        this.importExportService.bulkExportFlow(ids).subscribe({
            next: ({ blob, excluded }) => {
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `flows_export_${Date.now()}.json`;
                a.click();
                window.URL.revokeObjectURL(url);

                this.flowStorageService.setSelectMode(false);

                showExportExclusionWarning(this.toastService, excluded);
            },
            error: (error) => {
                console.error('Bulk export failed:', error);
            },
        });
    }

    public deleteSelectedFlows(): void {
        const selectedIds = new Set(this.selectedFlowIds());
        const flows = this.flowStorageService.flows().filter((flow) => selectedIds.has(flow.id));
        if (flows.length === 0) {
            return;
        }

        this.isDeleting.set(true);
        this.bulkDeleteService
            .run([flowsBulkDeleteGroup(this.flowStorageService, flows, this.recycleBinSettings.retentionDays())])
            .pipe(
                tap(() => this.flowStorageService.setSelectMode(false)),
                filter((outcomes) => outcomes.some((outcome) => (outcome.response?.deleted_count ?? 0) > 0)),
                switchMap(() => this.flowStorageService.getFlows(true, this.labelsStorage.activeLabelFilter())),
                finalize(() => this.isDeleting.set(false)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe();
    }

    public selectAllFlows(): void {
        this.flowStorageService.toggleSelectAllFlows();
    }

    public isAllSelected(): boolean {
        return this.flowStorageService.isAllFlowsSelected();
    }

    public navigateToSessions() {
        this.router.navigate(['/sessions']);
    }

    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;
}
