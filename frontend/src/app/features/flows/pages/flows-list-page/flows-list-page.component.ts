import { Dialog } from '@angular/cdk/dialog';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    computed,
    DestroyRef,
    inject,
    OnDestroy,
    signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { Subject } from 'rxjs';
import { debounceTime, distinctUntilChanged } from 'rxjs/operators';
import { ImportExportService } from '../../../../core/services/import-export.service';
import { ToastService } from '../../../../services/notifications/toast.service';
import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { ButtonComponent } from '../../../../shared/components/buttons/button/button.component';
import { SearchFilterChange } from '../../../../shared/components/filters-list/filters-list.component';
import { TabButtonComponent } from '../../../../shared/components/tab-button/tab-button.component';
import { HideInlineSubtitleOnOverflowDirective } from '../../../../shared/directives/hide-inline-subtitle-on-overflow.directive';
import { CreateFlowDialogComponent } from '../../components/create-flow-dialog/create-flow-dialog.component';
import {
    ImportFlowOptions,
    ImportFlowOptionsDialogComponent,
} from '../../components/import-flow-options-dialog/import-flow-options-dialog.component';
import { ImportResultDialogComponent } from '../../components/import-result-dialog/import-result-dialog.component';
import { GraphDto } from '../../models/graph.model';
import { EntityTypeResult, ImportResult, ImportResultItem } from '../../models/import-result.model';
import { FlowsStorageService } from '../../services/flows-storage.service';
import { LabelsStorageService } from '../../services/labels-storage.service';
import { FlowsLabelSidebarComponent } from './components/flows-label-sidebar/flows-label-sidebar.component';

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
        FlowsLabelSidebarComponent,
        HideInlineSubtitleOnOverflowDirective,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowsListPageComponent implements OnDestroy {
    public tabs = [
        { label: 'My Flows', link: 'my' },
        { label: 'Templates', link: 'templates' },
    ];

    public searchTerm: string = '';
    private searchTerms = new Subject<string>();

    private dialog = inject(Dialog);
    private flowStorageService = inject(FlowsStorageService);
    private router = inject(Router);
    private cdr = inject(ChangeDetectorRef);
    private importExportService = inject(ImportExportService);
    private toastService = inject(ToastService);
    private labelsStorage = inject(LabelsStorageService);
    private destroyRef = inject(DestroyRef);

    public selectMode = this.flowStorageService.selectMode;
    public selectedFlowIds = this.flowStorageService.selectedFlowIds;

    public showSidebar = signal<boolean>(true);

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

    public selectAllLabels(): void {
        this.labelsStorage.setActiveLabelFilter('all');
    }

    constructor() {
        this.searchTerms
            .pipe(debounceTime(300), distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
            .subscribe((term) => {
                this.updateSearch(term);
            });
    }

    ngOnDestroy(): void {
        this.searchTerm = '';
        this.flowStorageService.setFilter(null);
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
        const filter: SearchFilterChange = {
            searchTerm,
        };
        this.flowStorageService.setFilter(filter);
        this.cdr.markForCheck();
    }

    public openCreateFlowDialog(): void {
        const dialogRef = this.dialog.open<GraphDto | undefined>(CreateFlowDialogComponent, {
            width: '500px',
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

    public onImportClick(): void {
        const dialogRef = this.dialog.open<ImportFlowOptions | undefined>(ImportFlowOptionsDialogComponent, {
            width: '400px',
        });

        dialogRef.closed.subscribe((options) => {
            if (!options) return;

            const input = document.createElement('input');
            input.type = 'file';
            input.accept = '.json';
            input.onchange = (event: Event) => {
                const file = (event.target as HTMLInputElement).files?.[0];
                if (!file) return;

                file.text().then((text: string) => {
                    let fileData: Record<string, Record<string, unknown>[]> = {};
                    try {
                        fileData = JSON.parse(text);
                    } catch {}

                    this.importExportService.importFlow(file, options.preserveUuids).subscribe({
                        next: (result) => {
                            const enriched = this._enrichImportResult(result as ImportResult, fileData);

                            this.dialog.open(ImportResultDialogComponent, {
                                width: '80vw',
                                data: { importResult: enriched },
                            });

                            this.flowStorageService.getFlows(true).subscribe(() => {});
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
        });
    }

    // Per entity type: which field in the file serves as the display name
    // (used as fallback when id doesn't match, e.g. for newly created entities)
    private readonly ENTITY_NAME_KEY: Record<string, string> = {
        Agent: 'role',
        LLMConfig: 'custom_name',
        RealtimeConfig: 'custom_name',
    };

    private _enrichImportResult(
        result: ImportResult,
        fileData: Record<string, Record<string, unknown>[]>
    ): ImportResult {
        const enriched: ImportResult = {};

        for (const [entityType, entityResult] of Object.entries(result) as [string, EntityTypeResult][]) {
            const fields = this.ENTITY_FILE_FIELDS[entityType];
            const fileEntities: Record<string, unknown>[] | undefined = fileData[entityType];

            if (!fields || !fileEntities) {
                enriched[entityType] = entityResult;
                continue;
            }

            const nameKey = this.ENTITY_NAME_KEY[entityType] ?? 'name';
            const lookupById = new Map<number | string, Record<string, unknown>>(
                fileEntities.map((e) => [e['id'] as number | string, e])
            );
            const lookupByName = new Map<string, Record<string, unknown>>(
                fileEntities.map((e) => [String(e[nameKey] ?? ''), e])
            );

            const enrichItems = (items: ImportResultItem[]) =>
                items.map((item) => {
                    const baseName = item.name.replace(/\s*\(\d+\)$/, '').trim();
                    const source = lookupById.get(item.id) ?? lookupByName.get(baseName);
                    if (!source) return item;
                    const extra: Record<string, unknown> = {};
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
}
