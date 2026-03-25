import { Dialog } from '@angular/cdk/dialog';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    computed,
    inject,
    OnDestroy,
    signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { Subject, Subscription } from 'rxjs';
import { debounceTime, distinctUntilChanged } from 'rxjs/operators';

<<<<<<< HEAD
import { CreateFlowDialogComponent } from '../../components/create-flow-dialog/create-flow-dialog.component';

import { Dialog } from '@angular/cdk/dialog';

import { ButtonComponent } from '../../../../shared/components/buttons/button/button.component';
import { TabButtonComponent } from '../../../../shared/components/tab-button/tab-button.component';
import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
=======
import { ImportExportService } from '../../../../core/services/import-export.service';
import { AppIconComponent } from '../../../../shared/components/app-icon/app-icon.component';
import { ButtonComponent } from '../../../../shared/components/buttons/button/button.component';
>>>>>>> main
import {
    FiltersListComponent,
    SearchFilterChange,
} from '../../../../shared/components/filters-list/filters-list.component';
import { TabButtonComponent } from '../../../../shared/components/tab-button/tab-button.component';
import { FlowService } from '../../../../visual-programming/services/flow.service';
import { CreateFlowDialogComponent } from '../../components/create-flow-dialog/create-flow-dialog.component';
import { CreateGraphDtoRequest, GraphDto, UpdateGraphDtoRequest } from '../../models/graph.model';
import { FlowsApiService } from '../../services/flows-api.service';
import { FlowsStorageService } from '../../services/flows-storage.service';
import { LabelsStorageService } from '../../services/labels-storage.service';
import { FlowsLabelSidebarComponent } from './components/flows-label-sidebar/flows-label-sidebar.component';

@Component({
    selector: 'app-flows-list-page',
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
<<<<<<< HEAD
        AppSvgIconComponent,
=======
        AppIconComponent,
        FlowsLabelSidebarComponent,
>>>>>>> main
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
    private subscription: Subscription;

    private dialog = inject(Dialog);
    private flowStorageService = inject(FlowsStorageService);
    private router = inject(Router);
    private cdr = inject(ChangeDetectorRef);
    private importExportService = inject(ImportExportService);
    private labelsStorage = inject(LabelsStorageService);

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
        this.subscription = this.searchTerms.pipe(debounceTime(300), distinctUntilChanged()).subscribe((term) => {
            this.updateSearch(term);
        });
    }

    ngOnDestroy(): void {
        if (this.subscription) {
            this.subscription.unsubscribe();
        }

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

    public onImportClick(): void {
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = '.json';
        input.onchange = (event: Event) => {
            const file = (event.target as HTMLInputElement).files?.[0];
            if (file) {
                this.importExportService.importFlow(file).subscribe({
                    next: (result) => {
                        console.log('Flow imported successfully:', result);
                        // Reload the page on successful import
                        window.location.reload();
                    },
                    error: (error) => {
                        console.error('Import failed:', error);
                        // TODO: Show error message to user
                    },
                });
            }
        };
        input.click();
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
