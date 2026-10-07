import { BridgeCallError } from './errors.js';
import {
    BRIDGE_LIMITS,
    BRIDGE_VERSION,
    type BridgeEvents,
    type EventTopic,
    isBridgeErrorCode,
    isRecord,
    type RequestMessage,
} from './protocol.js';
import { reportCallbackError } from './report-error.js';

/**
 * How long a request the caller gave up on (timeout or abort) keeps its in-flight slot when no
 * late answer arrives. EpicStaff counts a request until its own HTTP call finishes, so freeing
 * the slot at once would let the next calls hit `rate_limited`; this only guards against an
 * answer that never comes.
 */
export const ABANDONED_REQUEST_RELEASE_MS = 120_000;

/** Receives one event; `subscription` is the session subscription id, or `null` for host-pushed topics. */
export type EventHandler<Topic extends EventTopic> = (data: BridgeEvents[Topic], subscription: string | null) => void;

export interface CallOptions {
    /** Overrides the connection's default request timeout. */
    timeoutMs?: number;
    /** Rejects the call (with `aborted`) when aborted; a request already sent still runs in EpicStaff. */
    signal?: AbortSignal;
}

interface PendingCall {
    readonly method: string;
    readonly resolve: (result: unknown) => void;
    readonly reject: (error: BridgeCallError) => void;
    readonly message: RequestMessage;
    sent: boolean;
    cleanup: () => void;
}

/**
 * One open bridge port: request ids, per-call timeouts, event dispatch.
 *
 * Calls beyond EpicStaff's in-flight cap wait here instead of failing with `rate_limited`, and a
 * request over the size cap fails locally with `bad_request` without being sent. A sent request
 * the caller gave up on stays counted until EpicStaff answers it (the answer is then dropped),
 * because EpicStaff keeps counting it too.
 */
export class BridgeConnection {
    private readonly pending = new Map<number, PendingCall>();
    private readonly waiting: PendingCall[] = [];
    /** Sent requests the caller gave up on, still counted in flight, with their safety release timer. */
    private readonly abandoned = new Map<number, ReturnType<typeof setTimeout>>();
    private readonly handlers = new Map<EventTopic, Set<EventHandler<EventTopic>>>();
    private readonly closeListeners = new Set<() => void>();
    private readonly encoder = new TextEncoder();
    private nextId = 1;
    private inFlight = 0;
    private closed = false;

    constructor(
        private readonly port: MessagePort,
        private readonly defaultTimeoutMs: number,
        private readonly abandonedReleaseMs: number = ABANDONED_REQUEST_RELEASE_MS
    ) {
        port.onmessage = (event: MessageEvent) => this.handleMessage(event.data);
    }

    /** Requests waiting for an answer, including abandoned ones EpicStaff still counts. */
    get inFlightCount(): number {
        return this.inFlight;
    }

    get isClosed(): boolean {
        return this.closed;
    }

    call(method: string, params: Record<string, unknown> = {}, options: CallOptions = {}): Promise<unknown> {
        if (this.closed) {
            return Promise.reject(new BridgeCallError('closed', 'The bridge connection is closed.', method));
        }
        const id = this.nextId++;
        const message: RequestMessage = { v: BRIDGE_VERSION, kind: 'request', id, method, params };
        const sizeProblem = this.sizeProblem(message);
        if (sizeProblem !== null) {
            return Promise.reject(new BridgeCallError('bad_request', sizeProblem, method));
        }

        if (options.signal?.aborted) {
            return Promise.reject(new BridgeCallError('aborted', `${method} was aborted.`, method));
        }

        return new Promise<unknown>((resolve, reject) => {
            const call: PendingCall = { method, resolve, reject, message, sent: false, cleanup: () => undefined };
            this.pending.set(id, call);
            const timeoutMs = options.timeoutMs ?? this.defaultTimeoutMs;
            const timer = setTimeout(
                () =>
                    this.fail(
                        id,
                        call,
                        new BridgeCallError('timeout', `${method} got no answer in ${timeoutMs} ms.`, method)
                    ),
                timeoutMs
            );
            const onAbort = (): void =>
                this.fail(id, call, new BridgeCallError('aborted', `${method} was aborted.`, method));
            options.signal?.addEventListener('abort', onAbort, { once: true });
            call.cleanup = () => {
                clearTimeout(timer);
                options.signal?.removeEventListener('abort', onAbort);
            };
            if (this.inFlight < BRIDGE_LIMITS.maxInFlight) this.send(call);
            else this.waiting.push(call);
        });
    }

    /** Subscribes to one topic; returns the function that unsubscribes. */
    on<Topic extends EventTopic>(topic: Topic, handler: EventHandler<Topic>): () => void {
        let set = this.handlers.get(topic);
        if (!set) {
            set = new Set();
            this.handlers.set(topic, set);
        }
        const stored = handler as EventHandler<EventTopic>;
        set.add(stored);
        return () => {
            set.delete(stored);
        };
    }

    /** Called once when the connection closes. Returns the function that removes the listener. */
    onClose(listener: () => void): () => void {
        if (this.closed) {
            queueMicrotask(listener);
            return () => undefined;
        }
        this.closeListeners.add(listener);
        return () => {
            this.closeListeners.delete(listener);
        };
    }

    /** Rejects every waiting call with `closed`, closes the port and tells close listeners. Safe to call twice. */
    close(): void {
        if (this.closed) return;
        this.closed = true;
        this.port.onmessage = null;
        this.port.close();
        for (const [id, call] of [...this.pending]) {
            this.fail(id, call, new BridgeCallError('closed', 'The bridge connection is closed.', call.method));
        }
        this.abandoned.forEach((timer) => clearTimeout(timer));
        this.abandoned.clear();
        this.handlers.clear();
        const listeners = [...this.closeListeners];
        this.closeListeners.clear();
        for (const listener of listeners) {
            try {
                listener();
            } catch (error) {
                reportCallbackError(error);
            }
        }
    }

    private send(call: PendingCall): void {
        call.sent = true;
        this.inFlight++;
        this.port.postMessage(call.message);
    }

    /** The answer arrived: the call leaves the books and frees its slot. */
    private settle(id: number, call: PendingCall): void {
        this.pending.delete(id);
        call.cleanup();
        this.releaseSlot();
    }

    /**
     * The caller gave up (timeout, abort, close). A call still waiting to be sent just leaves the
     * queue; a sent one keeps its slot until its late answer or the safety timer.
     */
    private fail(id: number, call: PendingCall, error: BridgeCallError): void {
        if (this.pending.get(id) !== call) return;
        this.pending.delete(id);
        call.cleanup();
        if (!call.sent) {
            const index = this.waiting.indexOf(call);
            if (index >= 0) this.waiting.splice(index, 1);
        } else if (!this.closed) {
            this.abandoned.set(
                id,
                setTimeout(() => this.releaseAbandoned(id), this.abandonedReleaseMs)
            );
        }
        call.reject(error);
    }

    private releaseAbandoned(id: number): void {
        const timer = this.abandoned.get(id);
        if (timer === undefined) return;
        clearTimeout(timer);
        this.abandoned.delete(id);
        this.releaseSlot();
    }

    private releaseSlot(): void {
        this.inFlight--;
        this.sendWaiting();
    }

    private sendWaiting(): void {
        while (!this.closed && this.inFlight < BRIDGE_LIMITS.maxInFlight) {
            const next = this.waiting.shift();
            if (!next) return;
            this.send(next);
        }
    }

    private handleMessage(data: unknown): void {
        if (this.closed || !isRecord(data) || data['v'] !== BRIDGE_VERSION) return;
        if (data['kind'] === 'response') this.handleResponse(data);
        else if (data['kind'] === 'event') this.handleEvent(data);
    }

    private handleResponse(data: Record<string, unknown>): void {
        const id = data['id'];
        if (typeof id !== 'number') return;
        if (this.abandoned.has(id)) {
            // A late answer to a call the caller gave up on: only its slot matters now.
            this.releaseAbandoned(id);
            return;
        }
        const call = this.pending.get(id);
        // An answer to a request still queued here (never sent) can't be genuine.
        if (!call || !call.sent) return;
        this.settle(id, call);
        if (data['ok'] === true) {
            call.resolve(data['result']);
            return;
        }
        const error = isRecord(data['error']) ? data['error'] : {};
        const code = isBridgeErrorCode(error['code']) ? error['code'] : 'internal';
        const message = typeof error['message'] === 'string' ? error['message'] : `${call.method} failed.`;
        call.reject(new BridgeCallError(code, message, call.method));
    }

    private handleEvent(data: Record<string, unknown>): void {
        const topic = data['topic'];
        if (typeof topic !== 'string') return;
        const handlers = this.handlers.get(topic as EventTopic);
        if (!handlers) return;
        const subscription = typeof data['subscription'] === 'string' ? data['subscription'] : null;
        for (const handler of [...handlers]) {
            try {
                handler(data['data'] as BridgeEvents[EventTopic], subscription);
            } catch (error) {
                reportCallbackError(error);
            }
        }
    }

    private sizeProblem(message: RequestMessage): string | null {
        let json: string;
        try {
            json = JSON.stringify(message);
        } catch {
            return `${message.method} params must be plain JSON data.`;
        }
        if (this.encoder.encode(json).length > BRIDGE_LIMITS.maxRequestBytes) {
            return `The ${message.method} request is larger than ${BRIDGE_LIMITS.maxRequestBytes / 1024} KB.`;
        }
        return null;
    }
}
