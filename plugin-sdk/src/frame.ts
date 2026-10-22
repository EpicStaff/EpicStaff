import { canonicalNavPath } from './nav-path.js';
import {
    type AvailabilityChangedMessage,
    FRAME_ERROR_CODES,
    FRAME_LIMITS,
    FRAME_MESSAGE_TYPES,
    FRAME_PROTOCOL_VERSION,
    type FrameErrorCode,
    isRecord,
    type NavChangedMessage,
    ORG_HINT_PARAMETER,
    type OrgContext,
    type PluginAvailability,
    type ReadyMessage,
    type ThemeState,
} from './protocol.js';
import { readThemeState } from './theme.js';

/** What `es:init` told the page, checked and normalised. */
export interface FrameInit {
    theme: ThemeState;
    /** The page's path EpicStaff's address shows, canonical. */
    navPath: string;
    org: OrgContext | null;
}

/** Why the page runs without EpicStaff's frame. */
export type UnframedReason = 'not_framed' | 'timeout' | FrameErrorCode;

export type HandshakeOutcome =
    | { framed: true; init: FrameInit; port: MessagePort }
    | { framed: false; reason: UnframedReason };

export interface HandshakeOptions {
    /** EpicStaff's origin from the platform config; the only origin the handshake talks to. */
    epicstaffOrigin: string;
    /** Defaults to the protocol's 3 seconds. */
    timeoutMs?: number;
}

const DEFAULT_THEME: ThemeState = { mode: 'dark', tokens: {} };

/**
 * Reads the organization hint EpicStaff put into the frame URL (`es_org`) and removes it from the address with
 * `history.replaceState`, so the page's router never sees it. Call it before the router starts. Returns `null` when
 * there is no valid hint.
 */
export function takeOrgHint(win: Window): number | null {
    const { pathname, search, hash } = win.location;
    const parts = search.startsWith('?') ? search.slice(1).split('&') : [];
    const isHint = (part: string): boolean => part.split('=', 1)[0] === ORG_HINT_PARAMETER;
    const hints = parts.filter(isHint);
    if (hints.length === 0) return null;
    // Rebuilt from the raw parts, so the page's own query keeps its exact spelling.
    const rest = parts.filter((part) => !isHint(part));
    win.history.replaceState(win.history.state, '', pathname + (rest.length > 0 ? `?${rest.join('&')}` : '') + hash);
    // EpicStaff appends the hint last, after the page's own query.
    const value = hints[hints.length - 1]?.slice(ORG_HINT_PARAMETER.length + 1) ?? '';
    const hint = /^[1-9][0-9]{0,15}$/.test(value) ? Number(value) : Number.NaN;
    return Number.isSafeInteger(hint) ? hint : null;
}

/** True when the page is inside some frame (it may still turn out not to be EpicStaff's). */
export function isFramed(win: Window): boolean {
    return win.parent !== win;
}

/**
 * Runs the frame protocol handshake: posts `es:ready` to `window.parent` for EpicStaff's origin only and waits for the
 * answer. Only a message whose `source` is `window.parent` and whose `origin` is EpicStaff's counts. Without an answer
 * in time the page runs unframed — the protocol is optional.
 */
export function performHandshake(win: Window, options: HandshakeOptions): Promise<HandshakeOutcome> {
    if (!isFramed(win)) return Promise.resolve({ framed: false, reason: 'not_framed' });
    const timeoutMs = options.timeoutMs ?? FRAME_LIMITS.initTimeoutMs;

    return new Promise((resolve) => {
        let settled = false;
        const finish = (outcome: HandshakeOutcome): void => {
            if (settled) return;
            settled = true;
            clearTimeout(timer);
            win.removeEventListener('message', onMessage);
            resolve(outcome);
        };
        const onMessage = (event: MessageEvent): void => {
            if (event.source !== win.parent || event.origin !== options.epicstaffOrigin) return;
            const data: unknown = event.data;
            if (!isRecord(data)) return;
            if (data['type'] === FRAME_MESSAGE_TYPES.error) {
                finish({ framed: false, reason: toErrorCode(data['code']) });
                return;
            }
            if (data['type'] !== FRAME_MESSAGE_TYPES.init || data['protocol'] !== FRAME_PROTOCOL_VERSION) return;
            const port = event.ports[0];
            if (!port) return;
            finish({ framed: true, init: readInit(data), port });
        };
        const timer = setTimeout(() => finish({ framed: false, reason: 'timeout' }), timeoutMs);
        win.addEventListener('message', onMessage);
        const ready: ReadyMessage = { type: FRAME_MESSAGE_TYPES.ready, protocol: FRAME_PROTOCOL_VERSION };
        win.parent.postMessage(ready, options.epicstaffOrigin);
    });
}

/** Handlers for the messages EpicStaff sends on the port. */
export interface FramePortHandlers {
    onNavigate(path: string): void;
    onThemeChanged(theme: ThemeState): void;
}

/**
 * The page's end of the port: sends `nav.changed` and `availability.changed`, dispatches `nav.navigate` and
 * `theme.changed`.
 */
export class FrameChannel {
    private readonly port: MessagePort;
    private closed = false;

    constructor(port: MessagePort, handlers: FramePortHandlers) {
        this.port = port;
        port.onmessage = (event: MessageEvent): void => {
            if (this.closed || !isRecord(event.data)) return;
            const data = event.data;
            if (data['type'] === FRAME_MESSAGE_TYPES.navNavigate) {
                const path = canonicalNavPath(data['path']);
                if (path !== null) handlers.onNavigate(path);
            } else if (data['type'] === FRAME_MESSAGE_TYPES.themeChanged) {
                const theme = readThemeState(data['theme']);
                if (theme !== null) handlers.onThemeChanged(theme);
            }
        };
    }

    reportNavigation(path: string, replace: boolean): void {
        if (this.closed) return;
        const message: NavChangedMessage = { type: FRAME_MESSAGE_TYPES.navChanged, path, replace };
        this.port.postMessage(message);
    }

    reportAvailability(state: PluginAvailability): void {
        if (this.closed) return;
        const message: AvailabilityChangedMessage = { type: FRAME_MESSAGE_TYPES.availabilityChanged, state };
        this.port.postMessage(message);
    }

    close(): void {
        if (this.closed) return;
        this.closed = true;
        this.port.onmessage = null;
        this.port.close();
    }
}

/** How long the page waits after telling EpicStaff its availability before it tells it again. */
export const AVAILABILITY_REPORT_INTERVAL_MS = 30_000;

/**
 * Tells EpicStaff when the plugin's API answers `maintenance` or `unavailable`, at most once per
 * {@link AVAILABILITY_REPORT_INTERVAL_MS}. A change inside that window is not lost: when the window ends, the latest
 * state is sent, unless the API is available again by then. `available` itself is never sent: EpicStaff finds out
 * from its own server.
 */
export class AvailabilityReporter {
    private readonly send: (state: PluginAvailability) => void;
    private readonly intervalMs: number;
    /** Set while a window is open: a report waits for it to end. */
    private timer: ReturnType<typeof setTimeout> | null = null;
    /** What to send when the window ends. */
    private waiting: PluginAvailability | null = null;
    private closed = false;

    constructor(send: (state: PluginAvailability) => void, intervalMs = AVAILABILITY_REPORT_INTERVAL_MS) {
        this.send = send;
        this.intervalMs = intervalMs;
    }

    report(state: PluginAvailability): void {
        if (this.closed) return;
        if (this.timer !== null) {
            this.waiting = state === 'available' ? null : state;
            return;
        }
        if (state !== 'available') this.sendNow(state);
    }

    close(): void {
        this.closed = true;
        this.waiting = null;
        if (this.timer !== null) clearTimeout(this.timer);
        this.timer = null;
    }

    private sendNow(state: PluginAvailability): void {
        this.send(state);
        this.timer = setTimeout(() => this.endWindow(), this.intervalMs);
    }

    private endWindow(): void {
        this.timer = null;
        const waiting = this.waiting;
        this.waiting = null;
        if (waiting !== null && !this.closed) this.sendNow(waiting);
    }
}

function readInit(data: Record<string, unknown>): FrameInit {
    const nav = data['nav'];
    const navPath = isRecord(nav) ? canonicalNavPath(nav['path']) : null;
    return {
        theme: readThemeState(data['theme']) ?? DEFAULT_THEME,
        navPath: navPath ?? '/',
        org: readOrg(data['org']),
    };
}

function readOrg(value: unknown): OrgContext | null {
    if (!isRecord(value)) return null;
    const id = value['id'];
    const name = value['name'];
    if (typeof id !== 'number' || !Number.isSafeInteger(id) || id <= 0 || typeof name !== 'string') return null;
    return { id, name };
}

function toErrorCode(code: unknown): FrameErrorCode {
    return FRAME_ERROR_CODES.find((known) => known === code) ?? 'unsupported_protocol';
}
