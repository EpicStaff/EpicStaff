/**
 * Just enough of a browser window for the SDK: `parent`, message delivery with any `source` and `origin` (Node's
 * `MessageEvent` only accepts a `MessagePort` as `source`), `history`, `location`, `document`, `sessionStorage`,
 * `open`, `opener` and the secure-context switch.
 */

export const EPICSTAFF_ORIGIN = 'https://epicstaff.example.com';
export const PLUGIN_ORIGIN = 'https://weather.plugins.epicstaff.example.com';

interface DeliveredMessage {
    data: unknown;
    source: unknown;
    origin: string;
    ports: readonly MessagePort[];
}

type MessageListener = (event: DeliveredMessage) => void;

export class FakeLocation {
    /** Every `location.replace` call; the page stays where it is, as if the navigation were still loading. */
    readonly replacements: string[] = [];
    /** Every `location.assign` call; the login flow must never make one. */
    readonly assignments: string[] = [];
    private url: URL;

    constructor(href: string) {
        this.url = new URL(href);
    }

    get href(): string {
        return this.url.href;
    }

    set href(value: string) {
        this.url = new URL(value, this.url.href);
    }

    get origin(): string {
        return this.url.origin;
    }

    get pathname(): string {
        return this.url.pathname;
    }

    get search(): string {
        return this.url.search;
    }

    get hash(): string {
        return this.url.hash;
    }

    replace(url: string | URL): void {
        this.replacements.push(new URL(url, this.url.href).href);
    }

    assign(url: string | URL): void {
        this.assignments.push(new URL(url, this.url.href).href);
    }
}

/** `sessionStorage`: strings by key. */
export class FakeStorage {
    readonly items = new Map<string, string>();

    get length(): number {
        return this.items.size;
    }

    key(index: number): string | null {
        return [...this.items.keys()][index] ?? null;
    }

    getItem(key: string): string | null {
        return this.items.get(key) ?? null;
    }

    setItem(key: string, value: string): void {
        this.items.set(key, String(value));
    }

    removeItem(key: string): void {
        this.items.delete(key);
    }

    clear(): void {
        this.items.clear();
    }
}

export interface HistoryCall {
    method: 'pushState' | 'replaceState';
    url: string;
}

export class FakeHistory {
    state: unknown = null;
    length = 1;
    readonly calls: HistoryCall[] = [];
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
        if (url !== undefined && url !== null) this.location.href = String(url);
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

/** A frame the page created; its `contentWindow` is a stand-in object, compared by identity. */
export class FakeFrame {
    src = '';
    hidden = false;
    tabIndex = 0;
    title = '';
    readonly style = new FakeStyle() as FakeStyle & Record<string, string>;
    readonly attributes = new Map<string, string>();
    readonly contentWindow = { frame: 'silent sign-in' };
    removed = false;

    setAttribute(name: string, value: string): void {
        this.attributes.set(name, value);
    }

    remove(): void {
        this.removed = true;
    }
}

export class FakeBody {
    readonly children: FakeFrame[] = [];

    append(...nodes: FakeFrame[]): void {
        this.children.push(...nodes);
    }
}

export class FakeDocument extends EventTarget {
    readonly documentElement = new FakeElement();
    visibilityState: 'visible' | 'hidden' = 'visible';
    readonly body = new FakeBody();
    /** Every frame the page created, attached or not. */
    readonly frames: FakeFrame[] = [];

    createElement(tag: string): FakeFrame {
        if (tag !== 'iframe') throw new Error(`The fake document only creates iframes, not ${tag}.`);
        const frame = new FakeFrame();
        this.frames.push(frame);
        return frame;
    }

    /** Frames attached and not removed yet. */
    get liveFrames(): FakeFrame[] {
        return this.body.children.filter((frame) => !frame.removed);
    }

    /** What the browser does when the tab is hidden or shown again. */
    setVisibility(state: 'visible' | 'hidden'): void {
        this.visibilityState = state;
        this.dispatchEvent(new Event('visibilitychange'));
    }
}

/** A window the page opened with `window.open`, or the page's own opener. */
export class FakePopup {
    closed = false;
    readonly posted: { data: unknown; targetOrigin: string }[] = [];

    postMessage(data: unknown, targetOrigin: string): void {
        this.posted.push({ data, targetOrigin });
    }
}

/** EpicStaff's window as the plugin page sees it: records what the page posts to it. */
export class FakeParent {
    readonly posted: { data: unknown; targetOrigin: string }[] = [];
    handler: (data: unknown, targetOrigin: string) => void = () => undefined;

    postMessage(data: unknown, targetOrigin: string): void {
        this.posted.push({ data, targetOrigin });
        this.handler(data, targetOrigin);
    }
}

export interface FakeWindowOptions {
    /** `false`: the window is its own parent (a top-level page). Default `true`. */
    framed?: boolean;
    url?: string;
    /** `window.isSecureContext`. Default `true`. */
    secure?: boolean;
    /** `window.crypto`; `null` for none. Default Node's Web Crypto. */
    crypto?: Crypto | null;
    /** `window.opener`. Default `null`. */
    opener?: FakePopup | null;
    /** What `window.open` returns; `null` for a blocked popup. Default a new {@link FakePopup}. */
    popup?: FakePopup | null;
}

export class FakeWindow extends EventTarget {
    readonly location: FakeLocation;
    readonly history: FakeHistory;
    readonly document = new FakeDocument();
    readonly sessionStorage = new FakeStorage();
    readonly parent: FakeParent | FakeWindow;
    readonly isSecureContext: boolean;
    readonly crypto: Crypto | undefined;
    readonly opener: FakePopup | null;
    readonly dispatched: string[] = [];
    /** Every `window.open` call. */
    readonly opened: { url: string; target: string; features: string }[] = [];
    /** `true` once the page called `window.close()`. */
    closedByScript = false;
    private readonly popup: FakePopup | null;
    private readonly messageListeners = new Set<MessageListener>();

    constructor(options: FakeWindowOptions = {}) {
        super();
        this.location = new FakeLocation(options.url ?? `${PLUGIN_ORIGIN}/`);
        this.history = new FakeHistory(this.location);
        this.parent = options.framed === false ? this : new FakeParent();
        this.isSecureContext = options.secure ?? true;
        this.crypto = options.crypto === null ? undefined : (options.crypto ?? globalThis.crypto);
        this.opener = options.opener ?? null;
        this.popup = options.popup === undefined ? new FakePopup() : options.popup;
    }

    open(url: string, target: string, features: string): FakePopup | null {
        this.opened.push({ url, target, features });
        return this.popup;
    }

    close(): void {
        this.closedByScript = true;
    }

    /** The popup `window.open` hands out. */
    get openedPopup(): FakePopup {
        if (this.popup === null) throw new Error('This window blocks popups.');
        return this.popup;
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

    /** Delivers a `message` event as the browser would, with any `source` and `origin`. */
    deliverMessage(data: unknown, source: unknown, origin: string, ports: readonly MessagePort[] = []): void {
        for (const listener of [...this.messageListeners]) listener({ data, source, origin, ports });
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

export interface FakeHost {
    /** EpicStaff's end of the port; set after the handshake. */
    port(): MessagePort;
    /** Everything the page sent on the port. */
    readonly received: unknown[];
    /** How many `es:ready` messages EpicStaff answered. */
    readonly handshakes: number;
}

export interface FakeHostOptions {
    init?: Record<string, unknown>;
    /** Answer `es:ready` from this origin instead of EpicStaff's. */
    origin?: string;
    /** Answer `es:ready` with this `source` instead of `window.parent`. */
    source?: unknown;
    /** Answer with `es:error` instead of `es:init`. */
    error?: string;
    /** Never answer. */
    silent?: boolean;
}

/** Every port a fake host opened; an open port with a listener would keep the test process alive. */
const openHostPorts = new Set<MessagePort>();

/** Closes every port the fake hosts opened. Call it after each test. */
export function closeFakeHosts(): void {
    for (const port of openHostPorts) port.close();
    openHostPorts.clear();
}

/** Frames `win` in a fake EpicStaff that answers `es:ready` the way the real host does (or deliberately does not). */
export function frameWithHost(win: FakeWindow, options: FakeHostOptions = {}): FakeHost {
    const parent = win.parentFrame;
    let hostPort: MessagePort | null = null;
    const received: unknown[] = [];
    let handshakes = 0;
    parent.handler = (data) => {
        if (options.silent || typeof data !== 'object' || data === null) return;
        if ((data as { type?: unknown }).type !== 'es:ready') return;
        handshakes++;
        const origin = options.origin ?? EPICSTAFF_ORIGIN;
        const source = options.source ?? parent;
        if (options.error !== undefined) {
            queueMicrotask(() =>
                win.deliverMessage({ type: 'es:error', protocol: 1, code: options.error }, source, origin)
            );
            return;
        }
        const channel = new MessageChannel();
        openHostPorts.add(channel.port1).add(channel.port2);
        hostPort = channel.port1;
        hostPort.onmessage = (event: MessageEvent) => received.push(event.data);
        const init = {
            type: 'es:init',
            protocol: 1,
            theme: { mode: 'dark', tokens: { '--es-color-accent': '#685fff' } },
            nav: { path: '/' },
            org: { id: 3, name: 'Acme' },
            ...options.init,
        };
        queueMicrotask(() => win.deliverMessage(init, source, origin, [channel.port2]));
    };
    return {
        port: () => {
            if (!hostPort) throw new Error('No handshake yet.');
            return hostPort;
        },
        received,
        get handshakes() {
            return handshakes;
        },
    };
}

/** A `fetch` that answers the platform config request. */
export function configFetch(
    overrides: Record<string, unknown> = {}
): typeof fetch & { urls: string[]; requests: (RequestInit | undefined)[] } {
    const urls: string[] = [];
    const requests: (RequestInit | undefined)[] = [];
    const fetchConfig = async (input: string | URL | Request, init?: RequestInit): Promise<Response> => {
        urls.push(String(input));
        requests.push(init);
        const body = {
            plugin: { identifier: 'weather', name: 'Weather', version: '0.1.0' },
            epicstaff_origin: EPICSTAFF_ORIGIN,
            frame_protocol: 1,
            api_base: '/api/',
            login: null,
            ...overrides,
        };
        return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });
    };
    return Object.assign(fetchConfig as typeof fetch, { urls, requests });
}

export function delay(milliseconds: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

/** Resolves once `predicate` holds, polling every few milliseconds; fails after `timeoutMs`. */
export async function waitFor(predicate: () => boolean, timeoutMs = 2000): Promise<void> {
    const start = Date.now();
    while (!predicate()) {
        if (Date.now() - start > timeoutMs) throw new Error('Timed out waiting for a condition.');
        await delay(5);
    }
}
