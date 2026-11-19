import { Dialog } from '@angular/cdk/dialog';
import { Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ButtonComponent } from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import { ImportedEntityStoragesService } from '@shared/services';
import {
    buildPreviewImportResult,
    enrichImportResult,
    exportEnvelopeFile,
    ImportFileData,
    readExportEnvelope,
} from '@shared/utils';
import { EMPTY, from, Observable, of, throwError } from 'rxjs';
import { catchError, finalize, map, switchMap, tap } from 'rxjs/operators';

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
    TransferJobsService,
} from '../../../../core/services/transfer-jobs.service';
import { ToastService } from '../../../../services/notifications';
import { ImportResultDialogComponent } from '../../../flows/components/import-result-dialog/import-result-dialog.component';
import { ImportReviewDialogComponent } from '../../../flows/components/import-review-dialog/import-review-dialog.component';
import { CollectionsApiService } from '../../services/collections-api.service';
import { CollectionsStorageService } from '../../services/collections-storage.service';

/** Collections carry their files, which only an export archive holds. */
const ARCHIVE_REQUIRED_MESSAGE = 'Knowledge sources are imported from a .zip export. Choose a .zip file.';
const IMPORT_FAILED_MESSAGE = 'Failed to import knowledge sources. Please check the file and try again.';

interface CollectionImport {
    /** `null` when the server reported no summary. */
    result: ImportResult | null;
    fileData: ImportFileData;
}

/**
 * The Import button of Knowledge Sources, in the page header, and the import it starts: picks an export archive,
 * has its code reviewed when it carries any, imports it and shows what came in. Leaving the tab stops waiting for
 * the import's job; the job itself runs on.
 */
@Component({
    selector: 'app-collections-import',
    imports: [ButtonComponent, HasPermissionDirective],
    templateUrl: './collections-import.component.html',
})
export class CollectionsImportComponent {
    /**
     * From the pick of a file until the server has accepted its import, it fails, or the review dialog opens with
     * its own progress: Import is disabled meanwhile, so a second click starts no second upload.
     */
    protected readonly isImporting = signal(false);

    protected readonly ActionCode = ActionCode;
    protected readonly ResourceCode = ResourceCode;

    private readonly destroyRef = inject(DestroyRef);
    private readonly dialog = inject(Dialog);
    private readonly toastService = inject(ToastService);
    private readonly collectionsApiService = inject(CollectionsApiService);
    private readonly collectionsStorageService = inject(CollectionsStorageService);
    private readonly transferJobs = inject(TransferJobsService);
    private readonly importedEntityStorages = inject(ImportedEntityStoragesService);

    importCollections(): void {
        if (this.isImporting()) return;

        const input = document.createElement('input');
        input.type = 'file';
        input.accept = '.zip';
        input.onchange = (event: Event) => {
            const file = (event.target as HTMLInputElement).files?.[0];
            if (!file) return;

            const endImporting = this.startImporting();
            from(readExportEnvelope(file))
                .pipe(
                    switchMap(({ format, data }) =>
                        format === 'zip'
                            ? this.importArchive(file, data, endImporting)
                            : throwError(() => new Error(ARCHIVE_REQUIRED_MESSAGE))
                    ),
                    catchError((error: unknown) => {
                        this.toastService.error(describeTransferError(error, IMPORT_FAILED_MESSAGE));
                        return EMPTY;
                    }),
                    finalize(endImporting),
                    takeUntilDestroyed(this.destroyRef)
                )
                .subscribe((collectionImport) => this.finishImport(collectionImport));
        };
        input.click();
    }

    /**
     * Inspects the archive's envelope, never its files, and imports the archive straight away or after the user has
     * reviewed the code it carries. The import runs as a job: `endImporting` is called once the server has accepted
     * it, which TransferJobsStoreService announces, or once the review dialog, which shows its own progress, opens.
     */
    private importArchive(
        file: File,
        fileData: ImportFileData,
        endImporting: () => void
    ): Observable<CollectionImport> {
        const importFn = (): Observable<ImportResult | null> =>
            this.transferJobs.startImport('collections', file).pipe(
                tap(endImporting),
                switchMap((started) => this.transferJobs.waitForImport(started))
            );
        return this.collectionsApiService.inspect(exportEnvelopeFile(fileData)).pipe(
            switchMap(
                (inspection): Observable<InspectedImport> =>
                    hasReviewableItems(inspection.review_items)
                        ? of({ kind: 'review', reviewItems: inspection.review_items })
                        : importFn().pipe(map((result): InspectedImport => ({ kind: 'imported', result })))
            ),
            switchMap((inspected) => {
                if (inspected.kind === 'imported') return of(inspected.result);
                endImporting();
                return this.reviewAndImport(inspected.reviewItems, fileData, importFn);
            }),
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

    /**
     * Marks an import in flight and returns what ends it. Ending it twice is harmless: a job's end, long after its
     * start was accepted, must not end a later import's busy state.
     */
    private startImporting(): () => void {
        this.isImporting.set(true);
        let ended = false;
        return () => {
            if (ended) return;
            ended = true;
            this.isImporting.set(false);
        };
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
}
