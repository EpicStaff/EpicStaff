import type { BridgeErrorCode } from './protocol.js';

/**
 * Why a bridge call failed. EpicStaff's own codes, plus three the client raises itself:
 * `timeout` (no answer in time), `closed` (the connection was closed before the answer) and
 * `aborted` (the caller's `AbortSignal` fired).
 */
export type BridgeCallErrorCode = BridgeErrorCode | 'timeout' | 'closed' | 'aborted';

/** A failed bridge call or handshake. Branch on `code`, not on `message`. */
export class BridgeCallError extends Error {
    readonly code: BridgeCallErrorCode;
    /** The method that failed; `null` for the handshake. */
    readonly method: string | null;

    constructor(code: BridgeCallErrorCode, message: string, method: string | null = null) {
        super(message);
        this.name = 'BridgeCallError';
        this.code = code;
        this.method = method;
    }
}

/**
 * Why `flows.runAndWait` gave up on a session that did start:
 * - `failed`: the session ended with a failed status (`error`, `stop`, `expired`);
 * - `no_output`: the session ended without an End node result;
 * - `disconnected`: EpicStaff lost the session's stream;
 * - `timeout`: the session did not finish within `timeoutMs`;
 * - `aborted`: the caller's `AbortSignal` fired.
 */
export type FlowRunFailure = 'failed' | 'no_output' | 'disconnected' | 'timeout' | 'aborted';

/** A flow run that started but did not produce an output. Bridge failures stay {@link BridgeCallError}. */
export class FlowRunError extends Error {
    readonly reason: FlowRunFailure;
    readonly sessionId: number;
    /** The last status EpicStaff reported for the session, if any. */
    readonly status: string | null;

    constructor(reason: FlowRunFailure, message: string, sessionId: number, status: string | null) {
        super(message);
        this.name = 'FlowRunError';
        this.reason = reason;
        this.sessionId = sessionId;
        this.status = status;
    }
}
