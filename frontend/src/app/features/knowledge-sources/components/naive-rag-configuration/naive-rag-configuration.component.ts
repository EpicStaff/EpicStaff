import { Dialog } from '@angular/cdk/dialog';
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
import { EMPTY, groupBy, mergeMap, of, Subject } from 'rxjs';
import { catchError, debounceTime, switchMap } from 'rxjs/operators';

import { ToastService } from '../../../../services/notifications';
import { IndexingDocumentInfo } from '../../helpers/get-indexing-confirmation-data.util';
import { UpdateNaiveRagDocumentDtoRequest } from '../../models/naive-rag-document.model';
import { RagConfiguration } from '../../models/rag-configuration';
import { ChunkDeepLinkService } from '../../services/chunk-deep-link.service';
import { NaiveRagService } from '../../services/naive-rag.service';
import { NaiveRagDocumentsStorageService } from '../../services/naive-rag-documents-storage.service';
import { DocumentChunksSectionComponent } from '../document-chunks-section/document-chunks-section.component';
import { EditFileParametersDialogComponent } from '../edit-file-parameters-dialog/edit-file-parameters-dialog.component';
import { ConfigurationTableComponent } from './configuration-table/configuration-table.component';
import { DocFieldChange, DocumentStatusFilter } from './configuration-table/configuration-table.interface';

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

    private docFieldChange$ = new Subject<DocFieldChange>();

    constructor() {
        effect(() => {
            this.canIndexChange()?.set(this.filteredAndCheckedDocIds().length > 0);
        });
    }

    ngOnInit() {
        const id = this.naiveRagId();
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

        this.docFieldChange$
            .pipe(
                groupBy((change) => change.documentId),
                mergeMap((group$) =>
                    group$.pipe(
                        debounceTime(300),
                        switchMap((change) =>
                            this.documentsStorageService.updateDocumentField(id, change).pipe(
                                catchError((err) => {
                                    const [error] = err.error?.errors;

                                    this.toastService.error(`Update failed: ${error.reason}`);
                                    return EMPTY;
                                })
                            )
                        )
                    )
                ),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe(() => this.toastService.success('Document updated'));
    }

    onDocFieldChange(change: DocFieldChange) {
        this.docFieldChange$.next(change);
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

    applyBulkEdit(dto: UpdateNaiveRagDocumentDtoRequest) {
        const config_ids = this.filteredAndCheckedDocIds();
        if (!config_ids.length) return;
        const id = this.naiveRagId();

        this.documentsStorageService
            .bulkEditDocConfigs(id, config_ids, dto)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (res) => this.toastService.success(res.message),
                error: (e) => console.error(e),
            });
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

    getDocumentConfigIds(): number[] {
        const { configIds } = this.getDocumentsForIndexing();
        return configIds;
    }

    getIndexingDocuments(): IndexingDocumentInfo[] {
        const checkedIds = this.filteredAndCheckedDocIds();
        const allDocs = this.documentsStorageService.documents();
        const docs = checkedIds.length ? allDocs.filter((d) => checkedIds.includes(d.naive_rag_document_id)) : allDocs;

        return docs.map((d) => ({
            fileName: d.file_name,
            wasIndexed: d.status === 'completed' || d.status === 'warning',
        }));
    }

    getDocumentsForIndexing(): { configIds: number[]; fileNames: string[] } {
        const checkedIds = this.filteredAndCheckedDocIds();
        const allDocs = this.documentsStorageService.documents();

        if (checkedIds.length) {
            const checkedDocs = allDocs.filter((d) => checkedIds.includes(d.naive_rag_document_id));
            return {
                configIds: checkedIds,
                fileNames: checkedDocs.map((d) => d.file_name),
            };
        }

        return {
            configIds: allDocs.map((d) => d.naive_rag_document_id),
            fileNames: allDocs.map((d) => d.file_name),
        };
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
