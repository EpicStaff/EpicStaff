import { HttpErrorResponse } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { ConfirmationDialogService } from '@shared/components';
import { DeleteReport } from '@shared/models';
import { catchError, filter, Observable, of, switchMap } from 'rxjs';

import { ToastService } from '../../../services/notifications';
import { buildDeleteImpactMessage, rbacErrorMessage } from '../utils';

export interface HardDeleteOptions {
    title: string;
    caution: string;
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

    run(
        deleteFn: (dryRun: boolean) => Observable<DeleteReport>,
        label: string,
        options: HardDeleteOptions
    ): Observable<boolean> {
        return deleteFn(true).pipe(
            switchMap((report) =>
                this.confirmation.confirm({
                    title: options.title,
                    message: buildDeleteImpactMessage(label, report),
                    caution: options.caution,
                    type: 'danger',
                    confirmText: 'Delete permanently',
                    cancelText: 'Cancel',
                })
            ),
            filter((confirmed) => confirmed === true),
            switchMap(() =>
                deleteFn(false).pipe(
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
