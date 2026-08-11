import { Dialog } from '@angular/cdk/dialog';
import { OverlayModule } from '@angular/cdk/overlay';
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
import { AppSvgIconComponent, ButtonComponent, SearchComponent, TabButtonComponent } from '@shared/components';
import { LabelSidebarComponent } from '@shared/components';
import {
    AppCustomFilterDialogComponent,
    AppCustomFilterDialogData,
    AppCustomFilterDialogResult,
    AppIncludeExcludeDialogComponent,
    AppIncludeExcludeDialogData,
    AppIncludeExcludeDialogResult,
    IncludeExcludeTab,
} from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import { LabelTreeNode } from '@shared/models';
import {
    AppStorageService,
    EmbeddingConfigStorageService,
    EmbeddingModelsStorageService,
    LlmConfigStorageService,
    LlmModelsStorageService,
    LlmProvidersStorageService,
    RealtimeConfigStorageService,
    RealtimeModelsStorageService,
    StorageService,
    TranscriptionConfigStorageService,
    TranscriptionModelsStorageService,
} from '@shared/services';
import { LABELS_STORE } from '@shared/services';
import { forkJoin, Subject } from 'rxjs';
import { debounceTime, distinctUntilChanged, take } from 'rxjs/operators';

import { EntityTypeResult, ImportResult, ImportResultItem } from '../../../../core/models/import-result.model';
import { ImportExportService } from '../../../../core/services/import-export.service';
import { ToastService } from '../../../../services/notifications/toast.service';
import { HideInlineSubtitleOnOverflowDirective } from '../../../../shared/directives/hide-inline-subtitle-on-overflow.directive';
import { CreateFlowDialogComponent } from '../../components/create-flow-dialog/create-flow-dialog.component';
import {
    FlowsFilterMenuAction,
    FlowsFilterMenuComponent,
} from '../../components/filter/flows-filter-menu/flows-filter-menu.component';
import { ImportFlowOptionsPopoverComponent } from '../../components/import-flow-options-popover/import-flow-options-popover.component';
import { ImportResultDialogComponent } from '../../components/import-result-dialog/import-result-dialog.component';
import { EMPTY_FLOWS_FILTER, FlowsFilterState } from '../../models/flow-filter.model';
import { GraphDto } from '../../models/graph.model';
import { FlowsStorageService } from '../../services/flows-storage.service';
import { ImportFlowSettingsService } from '../../services/import-flow-settings.service';
import { LabelsStorageService } from '../../services/labels-storage.service';
import { parseFilterFromParams, serializeFilterToParams } from '../../utils/flow-filter-url.utils';

type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };
type JsonObject = { [key: string]: JsonValue };

interface ImportFileEntity {
    id?: number | string;
    name?: string;
    role?: string;
    custom_name?: string;
    [field: string]: JsonValue | undefined;
}

type ImportFileData = Record<string, ImportFileEntity[]>;

@Component({
    standalone: true,
    templateUrl: './flows-list-page.component.html',
    styleUrls: ['./flows-list-page.component.scss'],
    imports: [
        RouterOutlet,
        RouterLink,
        RouterLinkActive,
        ButtonComponent,
        TabButtonComponent,
        FormsModule,
        AppSvgIconComponent,
        LabelSidebarComponent,
        HideInlineSubtitleOnOverflowDirective,
        ImportFlowOptionsPopoverComponent,
        OverlayModule,
        FlowsFilterMenuComponent,
        HasPermissionDirective,
        MatTooltipModule,
        SearchComponent,
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
    private toastService = inject(ToastService);
    private labelsStorage = inject(LabelsStorageService);
    private importFlowSettings = inject(ImportFlowSettingsService);
    private destroyRef = inject(DestroyRef);
    private appStorage = inject(AppStorageService);

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
    public readonly filterState = this.flowStorageService.filter;

    public readonly hasActiveFilter = computed(() => {
        const f = this.filterState();
        return (
            f.sortOrder !== 'default' ||
            f.includedFlowIds !== null ||
            f.includedLabelIds !== null ||
            f.customFilter !== null
        );
    });

    public showSidebar = signal<boolean>(true);
    public filterMenuOpen = signal<boolean>(false);

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

            const hasIdsToValidate = initial.includedFlowIds !== null || initial.includedLabelIds !== null;
            if (!hasIdsToValidate) return;

            forkJoin({
                flows: this.flowStorageService.getFlows(),
                labels: this.labelsStorage.loadLabels(),
            }).subscribe(({ flows, labels }) => {
                const knownFlowIds = new Set(flows.map((f) => f.id));
                const knownLabelIds = new Set(labels.map((l) => l.id));

                const validatedFlowIds =
                    initial.includedFlowIds === null
                        ? null
                        : initial.includedFlowIds.filter((id) => knownFlowIds.has(id));
                const validatedLabelIds =
                    initial.includedLabelIds === null
                        ? null
                        : initial.includedLabelIds.filter((id) => knownLabelIds.has(id));

                const flowsChanged =
                    validatedFlowIds !== null &&
                    initial.includedFlowIds !== null &&
                    validatedFlowIds.length !== initial.includedFlowIds.length;
                const labelsChanged =
                    validatedLabelIds !== null &&
                    initial.includedLabelIds !== null &&
                    validatedLabelIds.length !== initial.includedLabelIds.length;

                if (!flowsChanged && !labelsChanged) return;

                this.applyFilterPatch({
                    includedFlowIds: validatedFlowIds && validatedFlowIds.length > 0 ? validatedFlowIds : null,
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

    public toggleFilterMenu(): void {
        this.filterMenuOpen.update((open) => !open);
    }

    public closeFilterMenu(): void {
        this.filterMenuOpen.set(false);
    }

    public onFilterMenuAction(action: FlowsFilterMenuAction): void {
        this.closeFilterMenu();
        switch (action) {
            case 'sort_asc':
                this.applyFilterPatch({ sortOrder: 'name_asc' });
                return;
            case 'sort_desc':
                this.applyFilterPatch({ sortOrder: 'name_desc' });
                return;
            case 'include_exclude':
                this.openIncludeExcludeDialog('primary');
                return;
            case 'custom_filter':
                this.openCustomFilterDialog();
                return;
        }
    }

    public clearAllFilters(): void {
        const reset: FlowsFilterState = {
            ...EMPTY_FLOWS_FILTER,
            searchTerm: this.flowStorageService.getCurrentFilter().searchTerm,
        };
        this.flowStorageService.setFilter(reset);
        this.syncFilterToUrl(reset);
        this.cdr.markForCheck();
    }

    private openIncludeExcludeDialog(initialTab: IncludeExcludeTab): void {
        this.labelsStorage.loadLabels().subscribe(() => {
            const current = this.flowStorageService.getCurrentFilter();
            const data: AppIncludeExcludeDialogData = {
                initialTab,
                primaryTab: {
                    label: 'Flows',
                    icon: 'flow',
                    searchPlaceholder: 'Search flow...',
                    emptyText: 'No flows match the search.',
                },
                items: this.flowStorageService.flows().map((f) => ({ id: f.id, name: f.name })),
                selectedItemIds: current.includedFlowIds,
                selectedLabelIds: current.includedLabelIds,
            };
            const ref = this.dialog.open<AppIncludeExcludeDialogResult | undefined>(AppIncludeExcludeDialogComponent, {
                data,
                panelClass: 'flows-filter-dialog-panel',
                hasBackdrop: true,
                providers: [{ provide: LABELS_STORE, useExisting: LabelsStorageService }],
            });
            ref.closed.subscribe((result) => {
                if (!result) return;
                this.applyFilterPatch({
                    includedFlowIds: result.includedItemIds,
                    includedLabelIds: result.includedLabelIds,
                });
            });
        });
    }

    private openCustomFilterDialog(): void {
        const data: AppCustomFilterDialogData = {
            scopes: [
                { key: 'flow_name', label: 'Flows', icon: 'flow', heading: 'Show flows matching the name conditions' },
                {
                    key: 'label_name',
                    label: 'Labels',
                    icon: 'label',
                    heading: 'Show flows matching the label conditions',
                },
            ],
            initialCondition: this.flowStorageService.getCurrentFilter().customFilter,
        };
        const ref = this.dialog.open<AppCustomFilterDialogResult | undefined>(AppCustomFilterDialogComponent, {
            data,
            panelClass: 'flows-filter-dialog-panel',
            hasBackdrop: true,
        });
        ref.closed.subscribe((result) => {
            if (!result) return;
            // Shared dialog stores scope as `string`; flows narrows it back to its own union.
            this.applyFilterPatch({
                customFilter: result.condition as FlowsFilterState['customFilter'],
            });
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

    private readonly ENTITY_FILE_FIELDS: Record<string, string[]> = {
        Flow: ['description', 'time_to_live', 'persistent_variables'],
        Project: ['description', 'process', 'memory', 'max_rpm', 'planning'],
        Agent: ['goal', 'backstory', 'max_iter', 'memory', 'allow_delegation', 'allow_code_execution'],
        LLMModel: ['provider_name', 'predefined', 'is_custom', 'description'],
        LLMConfig: ['custom_name', 'temperature', 'max_tokens', 'timeout'],
        PythonCodeTool: ['description'],
        MCPTool: ['description'],
        RealtimeModel: ['provider_name', 'is_custom'],
        RealtimeConfig: ['custom_name'],
    };

    public toggleImportOptions(): void {
        this.importOptionsOpen.update((v) => !v);
    }

    public closeImportOptions(): void {
        this.importOptionsOpen.set(false);
    }

    public onImportClick(): void {
        const settings = this.importFlowSettings.settings();

        const input = document.createElement('input');
        input.type = 'file';
        input.accept = '.json';
        input.onchange = (event: Event) => {
            const file = (event.target as HTMLInputElement).files?.[0];
            if (!file) return;

            file.text().then((text: string) => {
                let fileData: ImportFileData = {};
                try {
                    fileData = JSON.parse(text) as ImportFileData;
                } catch {}

                this.importExportService.importFlow(file, settings).subscribe({
                    next: (result) => {
                        const enriched = this._enrichImportResult(result, fileData);

                        this.dialog.open(ImportResultDialogComponent, {
                            width: '80vw',
                            data: { importResult: enriched },
                        });

                        this.invalidateStorages(result);
                        this.labelsStorage.setActiveLabelFilter('all');
                        this.flowStorageService.getFlows(true).subscribe(() => {});
                        this.labelsStorage.loadLabels(true).subscribe(() => {});
                    },
                    error: (error) => {
                        const message =
                            error?.error?.detail ||
                            error?.error?.message ||
                            'Failed to import flow. Please check the file and try again.';
                        this.toastService.error(message);
                    },
                });
            });
        };
        input.click();
    }

    private invalidateStorages(result: ImportResult): void {
        const storagesToInvalidate = Object.entries(this.storageInvalidationMap)
            .filter(([entityType]) => (result[entityType]?.total ?? 0) > 0)
            .flatMap(([, storages]) => storages);

        this.appStorage.invalidate(storagesToInvalidate);
    }

    // Per entity type: which field in the file serves as the display name
    // (used as fallback when id doesn't match, e.g. for newly created entities)
    private readonly ENTITY_NAME_KEY: Record<string, string> = {
        Agent: 'role',
        LLMConfig: 'custom_name',
        RealtimeConfig: 'custom_name',
    };

    private _enrichImportResult(result: ImportResult, fileData: ImportFileData): ImportResult {
        const enriched: ImportResult = {};

        for (const [entityType, entityResult] of Object.entries(result) as [string, EntityTypeResult][]) {
            const fields = this.ENTITY_FILE_FIELDS[entityType];
            const fileEntities: ImportFileEntity[] | undefined = fileData[entityType];

            if (!fields || !fileEntities) {
                enriched[entityType] = entityResult;
                continue;
            }

            const nameKey = this.ENTITY_NAME_KEY[entityType] ?? 'name';
            const lookupById = new Map<number | string, ImportFileEntity>();
            for (const e of fileEntities) {
                if (e.id !== undefined) lookupById.set(e.id, e);
            }
            const lookupByName = new Map<string, ImportFileEntity>(
                fileEntities.map((e) => [String(e[nameKey] ?? ''), e])
            );

            const enrichItems = (items: ImportResultItem[]) =>
                items.map((item) => {
                    const baseName = item.name.replace(/\s*\(\d+\)$/, '').trim();
                    const source = lookupById.get(item.id) ?? lookupByName.get(baseName);
                    if (!source) return item;
                    const extra: JsonObject = {};
                    for (const field of fields) {
                        const val = source[field];
                        if (val !== undefined) extra[field] = val;
                    }
                    return { ...item, ...extra };
                });

            enriched[entityType] = {
                ...entityResult,
                created: { ...entityResult.created, items: enrichItems(entityResult.created.items) },
                reused: { ...entityResult.reused, items: enrichItems(entityResult.reused.items) },
            };
        }

        return enriched;
    }

    public onExportClick(): void {
        this.flowStorageService.setSelectMode(true);
    }

    public cancelExport(): void {
        this.flowStorageService.setSelectMode(false);
    }

    public confirmExport(): void {
        const ids = this.selectedFlowIds();
        if (ids.length === 0) {
            return;
        }

        this.importExportService.bulkExportFlow(ids).subscribe({
            next: (blob) => {
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `flows_export_${Date.now()}.json`;
                a.click();
                window.URL.revokeObjectURL(url);

                this.flowStorageService.setSelectMode(false);
            },
            error: (error) => {
                console.error('Bulk export failed:', error);
            },
        });
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
