import { HttpErrorResponse } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { ConfirmationDialogService } from '@shared/components';
import { EMPTY, MonoTypeOperatorFunction, throwError } from 'rxjs';
import { catchError } from 'rxjs/operators';

/** The 403 the backend sends when a copy, import, partial import, version restore or new flow from a version
 *  would bring in trigger nodes (Webhook, Telegram, Schedule) for a user without Flows:Use; nothing is created. */
export const FLOW_WITH_TRIGGER_NODES_REQUIRES_USE_PERMISSION = 'flow_with_trigger_nodes_requires_use_permission';

export const USE_PERMISSION_REQUIRED_TITLE = 'Use permission required';

/** An operation refused for a user without Flows:Use when what it brings in contains trigger nodes. */
export type UsePermissionRefusalOperation =
    | 'copy'
    | 'import'
    | 'partialImport'
    | 'restore'
    | 'createFromVersion'
    | 'unpack';

/** What holds the trigger nodes, and the operation as the subject of "… requires the Use permission". */
const REFUSAL_COPY: Record<UsePermissionRefusalOperation, { source: string; action: string }> = {
    copy: { source: 'This flow', action: '<strong>Copying</strong> it' },
    import: { source: 'This file', action: '<strong>Importing</strong> it' },
    partialImport: { source: 'This file', action: '<strong>Importing</strong> it' },
    restore: { source: 'This version', action: '<strong>Restoring</strong> it' },
    createFromVersion: { source: 'This version', action: '<strong>Creating a flow</strong> from it' },
    unpack: { source: 'This subflow', action: '<strong>Unpacking</strong> it' },
};

function isUsePermissionRefusal(error: unknown): error is HttpErrorResponse {
    return (
        error instanceof HttpErrorResponse &&
        error.status === 403 &&
        (error.error as { code?: unknown } | null)?.code === FLOW_WITH_TRIGGER_NODES_REQUIRES_USE_PERMISSION
    );
}

/**
 * Handles the refusal of an operation that would bring trigger nodes into a flow for a user without
 * Flows:Use: says why in an OK-only warning dialog. `catchRefusal` does so for the backend's refusal and
 * completes without emitting, so the caller's success and error handling both stay silent; any other error
 * passes through unchanged. The text is the frontend's own, per operation.
 */
@Injectable({
    providedIn: 'root',
})
export class FlowUsePermissionRefusalService {
    private readonly confirmationDialog = inject(ConfirmationDialogService);

    catchRefusal<T>(operation: UsePermissionRefusalOperation): MonoTypeOperatorFunction<T> {
        return catchError((error: unknown) => {
            if (!isUsePermissionRefusal(error)) {
                return throwError(() => error);
            }
            this.showRefusal(operation);
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
}
