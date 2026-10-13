import { inject } from '@angular/core';
import { RedirectCommand, ResolveFn, Router } from '@angular/router';
import { catchError, Observable, of } from 'rxjs';

import { ToastService } from '../../services/notifications';
import { GetSandboxLimitsResponse } from '../core/models/sandbox-limits.model';
import { SandboxLimitsStorageService } from './sandbox-limits-storage.service';

export const SANDBOX_LIMITS_LOAD_FAILED_MESSAGE = 'Could not load the sandbox limits, so the flow cannot be opened.';

/**
 * Loads the sandbox limits before the flow editor opens: node panels validate execution timeouts against
 * them and new nodes take their default from them. Without them the editor cannot work, so a failed load
 * goes back to the flow list.
 */
export const sandboxLimitsResolver: ResolveFn<GetSandboxLimitsResponse | RedirectCommand> = (): Observable<
    GetSandboxLimitsResponse | RedirectCommand
> => {
    const router = inject(Router);
    const toastService = inject(ToastService);
    return inject(SandboxLimitsStorageService)
        .load()
        .pipe(
            catchError(() => {
                toastService.error(SANDBOX_LIMITS_LOAD_FAILED_MESSAGE);
                return of(new RedirectCommand(router.parseUrl('/flows')));
            })
        );
};
