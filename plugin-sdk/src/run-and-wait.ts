import type { BridgeConnection } from './connection.js';
import { BridgeCallError, FlowRunError } from './errors.js';
import {
    type BridgeEvents,
    FAILED_SESSION_STATUSES,
    type FlowsRunResult,
    isRecord,
    type SessionMessageData,
    type SubscribeResult,
} from './protocol.js';
import { notify } from './report-error.js';

export interface RunAndWaitOptions {
    /** Give up after this long (the session keeps running in EpicStaff). Default 300 000 ms. */
    timeoutMs?: number;
    /** Stop waiting when aborted (the session keeps running in EpicStaff). */
    signal?: AbortSignal;
    /** Called once the session started, e.g. to offer a Stop button (`sessions.stop`). */
    onSession?: (sessionId: number) => void;
    /** Every `session.message` of the run, for progress display. */
    onMessage?: (message: SessionMessageData) => void;
    /** Every `session.status` of the run. */
    onStatus?: (status: string) => void;
}

export const DEFAULT_RUN_TIMEOUT_MS = 300_000;

type SessionTopic = 'session.message' | 'session.status' | 'subscription.closed';

interface BufferedEvent {
    topic: SessionTopic;
    data: unknown;
    subscription: string | null;
}

/**
 * `flows.run` → `sessions.subscribe` → resolves with the End node's output (`end_node_result` of
 * the `graph_end` message). Rejects with {@link FlowRunError} on a failed status (`error`, `stop`,
 * `expired`), when the subscription closes without an output, on timeout or abort; a failing
 * bridge call rejects with its `BridgeCallError`, and closing the bridge rejects at once with
 * `closed`. Unsubscribes when done.
 *
 * The callbacks never change the outcome: it is decided first, then they are called, and a
 * callback that throws is reported (`reportError`) instead of propagating.
 */
export async function runAndWait<Output = unknown>(
    connection: BridgeConnection,
    flow: string,
    variables: Record<string, unknown>,
    options: RunAndWaitOptions = {}
): Promise<Output> {
    const { session_id: sessionId } = (await connection.call(
        'flows.run',
        { flow, variables },
        signalOnly(options)
    )) as FlowsRunResult;
    notify(options.onSession, sessionId);

    return new Promise<Output>((resolve, reject) => {
        let subscription: string | null = null;
        let lastStatus: string | null = null;
        let settled = false;
        let closedByHost = false;
        const early: BufferedEvent[] = [];

        const route = (topic: SessionTopic) => (data: BridgeEvents[SessionTopic], from: string | null) => {
            if (settled) return;
            if (subscription === null) early.push({ topic, data, subscription: from });
            else if (from === subscription) handle(topic, data);
        };
        const unsubscribers = [
            connection.on('session.message', route('session.message')),
            connection.on('session.status', route('session.status')),
            connection.on('subscription.closed', route('subscription.closed')),
        ];
        const timeoutMs = options.timeoutMs ?? DEFAULT_RUN_TIMEOUT_MS;
        const timer = setTimeout(() => fail('timeout', `The flow did not finish within ${timeoutMs} ms.`), timeoutMs);
        const onAbort = (): void => fail('aborted', 'Stopped waiting for the flow.');
        options.signal?.addEventListener('abort', onAbort, { once: true });
        const removeCloseListener = connection.onClose(() =>
            finish(() => reject(new BridgeCallError('closed', 'The bridge connection is closed.', 'flows.runAndWait')))
        );
        if (options.signal?.aborted) onAbort();

        function handle(topic: SessionTopic, data: unknown): void {
            if (topic === 'session.message') {
                const message = data as SessionMessageData;
                if (message.message_type === 'graph_end') {
                    const messageData = message.message_data;
                    finish(() =>
                        resolve((isRecord(messageData) ? messageData['end_node_result'] : undefined) as Output)
                    );
                }
                notify(options.onMessage, message);
            } else if (topic === 'session.status') {
                const status = isRecord(data) && typeof data['status'] === 'string' ? data['status'] : null;
                if (status === null) return;
                lastStatus = status;
                if (FAILED_SESSION_STATUSES.has(status)) fail('failed', `The flow ended with status "${status}".`);
                notify(options.onStatus, status);
            } else {
                closedByHost = true;
                const reason = isRecord(data) ? data['reason'] : null;
                if (reason === 'error') fail('disconnected', 'EpicStaff lost the connection to the flow.');
                else fail('no_output', 'The flow finished without an output.');
            }
        }

        function fail(reason: FlowRunError['reason'], message: string): void {
            finish(() => reject(new FlowRunError(reason, message, sessionId, lastStatus)));
        }

        function finish(settle: () => void): void {
            if (settled) return;
            settled = true;
            clearTimeout(timer);
            options.signal?.removeEventListener('abort', onAbort);
            removeCloseListener();
            unsubscribers.forEach((unsubscribe) => unsubscribe());
            if (subscription !== null && !closedByHost && !connection.isClosed) release(subscription);
            settle();
        }

        function release(id: string): void {
            connection.call('sessions.unsubscribe', { subscription: id }).catch(() => undefined);
        }

        if (settled) return;
        connection.call('sessions.subscribe', { session_id: sessionId }).then(
            (result) => {
                const id = (result as SubscribeResult).subscription;
                if (settled) {
                    release(id);
                    return;
                }
                subscription = id;
                for (const event of early.splice(0)) {
                    if (settled) break;
                    if (event.subscription === id) handle(event.topic, event.data);
                }
            },
            (error: unknown) => finish(() => reject(error))
        );
    });
}

function signalOnly(options: RunAndWaitOptions): { signal?: AbortSignal } {
    return options.signal ? { signal: options.signal } : {};
}
