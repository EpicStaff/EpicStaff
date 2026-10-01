import { HttpErrorResponse } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { ConfirmationDialogService } from '@shared/components';
import { DeleteReport } from '@shared/models';
import { catchError, filter, Observable, of, switchMap } from 'rxjs';

import { ToastService } from '../../../services/notifications';
import { HardDeleteContent } from '../models/hard-delete-content.model';
import { rbacErrorMessage } from '../utils';

const HARD_DELETE_PHRASE_PREFIX = 'delete-';

export interface HardDeleteOptions {
    title: string;
    /** Organization name or user email the typed confirmation phrase is built from. */
    verificationTarget: string;
    successMessage: string;
    previewErrorFallback: string;
    deleteErrorFallback: string;
}

@Injectable({
    providedIn: 'root',
})
export class HardDeleteFlowService {
    private readonly confirmation = inject(ConfirmationDialogService);
    private readonly toast = inject(ToastService);

    run<Report extends DeleteReport>(
        deleteRequest: (dryRun: boolean, verificationPhrase?: string) => Observable<Report>,
        buildContent: (report: Report) => HardDeleteContent,
        options: HardDeleteOptions
    ): Observable<boolean> {
        const verificationPhrase = `${HARD_DELETE_PHRASE_PREFIX}${options.verificationTarget}`;
        return deleteRequest(true).pipe(
            switchMap((report) =>
                this.confirmation.confirm({
                    ...buildContent(report),
                    title: options.title,
                    type: 'danger',
                    confirmText: 'Delete permanently',
                    cancelText: 'Cancel',
                    verification: { phrase: verificationPhrase },
                })
            ),
            filter((confirmed) => confirmed === true),
            switchMap(() =>
                deleteRequest(false, verificationPhrase).pipe(
                    switchMap(() => {
                        this.toast.success(options.successMessage);
                        return of(true);
                    }),
                    catchError((err: HttpErrorResponse) => {
                        this.toast.error(rbacErrorMessage(err, options.deleteErrorFallback));
                        return of(false);
                    })
                )
            ),
            catchError((err: HttpErrorResponse) => {
                this.toast.error(rbacErrorMessage(err, options.previewErrorFallback));
                return of(false);
            })
        );
    }
}
