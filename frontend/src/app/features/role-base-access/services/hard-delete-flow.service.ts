import { HttpErrorResponse } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { ConfirmationDialogService } from '@shared/components';
import { DeleteReport } from '@shared/models';
import { catchError, filter, Observable, of, switchMap } from 'rxjs';

import { ToastService } from '../../../services/notifications';
import { HardDeleteContent } from '../models/hard-delete-content.model';
import { rbacErrorMessage } from '../utils';

export interface HardDeleteOptions {
    title: string;
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
        deleteRequest: (dryRun: boolean) => Observable<Report>,
        buildContent: (report: Report) => HardDeleteContent,
        options: HardDeleteOptions
    ): Observable<boolean> {
        return deleteRequest(true).pipe(
            switchMap((report) =>
                this.confirmation.confirm({
                    ...buildContent(report),
                    title: options.title,
                    type: 'danger',
                    confirmText: 'Delete permanently',
                    cancelText: 'Cancel',
                })
            ),
            filter((confirmed) => confirmed === true),
            switchMap(() =>
                deleteRequest(false).pipe(
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
