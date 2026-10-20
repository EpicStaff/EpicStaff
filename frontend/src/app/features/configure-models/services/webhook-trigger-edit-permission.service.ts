import { HttpErrorResponse, HttpStatusCode } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { ActionCode, ResourceCode } from '@shared/models';
import { WebhookTriggerService } from '@shared/services';
import { catchError, map, Observable, of } from 'rxjs';

import { PermissionsService } from '../../../services/auth/permissions.service';

/**
 * What a pressed Edit on a webhook trigger leads to: open the edit dialog; open it read-only; nothing, because the
 * trigger no longer exists, so the list is out of date; or nothing, because the refusal was already explained.
 */
export type WebhookTriggerEditDecision = 'edit' | 'view' | 'gone' | 'explained';

/**
 * A 403 has already been explained by `forbiddenInterceptor`, which also reloads the permissions and the page;
 * a 404 means the trigger was deleted. Any other failure (network, 5xx) lets the dialog open: the backend still
 * refuses the save.
 */
function decideAfterFailedCheck(error: unknown): WebhookTriggerEditDecision {
    if (!(error instanceof HttpErrorResponse)) return 'edit';
    if (error.status === HttpStatusCode.Forbidden) return 'explained';
    if (error.status === HttpStatusCode.NotFound) return 'gone';
    return 'edit';
}

/**
 * Decides what a pressed Edit on a webhook trigger does. The backend refuses to save a trigger that flows' trigger
 * nodes use for a user without Flows:Use, so such a user gets the dialog read-only, with the reason shown in it,
 * instead of a form whose save would fail.
 */
@Injectable({
    providedIn: 'root',
})
export class WebhookTriggerEditPermissionService {
    private readonly permissions = inject(PermissionsService);
    private readonly webhookTriggers = inject(WebhookTriggerService);

    /** Emits once. Permissions are read on every call, so a permission granted since the last press counts. */
    decideEdit(triggerId: number): Observable<WebhookTriggerEditDecision> {
        if (this.permissions.can(ResourceCode.Flows, ActionCode.Use)) {
            return of('edit');
        }
        return this.webhookTriggers.getFlows(triggerId).pipe(
            map((usage): WebhookTriggerEditDecision => (usage.flow_count === 0 ? 'edit' : 'view')),
            catchError((error: unknown) => of(decideAfterFailedCheck(error)))
        );
    }
}
