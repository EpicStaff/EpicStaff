import { Dialog } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { buildPreviewImportResult, extractHttpErrorMessage, ImportFileData } from '@shared/utils';
import { catchError, EMPTY, from, map, Observable, of, switchMap } from 'rxjs';

import {
    hasReviewableItems,
    ImportReviewDialogCloseResult,
    InspectResult,
} from '../../../../core/models/review-item.model';
import { ToastService } from '../../../../services/notifications';
import { ImportReviewDialogComponent } from './import-review-dialog.component';

export interface ImportWithReviewConfig {
    entityLabel: string;
    entityLabelPlural: string;
    inspect: (file: File) => Observable<InspectResult>;
    importFile: (file: File) => Observable<unknown>;
}

@Injectable({ providedIn: 'root' })
export class ImportWithReviewService {
    private readonly dialog = inject(Dialog);
    private readonly toastService = inject(ToastService);

    public pickAndImport(config: ImportWithReviewConfig): Observable<unknown> {
        return this.pickJsonFile().pipe(switchMap((file) => this.importFile(file, config)));
    }

    public importFile(file: File, config: ImportWithReviewConfig): Observable<unknown> {
        return from(file.text()).pipe(
            map((text) => this.parseFileData(text)),
            switchMap((fileData) => this.inspectAndImport(file, fileData, config)),
            catchError((err: HttpErrorResponse) => {
                this.toastService.error(extractHttpErrorMessage(err, `Failed to read the ${config.entityLabel} file.`));
                return EMPTY;
            })
        );
    }

    private pickJsonFile(): Observable<File> {
        return new Observable<File>((subscriber) => {
            const input = document.createElement('input');
            input.type = 'file';
            input.accept = '.json, application/json';
            input.onchange = () => {
                const file = input.files?.[0];
                if (file) subscriber.next(file);
                subscriber.complete();
            };
            input.addEventListener('cancel', () => subscriber.complete());
            input.click();
        });
    }

    private parseFileData(text: string): ImportFileData {
        try {
            return JSON.parse(text) as ImportFileData;
        } catch {
            return {};
        }
    }

    private inspectAndImport(
        file: File,
        fileData: ImportFileData,
        config: ImportWithReviewConfig
    ): Observable<unknown> {
        return config.inspect(file).pipe(
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
