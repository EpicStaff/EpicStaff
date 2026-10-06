import { PluginUiSession } from '../../models/plugin.model';

/** A `MessagePort` stand-in that delivers synchronously, so bridge specs need no event-loop waits. */
export class FakeMessagePort {
    onmessage: ((event: MessageEvent) => void) | null = null;
    closed = false;
    partner: FakeMessagePort | null = null;
    /** Everything delivered to this port, in order. */
    readonly received: unknown[] = [];

    postMessage(data: unknown): void {
        const partner = this.partner;
        if (this.closed || !partner || partner.closed) return;
        const copy: unknown = structuredClone(data);
        partner.received.push(copy);
        partner.onmessage?.({ data: copy } as MessageEvent);
    }

    close(): void {
        this.closed = true;
    }

    start(): void {
        // Delivery is synchronous; nothing to start.
    }
}

export class FakeMessageChannel {
    readonly port1 = new FakeMessagePort();
    readonly port2 = new FakeMessagePort();

    constructor() {
        this.port1.partner = this.port2;
        this.port2.partner = this.port1;
    }
}

/** An `EventSource` stand-in the specs drive by hand. */
export class FakeEventSource {
    static readonly instances: FakeEventSource[] = [];

    onopen: (() => void) | null = null;
    onerror: (() => void) | null = null;
    closed = false;
    private readonly listeners = new Map<string, ((event: MessageEvent) => void)[]>();

    constructor(readonly url: string) {
        FakeEventSource.instances.push(this);
    }

    addEventListener(type: string, listener: (event: MessageEvent) => void): void {
        this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
    }

    emit(type: string, data: unknown): void {
        const event = { data: JSON.stringify(data) } as MessageEvent;
        this.listeners.get(type)?.forEach((listener) => listener(event));
    }

    fail(): void {
        this.onerror?.();
    }

    close(): void {
        this.closed = true;
    }
}

export interface PostedToFrame {
    message: unknown;
    targetOrigin: string;
    transfer: unknown[];
}

export interface PluginFrame {
    frame: HTMLIFrameElement;
    frameWindow: Window;
    /** Everything the host posted to the frame's window. */
    posted: PostedToFrame[];
}

/** An attached iframe whose window's `postMessage` is recorded instead of delivered. */
export function createPluginFrame(): PluginFrame {
    const frame = document.createElement('iframe');
    document.body.appendChild(frame);
    const frameWindow = frame.contentWindow;
    if (!frameWindow) throw new Error('jsdom gave the iframe no window');
    const posted: PostedToFrame[] = [];
    const record = (message: unknown, targetOrigin: string, transfer: unknown[] = []): void => {
        posted.push({ message, targetOrigin, transfer });
    };
    frameWindow.postMessage = record as unknown as Window['postMessage'];
    return { frame, frameWindow, posted };
}

/** Dispatches a `message` event on the host window as if `source` had posted it. */
export function postFromWindow(source: Window | null, data: unknown, origin = 'null'): void {
    window.dispatchEvent(new MessageEvent('message', { data, origin, source }));
}

export function buildUiSession(overrides: Partial<PluginUiSession> = {}): PluginUiSession {
    return {
        url: '/api/plugin-ui/token-1/index.html',
        token: 'token-1',
        expires_in: 600,
        bridge_version: 1,
        plugin: { id: 7, plugin_id: 'chat-bot', name: 'Chat Bot', version: '0.1.0' },
        access: [{ alias: 'chat', type: 'flow', actions: ['run', 'sessions.read', 'sessions.stop'], resource_id: 42 }],
        ...overrides,
    };
}
