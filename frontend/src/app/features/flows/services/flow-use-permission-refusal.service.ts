import { HttpErrorResponse } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { ConfirmationDialogService } from '@shared/components';
import { EMPTY, MonoTypeOperatorFunction, throwError } from 'rxjs';
import { catchError } from 'rxjs/operators';

/** The 403 the backend sends when a copy, import, partial import, version restore or new flow from a version
 *  would bring in trigger nodes (Webhook, Telegram, Schedule) for a user without Flows:Use; nothing is created. */
export const FLOW_WITH_TRIGGER_NODES_REQUIRES_USE_PERMISSION = 'flow_with_trigger_nodes_requires_use_permission';

/** The 403 the backend sends when a copy, version restore or new flow from a version would bring in Python code
 *  that reads secrets for a user without Secrets:Use; nothing is created. The trigger node refusal wins when both apply. */
export const CODE_WITH_SECRETS_REQUIRES_SECRETS_USE_PERMISSION = 'code_with_secrets_requires_secrets_use_permission';

export const USE_PERMISSION_REQUIRED_TITLE = 'Use permission required';

/** An operation refused when what it brings in contains trigger nodes (without Flows:Use) or code that reads
 *  secrets (without Secrets:Use). */
export type UsePermissionRefusalOperation =
    | 'copy'
    | 'import'
    | 'partialImport'
    | 'restore'
    | 'createFromVersion'
    | 'unpack';

/** An action on the open flow that needs Flows:Use itself, whatever the flow contains. */
export type UsePermissionAction = 'run' | 'getCurl' | 'stopSession';

/** What holds the refused content, and the operation as the subject of "… requires the Use permission". */
const REFUSAL_COPY: Record<UsePermissionRefusalOperation, { source: string; action: string }> = {
    copy: { source: 'This flow', action: '<strong>Copying</strong> it' },
    import: { source: 'This file', action: '<strong>Importing</strong> it' },
    partialImport: { source: 'This file', action: '<strong>Importing</strong> it' },
    restore: { source: 'This version', action: '<strong>Restoring</strong> it' },
    createFromVersion: { source: 'This version', action: '<strong>Creating a flow</strong> from it' },
    unpack: { source: 'This subflow', action: '<strong>Unpacking</strong> it' },
};

/** The action as the subject of "… requires the Use permission". */
const ACTION_REFUSAL_COPY: Record<UsePermissionAction, string> = {
    run: '<strong>Running</strong> this flow',
    getCurl: '<strong>Getting the cURL command</strong> for this flow',
    stopSession: '<strong>Stopping</strong> a session of this flow',
};

/** The refusal code of a 403 that refuses bringing something in, else null. */
function refusalCode(error: unknown): string | null {
    if (!(error instanceof HttpErrorResponse) || error.status !== 403) return null;
    const code = (error.error as { code?: unknown } | null)?.code;
    return code === FLOW_WITH_TRIGGER_NODES_REQUIRES_USE_PERMISSION ||
        code === CODE_WITH_SECRETS_REQUIRES_SECRETS_USE_PERMISSION
        ? code
        : null;
}

/**
 * Handles the refusal of an operation that would bring trigger nodes into a flow for a user without
 * Flows:Use, or code that reads secrets for a user without Secrets:Use, and of an action that needs Flows:Use
 * itself (`showActionRefusal`): says why in an OK-only warning dialog. `catchRefusal` does so for the backend's
 * refusal and completes without emitting, so the caller's success and error handling both stay silent; any other
 * error passes through unchanged. The text is the frontend's own, per operation.
 */
@Injectable({
    providedIn: 'root',
})
export class FlowUsePermissionRefusalService {
    private readonly confirmationDialog = inject(ConfirmationDialogService);

    catchRefusal<T>(operation: UsePermissionRefusalOperation): MonoTypeOperatorFunction<T> {
        return catchError((error: unknown) => {
            const code = refusalCode(error);
            if (code === null) {
                return throwError(() => error);
            }
            if (code === CODE_WITH_SECRETS_REQUIRES_SECRETS_USE_PERMISSION) {
                this.showSecretsRefusal(operation);
            } else {
                this.showRefusal(operation);
            }
            return EMPTY;
        });
    }

    /** Says, OK-only, why the operation needs Flows:Use; also for refusals the frontend decides itself. */
    showRefusal(operation: UsePermissionRefusalOperation): void {
        const { source, action } = REFUSAL_COPY[operation];
        // Static text only, so the markup the dialog renders as HTML needs no escaping.
        // The dialog opens on the call; the result (always a close) needs no subscriber.
        this.confirmationDialog.confirm({
            title: USE_PERMISSION_REQUIRED_TITLE,
            message: `${source} contains trigger nodes (Webhook, Telegram, Schedule).`,
            caution: `${action} requires the <strong>Use</strong> permission on flows.`,
            type: 'warning',
            hideConfirm: true,
            cancelText: 'OK',
        });
    }

    /** Says, OK-only, why the operation needs Secrets:Use; also for refusals the frontend decides itself. */
    showSecretsRefusal(operation: UsePermissionRefusalOperation): void {
        const { source, action } = REFUSAL_COPY[operation];
        // Static text only, as in `showRefusal`.
        this.confirmationDialog.confirm({
            title: USE_PERMISSION_REQUIRED_TITLE,
            message: `${source} contains code that reads secrets.`,
            caution: `${action} requires the <strong>Use</strong> permission on secrets.`,
            type: 'warning',
            hideConfirm: true,
            cancelText: 'OK',
        });
    }

    /** Says, OK-only, that the action needs Flows:Use; for an action the user reached without its button. */
    showActionRefusal(action: UsePermissionAction): void {
        // Static text only, as in `showRefusal`.
        this.confirmationDialog.confirm({
            title: USE_PERMISSION_REQUIRED_TITLE,
            message: `${ACTION_REFUSAL_COPY[action]} requires the <strong>Use</strong> permission on flows.`,
            type: 'warning',
            hideConfirm: true,
            cancelText: 'OK',
        });
    }
}
