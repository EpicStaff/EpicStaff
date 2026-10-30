import { HttpErrorResponse } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { ConfirmationDialogService } from '@shared/components';
import { extractHttpErrorMessage, pluralize } from '@shared/utils';
import { catchError, EMPTY, map, Observable } from 'rxjs';

import { wasHandledByForbiddenInterceptor } from '../../../core/interceptors/forbidden-interceptor-handled.util';
import { ToastService } from '../../../services/notifications';
import { GraphSessionService } from './flows-sessions.service';

const DELETE_FAILED_MESSAGE = 'Failed to delete sessions.';

/** Permanently deletes sessions and tells the user how it went. Sessions have no recycle bin. */
@Injectable({
    providedIn: 'root',
})
export class SessionDeletionService {
    private readonly graphSessionService = inject(GraphSessionService);
    private readonly confirmationDialogService = inject(ConfirmationDialogService);
    private readonly toastService = inject(ToastService);

    /** Asks the user to confirm deleting these sessions. Emits true only when they confirmed. */
    confirmDeletion(ids: number[]): Observable<boolean> {
        const subject = ids.length === 1 ? `Session #${ids[0]}` : pluralize(ids.length, 'session', 'sessions');
        return this.confirmationDialogService
            .confirm({
                title: ids.length === 1 ? `Delete session #${ids[0]}?` : `Delete ${subject}?`,
                message: `${subject} will be permanently deleted. This can't be undone.`,
                confirmText: 'Delete',
                cancelText: 'Cancel',
                type: 'danger',
            })
            .pipe(map((result) => result === true));
    }

    /** Deletes without asking. Emits once after a successful delete; completes without emitting on failure. */
    delete(ids: number[]): Observable<void> {
        return this.graphSessionService.bulkDeleteSessions(ids).pipe(
            map((response) => {
                this.toastService.success(
                    response.deleted === 0
                        ? 'Already deleted.'
                        : `Deleted ${pluralize(response.deleted, 'session', 'sessions')}.`
                );
            }),
            catchError((error: unknown) => {
                this.reportError(error);
                return EMPTY;
            })
        );
    }

    private reportError(error: unknown): void {
        if (wasHandledByForbiddenInterceptor(error)) return;
        const message =
            error instanceof HttpErrorResponse
                ? extractHttpErrorMessage(error, DELETE_FAILED_MESSAGE)
                : DELETE_FAILED_MESSAGE;
        this.toastService.error(message);
    }
}
