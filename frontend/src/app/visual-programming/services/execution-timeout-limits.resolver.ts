import { inject } from '@angular/core';
import { RedirectCommand, ResolveFn, Router } from '@angular/router';
import { catchError, Observable, of } from 'rxjs';

import { ToastService } from '../../services/notifications';
import { ExecutionTimeoutLimits } from '../core/models/execution-timeout-limits.model';
import { ExecutionTimeoutLimitsStorageService } from './execution-timeout-limits-storage.service';

/**
 * Loads the execution timeout limits before the flow editor opens: the timeout fields of the node panels show
 * and validate against them. Without them the editor cannot work, so a failed load goes back to the flow list.
 */
export const executionTimeoutLimitsResolver: ResolveFn<ExecutionTimeoutLimits | RedirectCommand> = (): Observable<
    ExecutionTimeoutLimits | RedirectCommand
> => {
    const router = inject(Router);
    const toastService = inject(ToastService);
    return inject(ExecutionTimeoutLimitsStorageService)
        .load()
        .pipe(
            catchError(() => {
                toastService.error('Could not load the execution timeout limits, so the flow cannot be opened.');
                return of(new RedirectCommand(router.parseUrl('/flows')));
            })
        );
};
