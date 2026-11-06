import { Dialog } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, OnDestroy, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FetchErrorStateComponent, SpinnerComponent } from '@shared/components';
import { STORAGE_SIDEBAR_WIDTH_KEY } from '@shared/constants';
import { ResizableSidebarDirective } from '@shared/directives';
import { ImportedEntityStoragesService, SidebarWidthService } from '@shared/services';
import {
    buildPreviewImportResult,
    enrichImportResult,
    exportEnvelopeFile,
    ImportFileData,
    readExportEnvelope,
    withProgressToast,
} from '@shared/utils';
import { EMPTY, from, Observable, of, throwError } from 'rxjs';
import { catchError, finalize, map, switchMap } from 'rxjs/operators';

import { ImportResult } from '../../../../core/models/import-result.model';
import {
    hasReviewableItems,
    ImportReviewDialogCloseResult,
    InspectedImport,
    ReviewItem,
} from '../../../../core/models/review-item.model';
import {
    describeTransferError,
    IMPORT_WITHOUT_SUMMARY_MESSAGE,
    TRANSFER_JOB_MAX_WAIT_MS,
    TransferJobsService,
} from '../../../../core/services/transfer-jobs.service';
import { ToastService } from '../../../../services/notifications';
import { ImportResultDialogComponent } from '../../../flows/components/import-result-dialog/import-result-dialog.component';
import { ImportReviewDialogComponent } from '../../../flows/components/import-review-dialog/import-review-dialog.component';
import { CreateCollectionDialogComponent } from '../../components/create-collection-dialog/create-collection-dialog.component';
import { NaiveRagConfigurationDialog } from '../../components/rag-configuration-dialog/naive-rag-configuration-dialog/naive-rag-configuration-dialog.component';
import { ChunkDeepLinkService } from '../../services/chunk-deep-link.service';
import { CollectionsApiService } from '../../services/collections-api.service';
import { CollectionsStorageService } from '../../services/collections-storage.service';
import { KnowledgeSourcesPollingService } from '../../services/knowledge-sources-polling.service';
import { CollectionDetailsComponent } from './components/collection-details/collection-details.component';
import { CollectionsListItemSidebarComponent } from './components/collections-list-sidebar/collections-list-sidebar.component';

const IMPORT_PROGRESS_MESSAGE = 'Importing…';
/** Collections carry their files, which only an export archive holds. */
const ARCHIVE_REQUIRED_MESSAGE = 'Knowledge sources are imported from a .zip export. Choose a .zip file.';
const IMPORT_FAILED_MESSAGE = 'Failed to import knowledge sources. Please check the file and try again.';

interface CollectionImport {
    /** `null` when the server reported no summary. */
    result: ImportResult | null;
    fileData: ImportFileData;
}

@Component({
    selector: 'app-collections-list-page',
    templateUrl: './collections-list-page.component.html',
    styleUrls: ['./collections-list-page.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [
        CollectionDetailsComponent,
        CollectionsListItemSidebarComponent,
        SpinnerComponent,
        FetchErrorStateComponent,
        ResizableSidebarDirective,
    ],
})
export class CollectionsListPageComponent implements OnInit, OnDestroy {
    private destroyRef = inject(DestroyRef);
    private dialog = inject(Dialog);
    private collectionsStorageService = inject(CollectionsStorageService);
    private pollingService = inject(KnowledgeSourcesPollingService);
    private deepLinkService = inject(ChunkDeepLinkService);
    private toastService = inject(ToastService);
    private collectionsApiService = inject(CollectionsApiService);
    private transferJobs = inject(TransferJobsService);
    private importedEntityStorages = inject(ImportedEntityStoragesService);

    isLoading = signal<boolean>(true);
    error = signal<string | null>(null);
    collections = this.collectionsStorageService.collections;

    protected readonly sidebarStorageKey = STORAGE_SIDEBAR_WIDTH_KEY;
    protected readonly sidebarWidth = inject(SidebarWidthService).getWidth(STORAGE_SIDEBAR_WIDTH_KEY);

    ngOnInit(): void {
        this.deepLinkService.initFromUrl();
        this.getCollections();
        this.pollingService.startPagePolling();
    }

    ngOnDestroy(): void {
        this.pollingService.stopPagePolling();
    }

    getCollections(): void {
        this.isLoading.set(true);
        this.error.set(null);

        this.collectionsStorageService
            .getCollections(true)
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => {
                    this.isLoading.set(false);
                    this.handleDeepLink();
                })
            )
            .subscribe({
                error: () => this.error.set('Failed to load knowledge sources.'),
            });
    }

    retryLoad(): void {
        this.getCollections();
    }

    /** Picks an export archive, has its code reviewed when it carries any, imports it and shows what came in. */
    importCollections(): void {
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = '.zip';
        input.onchange = (event: Event) => {
            const file = (event.target as HTMLInputElement).files?.[0];
            if (!file) return;

            from(readExportEnvelope(file))
                .pipe(
                    switchMap(({ format, data }) =>
                        format === 'zip'
                            ? this.importArchive(file, data)
                            : throwError(() => new Error(ARCHIVE_REQUIRED_MESSAGE))
                    ),
                    catchError((error: unknown) => {
                        this.toastService.error(describeTransferError(error, IMPORT_FAILED_MESSAGE));
                        return EMPTY;
                    }),
                    takeUntilDestroyed(this.destroyRef)
                )
                .subscribe((collectionImport) => this.finishImport(collectionImport));
        };
        input.click();
    }

    /**
     * Inspects the archive's envelope, never its files, and imports the archive straight away or after the user has
     * reviewed the code it carries. The progress toast covers the inspection and a straight import; the review
     * dialog shows its own progress.
     */
    private importArchive(file: File, fileData: ImportFileData): Observable<CollectionImport> {
        const importFn = (): Observable<ImportResult | null> => this.transferJobs.importAndWait('collections', file);
        return this.collectionsApiService.inspect(exportEnvelopeFile(fileData)).pipe(
            switchMap(
                (inspection): Observable<InspectedImport> =>
                    hasReviewableItems(inspection.review_items)
                        ? of({ kind: 'review', reviewItems: inspection.review_items })
                        : importFn().pipe(map((result): InspectedImport => ({ kind: 'imported', result })))
            ),
            withProgressToast(this.toastService, IMPORT_PROGRESS_MESSAGE, TRANSFER_JOB_MAX_WAIT_MS),
            switchMap((inspected) =>
                inspected.kind === 'imported'
                    ? of(inspected.result)
                    : this.reviewAndImport(inspected.reviewItems, fileData, importFn)
            ),
            map((result) => ({ result, fileData }))
        );
    }

    /** Emits the import's result once the review dialog has imported the archive; nothing when the user cancels. */
    private reviewAndImport(
        reviewItems: ReviewItem[],
        fileData: ImportFileData,
        importFn: () => Observable<ImportResult | null>
    ): Observable<ImportResult | null> {
        const reviewRef = this.dialog.open<ImportReviewDialogCloseResult>(ImportReviewDialogComponent, {
            width: 'calc(100vw - 2rem)',
            height: 'calc(100vh - 2rem)',
            // On the dialog itself, not its first button: Enter imports from there.
            autoFocus: 'dialog',
            data: {
                importResult: buildPreviewImportResult(fileData),
                reviewItems,
                importFn,
            },
        });
        // The dialog reports a failed import itself and stays open; a cancel imports nothing.
        return reviewRef.closed.pipe(
            switchMap((closeResult) =>
                closeResult?.action === 'imported' ? of(closeResult.result as ImportResult | null) : EMPTY
            )
        );
    }

    private finishImport({ result, fileData }: CollectionImport): void {
        if (result) {
            this.dialog.open(ImportResultDialogComponent, {
                width: 'calc(100vw - 2rem)',
                height: 'calc(100vh - 2rem)',
                data: { importResult: enrichImportResult(result, fileData) },
            });
            this.importedEntityStorages.invalidateImported(result);
        } else {
            this.toastService.warning(IMPORT_WITHOUT_SUMMARY_MESSAGE);
        }

        // In place: the list stays on screen while it reloads, unlike the first load.
        this.collectionsStorageService
            .getCollections(true)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({ error: () => this.toastService.error('Failed to reload knowledge sources.') });
    }

    private handleDeepLink(): void {
        const params = this.deepLinkService.pending();
        if (!params) return;

        const collection = this.collections().find((c) => c.collection_id === params.collectionId);
        if (!collection) {
            this.toastService.error('Deep link: collection not found');
            this.deepLinkService.consume();
            this.deepLinkService.clearUrl();
            return;
        }

        this.collectionsStorageService.setSelectedCollectionId(params.collectionId);

        this.collectionsStorageService
            .getFullCollection(params.collectionId, true)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (fullCollection) => {
                    if (!fullCollection) {
                        this.toastService.error('Deep link: collection data not found');
                        this.deepLinkService.consume();
                        this.deepLinkService.clearUrl();
                        return;
                    }

                    // Chunk deep links only ever point at naive RAG documents (see
                    // ChunkDeepLinkService) — scope the match to 'naive' explicitly, since
                    // naive and graph rag_id sequences are independent and can collide.
                    const ragConfig = fullCollection.rag_configurations.find(
                        (r) => r.rag_id === params.ragId && r.rag_type === 'naive'
                    );
                    if (!ragConfig) {
                        this.toastService.error('Deep link: RAG configuration not found');
                        this.deepLinkService.consume();
                        this.deepLinkService.clearUrl();
                        return;
                    }

                    this.openDeepLinkDialog(params.collectionId, params.ragId);
                },
                error: () => {
                    this.toastService.error('Deep link: failed to load collection');
                    this.deepLinkService.consume();
                    this.deepLinkService.clearUrl();
                },
            });
    }

    private openDeepLinkDialog(collectionId: number, ragId: number): void {
        this.dialog.open(NaiveRagConfigurationDialog, {
            width: 'calc(100vw - 2rem)',
            height: 'calc(100vh - 2rem)',
            data: { ragId, ragType: 'naive', collectionId },
            disableClose: true,
        });
    }

    createCollection(): void {
        this.collectionsStorageService
            .createCollection()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: ({ collection_id }) => {
                    if (!collection_id) return;
                    this.collectionsStorageService.setSelectedCollectionId(collection_id);
                    this.openCreateModal(collection_id);
                },
                error: () => this.toastService.error('Failed to create collection'),
            });
    }

    private openCreateModal(collection_id: number): void {
        const dialog = this.dialog.open(CreateCollectionDialogComponent, {
            width: 'calc(100vw - 2rem)',
            height: 'calc(100vh - 2rem)',
            data: { collection_id },
            disableClose: true,
        });

        // Update collection info after modal closed
        dialog.closed
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                switchMap(() => {
                    return this.collectionsStorageService.getFullCollection(collection_id, true);
                })
            )
            .subscribe({
                next: () => {
                    this.collectionsStorageService.setSelectedCollectionId(collection_id);
                },
                error: () => {
                    this.toastService.error('Failed to get collection data');
                },
            });
    }
}
