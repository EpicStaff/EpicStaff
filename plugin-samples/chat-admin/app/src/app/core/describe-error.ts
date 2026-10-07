import { BridgeCallError, FlowRunError } from '@epicstaff/plugin-sdk';

/** A sentence for the user, from any failure of a bridge call or a flow run. */
export function describeError(error: unknown): string {
    if (error instanceof FlowRunError) {
        switch (error.reason) {
            case 'failed':
                return `The assistant stopped before answering (${error.status ?? 'failed'}).`;
            case 'no_output':
                return 'The assistant finished without an answer.';
            case 'disconnected':
                return 'Lost the connection to the assistant. Please ask again.';
            case 'timeout':
                return 'The assistant took too long to answer.';
            case 'aborted':
                return 'Stopped waiting for the answer.';
        }
    }
    if (error instanceof BridgeCallError) {
        switch (error.code) {
            case 'forbidden':
                return 'You are not allowed to do this, or the plugin is suspended.';
            case 'not_found':
                return 'Not found.';
            case 'rate_limited':
                return 'Too many requests at once. Wait a moment and try again.';
            case 'timeout':
                return 'EpicStaff did not answer in time.';
            case 'closed':
                return 'The connection to EpicStaff was closed. Reload the page.';
            default:
                return error.message;
        }
    }
    return error instanceof Error ? error.message : 'Something went wrong.';
}

export function isNotFound(error: unknown): boolean {
    return error instanceof BridgeCallError && error.code === 'not_found';
}
