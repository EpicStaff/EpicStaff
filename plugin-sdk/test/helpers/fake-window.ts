/**
 * Just enough of a browser window for the SDK: `parent`, `postMessage`-style message delivery
 * (Node's `MessageEvent` only accepts a `MessagePort` as `source`), `history`, `location`,
 * `document.documentElement` and storage that throws like a sandboxed frame.
 */

import type { MockHost } from '../../dist/mock-host.js';

type MessageListener = (event: {
    data: unknown;
    source: unknown;
    origin: string;
    ports: readonly MessagePort[];
}) => void;

export class FakeLocation {
    href: string;

    constructor(href: string) {
        this.href = href;
    }

    get hash(): string {
        const index = this.href.indexOf('#');
        return index < 0 || index === this.href.length - 1 ? '' : this.href.slice(index);
    }
}

export interface HistoryCall {
    method: 'pushState' | 'replaceState';
    url: string;
}

export class FakeHistory {
    state: unknown = null;
    readonly calls: HistoryCall[] = [];
    length = 1;
    private readonly location: FakeLocation;

    constructor(location: FakeLocation) {
        this.location = location;
    }

    pushState(state: unknown, _unused: string, url?: string | URL | null): void {
        this.apply('pushState', state, url);
        this.length++;
    }

    replaceState(state: unknown, _unused: string, url?: string | URL | null): void {
        this.apply('replaceState', state, url);
    }

    private apply(method: HistoryCall['method'], state: unknown, url?: string | URL | null): void {
        this.state = state;
        if (url !== undefined && url !== null) this.location.href = new URL(String(url), this.location.href).href;
        this.calls.push({ method, url: this.location.href });
    }
}

export class FakeStyle {
    readonly properties = new Map<string, string>();

    setProperty(name: string, value: string): void {
        this.properties.set(name, value);
    }

    removeProperty(name: string): string {
        const value = this.properties.get(name) ?? '';
        this.properties.delete(name);
        return value;
    }

    getPropertyValue(name: string): string {
        return this.properties.get(name) ?? '';
    }
}

export class FakeElement {
    readonly style = new FakeStyle();
    readonly attributes = new Map<string, string>();

    setAttribute(name: string, value: string): void {
        this.attributes.set(name, value);
    }

    getAttribute(name: string): string | null {
        return this.attributes.get(name) ?? null;
    }
}

export class FakeDocument {
    readonly documentElement = new FakeElement();

    get cookie(): string {
        throw new DOMException('The document is sandboxed and lacks the "allow-same-origin" flag.', 'SecurityError');
    }

    set cookie(_value: string) {
        throw new DOMException('The document is sandboxed and lacks the "allow-same-origin" flag.', 'SecurityError');
    }
}

/** Receives what the page posts to `window.parent`. */
export type ParentHandler = (data: unknown, targetOrigin: string) => void;

export class FakeParent {
    readonly posted: Array<{ data: unknown; targetOrigin: string }> = [];
    handler: ParentHandler = () => undefined;

    postMessage(data: unknown, targetOrigin: string): void {
        this.posted.push({ data, targetOrigin });
        this.handler(data, targetOrigin);
    }
}

export interface FakeWindowOptions {
    /** `false`: the window is its own parent (a top-level page). Default `true`. */
    framed?: boolean;
    url?: string;
}

export class FakeWindow extends EventTarget {
    readonly location: FakeLocation;
    readonly history: FakeHistory;
    readonly document = new FakeDocument();
    readonly parent: FakeParent | FakeWindow;
    readonly dispatched: string[] = [];
    private readonly messageListeners = new Set<MessageListener>();

    constructor(options: FakeWindowOptions = {}) {
        super();
        this.location = new FakeLocation(options.url ?? 'http://epicstaff.test/api/plugin-ui/token/index.html#/');
        this.history = new FakeHistory(this.location);
        this.parent = options.framed === false ? this : new FakeParent();
    }

    get localStorage(): Storage {
        throw new DOMException('The document is sandboxed and lacks the "allow-same-origin" flag.', 'SecurityError');
    }

    get sessionStorage(): Storage {
        throw new DOMException('The document is sandboxed and lacks the "allow-same-origin" flag.', 'SecurityError');
    }

    override addEventListener(
        type: string,
        listener: EventListenerOrEventListenerObject | MessageListener | null,
        options?: AddEventListenerOptions | boolean
    ): void {
        if (type === 'message') this.messageListeners.add(listener as MessageListener);
        else super.addEventListener(type, listener as EventListenerOrEventListenerObject | null, options);
    }

    override removeEventListener(
        type: string,
        listener: EventListenerOrEventListenerObject | MessageListener | null,
        options?: EventListenerOptions | boolean
    ): void {
        if (type === 'message') this.messageListeners.delete(listener as MessageListener);
        else super.removeEventListener(type, listener as EventListenerOrEventListenerObject | null, options);
    }

    override dispatchEvent(event: Event): boolean {
        this.dispatched.push(event.type);
        return super.dispatchEvent(event);
    }

    /** Delivers a `message` event as the browser would, with any `source`. */
    deliverMessage(data: unknown, source: unknown, ports: readonly MessagePort[] = []): void {
        for (const listener of [...this.messageListeners]) listener({ data, source, origin: 'null', ports });
    }

    get messageListenerCount(): number {
        return this.messageListeners.size;
    }

    get parentFrame(): FakeParent {
        if (!(this.parent instanceof FakeParent)) throw new Error('This window is not framed.');
        return this.parent;
    }

    asWindow(): Window {
        return this as unknown as Window;
    }
}

/**
 * Frames `win` in a fake EpicStaff that answers the handshake with `host` (the SDK's mock host
 * speaks the real protocol), so the framed code path runs end to end.
 */
export function frameWithHost(win: FakeWindow, host: MockHost, options: { initDelayMs?: number } = {}): void {
    const parent = win.parentFrame;
    parent.handler = (data) => {
        const answer = (): void => {
            const result = host.handshake(data, { path: null });
            if (result.ok) win.deliverMessage(result.init, parent, [result.port]);
            else win.deliverMessage(result.error, parent);
        };
        if (options.initDelayMs === undefined) queueMicrotask(answer);
        else setTimeout(answer, options.initDelayMs);
    };
}

/** One request the scripted host received, with helpers to answer it. */
export interface ScriptedRequest {
    id: number | string;
    method: string;
    params: Record<string, unknown>;
}

export interface ScriptedHost {
    readonly requests: ScriptedRequest[];
    /** The host's end of the bridge port; set after the handshake. */
    port(): MessagePort;
    reply(request: ScriptedRequest, result: unknown): void;
    replyError(request: ScriptedRequest, code: string, message: string): void;
    emit(topic: string, subscription: string | null, data: unknown): void;
    close(): void;
}

/**
 * Frames `win` in a fake EpicStaff whose answers the test scripts by hand: every request goes to
 * `onRequest`, which may answer it (or not, to test timeouts).
 */
export function frameWithScriptedHost(
    win: FakeWindow,
    onRequest: (request: ScriptedRequest, host: ScriptedHost) => void,
    context: Record<string, unknown> = {}
): ScriptedHost {
    const parent = win.parentFrame;
    let hostPort: MessagePort | null = null;
    const requests: ScriptedRequest[] = [];
    const host: ScriptedHost = {
        requests,
        port: () => {
            if (!hostPort) throw new Error('No handshake yet.');
            return hostPort;
        },
        reply: (request, result) =>
            host.port().postMessage({ v: 2, kind: 'response', id: request.id, ok: true, result }),
        replyError: (request, code, message) =>
            host.port().postMessage({ v: 2, kind: 'response', id: request.id, ok: false, error: { code, message } }),
        emit: (topic, subscription, data) =>
            host.port().postMessage({ v: 2, kind: 'event', topic, subscription, data }),
        close: () => hostPort?.close(),
    };
    parent.handler = (data) => {
        if (!isReady(data)) return;
        const channel = new MessageChannel();
        hostPort = channel.port1;
        hostPort.onmessage = (event: MessageEvent) => {
            const request = event.data as ScriptedRequest;
            requests.push(request);
            onRequest(request, host);
        };
        const init = {
            v: 2,
            kind: 'init',
            context: {
                plugin: { id: 'scripted', version: '1.0.0', name: 'Scripted' },
                access: [],
                nav: { path: '/' },
                theme: { mode: 'dark', tokens: {} },
                ...context,
            },
        };
        queueMicrotask(() => win.deliverMessage(init, parent, [channel.port2]));
    };
    return host;
}

function isReady(data: unknown): boolean {
    return typeof data === 'object' && data !== null && (data as { kind?: unknown }).kind === 'ready';
}

export function delay(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Resolves once `predicate` holds, polling every few ms; fails after `timeoutMs`. */
export async function waitFor(predicate: () => boolean, timeoutMs = 2000): Promise<void> {
    const start = Date.now();
    while (!predicate()) {
        if (Date.now() - start > timeoutMs) throw new Error('Timed out waiting for a condition.');
        await delay(5);
    }
}
