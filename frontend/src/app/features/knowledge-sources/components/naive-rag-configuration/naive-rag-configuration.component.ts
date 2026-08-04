import { Dialog } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    effect,
    inject,
    input,
    OnInit,
    signal,
    WritableSignal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import {
    AppSvgIconComponent,
    ButtonComponent,
    ConfirmationDialogService,
    SearchComponent,
    SelectComponent,
    SelectItem,
} from '@shared/components';
import { EMPTY, Observable, of } from 'rxjs';
import { catchError, switchMap } from 'rxjs/operators';

import { ToastService } from '../../../../services/notifications';
import { IndexingDocumentInfo } from '../../helpers/get-indexing-confirmation-data.util';
import {
    BulkUpdateNaiveRagDocumentsResponse,
    UpdateNaiveRagDocumentDtoRequest,
} from '../../models/naive-rag-document.model';
import { RagConfiguration } from '../../models/rag-configuration';
import { ChunkDeepLinkService } from '../../services/chunk-deep-link.service';
import { KnowledgeSourcesPollingService } from '../../services/knowledge-sources-polling.service';
import { NaiveRagService } from '../../services/naive-rag.service';
import { NaiveRagDocumentsStorageService } from '../../services/naive-rag-documents-storage.service';
import { DocumentChunksSectionComponent } from '../document-chunks-section/document-chunks-section.component';
import { EditFileParametersDialogComponent } from '../edit-file-parameters-dialog/edit-file-parameters-dialog.component';
import { ConfigurationTableComponent } from './configuration-table/configuration-table.component';
import { DocumentStatusFilter } from './configuration-table/configuration-table.interface';

@Component({
    selector: 'app-naive-rag-configuration',
    templateUrl: './naive-rag-configuration.component.html',
    styleUrls: ['./naive-rag-configuration.component.scss'],
    imports: [
        FormsModule,
        SearchComponent,
        ConfigurationTableComponent,
        ButtonComponent,
        DocumentChunksSectionComponent,
        AppSvgIconComponent,
        SelectComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class NaiveRagConfigurationComponent implements OnInit, RagConfiguration {
    private confirmationDialogService = inject(ConfirmationDialogService);
    private naiveRagService = inject(NaiveRagService);
    private destroyRef = inject(DestroyRef);
    private toastService = inject(ToastService);
    private documentsStorageService = inject(NaiveRagDocumentsStorageService);
    private deepLinkService = inject(ChunkDeepLinkService);
    private pollingService = inject(KnowledgeSourcesPollingService);
    private dialog = inject(Dialog);

    naiveRagId = input.required<number>();
    collectionId = input.required<number>();
    canIndexChange = input<WritableSignal<boolean>>();

    statusFilterItems: SelectItem<DocumentStatusFilter>[] = [
        { name: 'Show All', value: 'all' },
        { name: 'Issues', value: 'issues' },
        { name: 'Not indexed', value: 'not_indexed' },
        { name: 'Indexed', value: 'indexed' },
    ];

    searchTerm = signal<string>('');
    statusFilter = signal<DocumentStatusFilter>('all');
    bulkBtnActive = signal<boolean>(false);
    selectedRagDocId = signal<number | null>(null);
    filteredAndCheckedDocIds = signal<number[]>([]);
    tuneChunkOpened = signal<boolean>(false);

    showBulkRow = computed(() => this.bulkBtnActive() && !!this.filteredAndCheckedDocIds().length);

    constructor() {
        effect(() => {
            this.canIndexChange()?.set(this.filteredAndCheckedDocIds().length > 0);
        });
    }

    ngOnInit() {
        const id = this.naiveRagId();
        this.documentsStorageService.clear();
        this.documentsStorageService
            .fetchDocumentConfigs(id)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => this.handleDeepLink(),
                error: (e) => {
                    this.toastService.error('Failed to fetch documents');
                    console.error(e);
                },
            });

        this.pollingService.startDocumentConfigsPolling(id);
        this.destroyRef.onDestroy(() => this.pollingService.stopDocumentConfigsPolling());
    }

    initDocuments() {
        const id = this.naiveRagId();

        this.naiveRagService
            .initializeDocuments(id)
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                switchMap((response) => {
                    if (response && response.configs_created > 0) {
                        return this.documentsStorageService.fetchDocumentConfigs(id);
                    } else {
                        return EMPTY;
                    }
                })
            )
            .subscribe({
                next: () => {},
                error: (e) => {
                    this.toastService.error('Failed to fetch documents');
                    console.log(e);
                },
            });
    }

    /**
     * Bulk-row apply to pending only. Save happens via Save & Run Indexing.
     */
    applyPendingBulkEdit(patch: UpdateNaiveRagDocumentDtoRequest) {
        const config_ids = this.filteredAndCheckedDocIds();
        if (!config_ids.length) return;

        for (const id of config_ids) {
            this.documentsStorageService.setPendingFields(id, patch);
        }
    }

    applyBulkDelete() {
        const config_ids = this.filteredAndCheckedDocIds();
        if (!config_ids.length) return;

        this.confirmationDialogService
            .confirm({
                title: 'Confirm Deletion',
                message: `Are you sure you want to delete selected file(s)? <br> You can return them by clicking the 'Re-include Files' button.`,
                confirmText: 'Delete',
                cancelText: 'Cancel',
                type: 'info',
            })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((result) => {
                if (result === true) {
                    this.deleteDocConfigs(config_ids);
                }
            });
    }

    private deleteDocConfigs(config_ids: number[]) {
        const id = this.naiveRagId();

        this.documentsStorageService
            .bulkDeleteDocConfigs(id, config_ids)
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                catchError(() => {
                    this.toastService.error('Documents delete failed');
                    return of();
                })
            )
            .subscribe({
                next: (res) => this.toastService.success(res.message),
                error: (e) => console.error(e),
            });
    }

    openTuneChunkModal({ ragDocumentId, allDocumentIds }: { ragDocumentId: number; allDocumentIds: number[] }) {
        this.tuneChunkOpened.set(true);
        const dialogRef = this.dialog.open(EditFileParametersDialogComponent, {
            width: 'calc(100vw - 2rem)',
            height: 'calc(100vh - 2rem)',
            data: {
                ragId: this.naiveRagId(),
                collectionId: this.collectionId(),
                ragDocumentId,
                allDocumentIds,
            },
            disableClose: true,
        });

        dialogRef.closed.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => this.tuneChunkOpened.set(false));
    }

    getConfigurationData(): unknown {
        return true;
    }

    // TODO check is this can be removed
    // Naive rag persists per-document pending fields via its own bulk endpoint
    // called from the naive dialog wrapper. The generic save-then-index flow does
    // nothing extra here.
    shouldSaveConfig(): boolean {
        return false;
    }

    getDocumentConfigIds(): number[] {
        return this.filteredAndCheckedDocIds();
    }

    hasUnsavedChanges(): boolean {
        return this.documentsStorageService.pending().size > 0;
    }

    // TODO check this
    getIndexingDocuments(): IndexingDocumentInfo[] {
        const checkedIds = this.filteredAndCheckedDocIds();
        const docs = this.documentsStorageService
            .documents()
            .filter((d) => checkedIds.includes(d.naive_rag_document_id));

        return docs.map((d) => ({
            fileName: d.file_name,
            wasIndexed: d.status === 'completed' || d.status === 'outdated',
        }));
    }
    // TODO and this
    getDocumentsForIndexing(): { configIds: number[]; fileNames: string[] } {
        const checkedIds = this.filteredAndCheckedDocIds();
        const docs = this.documentsStorageService
            .documents()
            .filter((d) => checkedIds.includes(d.naive_rag_document_id));

        return {
            configIds: checkedIds,
            fileNames: docs.map((d) => d.file_name),
        };
    }

    uploadPendingForChecked(): Observable<BulkUpdateNaiveRagDocumentsResponse | null> {
        const id = this.naiveRagId();
        const checkedIds = this.filteredAndCheckedDocIds();
        if (!checkedIds.length) return of(null);

        return this.documentsStorageService.bulkPartialUpdate(id, checkedIds).pipe(
            catchError((err: HttpErrorResponse) => {
                const first = err.error?.errors?.[0];
                this.toastService.error(first?.reason ? `Save failed: ${first.reason}` : 'Save failed');
                return of(null);
            })
        );
    }

    hasFailedSavesForChecked(): boolean {
        const checkedIds = new Set(this.filteredAndCheckedDocIds());
        return this.documentsStorageService.documents().some((d) => {
            if (!checkedIds.has(d.naive_rag_document_id)) return false;
            return !!d.errors && Object.keys(d.errors).length > 0;
        });
    }

    private handleDeepLink(): void {
        const params = this.deepLinkService.pending();
        if (!params || params.ragId !== this.naiveRagId()) return;

        const documents = this.documentsStorageService.documents();
        const doc = documents.find((d) => d.naive_rag_document_id === params.documentId);

        if (!doc) {
            this.toastService.error('Deep link: document not found');
            this.deepLinkService.consume();
            this.deepLinkService.clearUrl();
            return;
        }

        this.selectedRagDocId.set(params.documentId);
    }
}
