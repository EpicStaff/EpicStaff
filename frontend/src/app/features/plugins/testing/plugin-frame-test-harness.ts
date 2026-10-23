/** A `MessagePort` stand-in that delivers synchronously, so frame specs need no event-loop waits. */
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

/** Dispatches a `message` event on the host window as if `source` had posted it from `origin`. */
export function postFromWindow(source: Window | null, data: unknown, origin: string): void {
    window.dispatchEvent(new MessageEvent('message', { data, origin, source }));
}
