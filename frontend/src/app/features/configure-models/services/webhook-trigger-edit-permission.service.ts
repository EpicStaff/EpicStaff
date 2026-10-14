import { HttpErrorResponse, HttpStatusCode } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { ConfirmationDialogService } from '@shared/components';
import { ActionCode, ResourceCode, WebhookTriggerFlowsResponse } from '@shared/models';
import { WebhookTriggerService } from '@shared/services';
import { escapeHtml } from '@shared/utils';
import { catchError, map, Observable, of, tap } from 'rxjs';

import { PermissionsService } from '../../../services/auth/permissions.service';
import { RUN_PERMISSION_REQUIRED_TITLE } from '../../flows/services/flow-run-permission-refusal.service';

/**
 * What a pressed Edit on a webhook trigger leads to: open the edit dialog, nothing (the user has been told why),
 * or nothing because the trigger no longer exists, so the list is out of date.
 */
export type WebhookTriggerEditDecision = 'edit' | 'blocked' | 'gone';

/** How many flow names the warning lists; the rest are counted. */
export const MAX_LISTED_FLOW_NAMES = 5;

/** The decision, plus the usage to explain when the decision is to block because flows use the trigger. */
interface CheckOutcome {
    decision: WebhookTriggerEditDecision;
    usageToExplain?: WebhookTriggerFlowsResponse;
}

/**
 * A 403 has already been explained by `forbiddenInterceptor`, which also reloads the permissions and the page;
 * a 404 means the trigger was deleted. Any other failure (network, 5xx) lets the dialog open: the backend still
 * refuses the save.
 */
function decideAfterFailedCheck(error: unknown): WebhookTriggerEditDecision {
    if (!(error instanceof HttpErrorResponse)) return 'edit';
    if (error.status === HttpStatusCode.Forbidden) return 'blocked';
    if (error.status === HttpStatusCode.NotFound) return 'gone';
    return 'edit';
}

/** Flow names are user-controlled and the dialog renders the message as HTML: names are escaped, numbers are
 *  forced to numbers, so nothing from the server reaches the markup raw. */
function describeUsage({ flow_count: flowCount, flows }: WebhookTriggerFlowsResponse): string {
    const count = Number(flowCount);
    if (flows.length === 0) {
        return `This webhook is part of ${String(count)} ${count === 1 ? 'flow' : 'flows'}.`;
    }
    const listedNames = flows
        .slice(0, MAX_LISTED_FLOW_NAMES)
        .map((flow) => `<strong>${escapeHtml(flow.name)}</strong>`);
    if (count === 1) {
        return `This webhook is part of the flow ${listedNames[0]}.`;
    }
    const unlistedCount = count - listedNames.length;
    const more = unlistedCount > 0 ? ` and ${String(unlistedCount)} more` : '';
    return `This webhook is part of ${String(count)} flows: ${listedNames.join(', ')}${more}.`;
}

/**
 * Decides what a pressed Edit on a webhook trigger does. The backend refuses to save a trigger that flows' trigger
 * nodes use for a user without FLOWS:RUN, so such a user is told why up front, in an OK-only warning, instead of
 * after filling in the form.
 */
@Injectable({
    providedIn: 'root',
})
export class WebhookTriggerEditPermissionService {
    private readonly permissions = inject(PermissionsService);
    private readonly webhookTriggers = inject(WebhookTriggerService);
    private readonly confirmationDialog = inject(ConfirmationDialogService);

    /** Emits once. Permissions are read on every call, so a permission granted since the last press counts. */
    decideEdit(triggerId: number): Observable<WebhookTriggerEditDecision> {
        if (this.permissions.can(ResourceCode.Flows, ActionCode.Run)) {
            return of('edit');
        }
        return this.webhookTriggers.getFlows(triggerId).pipe(
            map(
                (usage): CheckOutcome =>
                    usage.flow_count === 0 ? { decision: 'edit' } : { decision: 'blocked', usageToExplain: usage }
            ),
            // Only the request and the pure mapping above are covered: an error while showing the warning is not
            // turned into a decision.
            catchError((error: unknown) => of<CheckOutcome>({ decision: decideAfterFailedCheck(error) })),
            tap((outcome) => {
                if (outcome.usageToExplain) this.showInUse(outcome.usageToExplain);
            }),
            map((outcome) => outcome.decision)
        );
    }

    private showInUse(usage: WebhookTriggerFlowsResponse): void {
        // The dialog opens on the call; the result (always a close) needs no subscriber.
        this.confirmationDialog.confirm({
            title: RUN_PERMISSION_REQUIRED_TITLE,
            message: describeUsage(usage),
            caution:
                "You can't <strong>edit</strong> it because you don't have the <strong>Run</strong> permission on flows.",
            type: 'warning',
            hideConfirm: true,
            cancelText: 'OK',
        });
    }
}
