import { Dialog } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import {
    buildPreviewImportResult,
    exportEnvelopeFile,
    extractHttpErrorMessage,
    ImportFileData,
    readExportEnvelope,
} from '@shared/utils';
import { catchError, EMPTY, from, Observable, of, switchMap } from 'rxjs';

import {
    hasReviewableItems,
    ImportReviewDialogCloseResult,
    InspectResult,
} from '../../../../core/models/review-item.model';
import { describeTransferError } from '../../../../core/services/transfer-jobs.service';
import { ToastService } from '../../../../services/notifications';
import { ImportReviewDialogComponent } from './import-review-dialog.component';

export interface ImportWithReviewConfig {
    entityLabel: string;
    entityLabelPlural: string;
    inspect: (file: File) => Observable<InspectResult>;
    importFile: (file: File) => Observable<unknown>;
    /** The file picker's `accept`; a plain `.json` export when left out. Add `.zip` where the import takes archives. */
    accept?: string;
}

const JSON_EXPORT_ACCEPT = '.json,application/json';

@Injectable({ providedIn: 'root' })
export class ImportWithReviewService {
    private readonly dialog = inject(Dialog);
    private readonly toastService = inject(ToastService);

    public pickAndImport(config: ImportWithReviewConfig): Observable<unknown> {
        return this.pickFile(config.accept ?? JSON_EXPORT_ACCEPT).pipe(
            switchMap((file) => this.importFile(file, config))
        );
    }

    public importFile(file: File, config: ImportWithReviewConfig): Observable<unknown> {
        return from(readExportEnvelope(file)).pipe(
            switchMap(({ data }) => this.inspectAndImport(file, data, config)),
            catchError((error: unknown) => {
                this.toastService.error(describeTransferError(error, `Failed to read the ${config.entityLabel} file.`));
                return EMPTY;
            })
        );
    }

    private pickFile(accept: string): Observable<File> {
        return new Observable<File>((subscriber) => {
            const input = document.createElement('input');
            input.type = 'file';
            input.accept = accept;
            input.onchange = () => {
                const file = input.files?.[0];
                if (file) subscriber.next(file);
                subscriber.complete();
            };
            input.addEventListener('cancel', () => subscriber.complete());
            input.click();
        });
    }

    private inspectAndImport(
        file: File,
        fileData: ImportFileData,
        config: ImportWithReviewConfig
    ): Observable<unknown> {
        // Only the envelope is inspected, so an archive's files stay on the user's machine; the import takes the
        // file the user chose, a `.zip` archive or a plain `.json` export.
        return config.inspect(exportEnvelopeFile(fileData)).pipe(
            switchMap((inspection) => {
                if (!hasReviewableItems(inspection.review_items)) {
                    return config.importFile(file).pipe(
                        catchError((err: HttpErrorResponse) => {
                            this.toastService.error(
                                extractHttpErrorMessage(err, `Failed to import ${config.entityLabelPlural}.`)
                            );
                            return EMPTY;
                        })
                    );
                }

                const dialogRef = this.dialog.open<ImportReviewDialogCloseResult>(ImportReviewDialogComponent, {
                    width: 'calc(100vw - 2rem)',
                    height: 'calc(100vh - 2rem)',
                    autoFocus: false,
                    data: {
                        importResult: buildPreviewImportResult(fileData),
                        reviewItems: inspection.review_items,
                        importFn: () => config.importFile(file),
                    },
                });

                return dialogRef.closed.pipe(
                    switchMap((closeResult) => (closeResult?.action === 'imported' ? of(closeResult.result) : EMPTY))
                );
            })
        );
    }
}
