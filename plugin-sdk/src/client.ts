import { BridgeConnection, type CallOptions, type EventHandler } from './connection.js';
import { BridgeCallError } from './errors.js';
import type { MockHost } from './mock-host.js';
import { canonicalNavPath, hashToNavPath } from './nav-path.js';
import { installNavSync, type NavReport, type NavSync } from './nav-sync.js';
import {
    ACCESS_ACTIONS_BY_TYPE,
    type AccessAction,
    type AccessDescription,
    type AccessType,
    BRIDGE_VERSION,
    type EmptyResult,
    type EventTopic,
    type FlowsRunResult,
    type InitContext,
    isBridgeErrorCode,
    isRecord,
    type KvEntry,
    type KvListParams,
    type KvListResult,
    type MethodName,
    type MethodParams,
    type MethodResult,
    type ReadyMessage,
    type SessionRecord,
    type SubscribeResult,
    type ThemeState,
} from './protocol.js';
import { notify } from './report-error.js';
import { runAndWait, type RunAndWaitOptions } from './run-and-wait.js';
import { applyTheme, normalizeThemeMode } from './theme.js';

/** A mock host, or a factory for one (e.g. a lazy `import()`, so production bundles skip the sample data). */
export type MockHostSource = MockHost | (() => MockHost | Promise<MockHost>);

export interface NavSyncConnectOptions {
    /**
     * Handle `nav.navigate` yourself (e.g. `router.navigateByUrl(path)`) instead of the default:
     * set the hash with `replaceState`, then dispatch synthetic `popstate` and `hashchange`.
     */
    onNavigate?: (path: string) => void;
}

export interface ConnectOptions {
    /** How long to wait for EpicStaff to answer the handshake. Default 10 000 ms. */
    timeoutMs?: number;
    /** Default timeout of every call. Default 30 000 ms. */
    requestTimeoutMs?: number;
    /**
     * The host to use when the page is not inside EpicStaff (`window.parent === window`), e.g. under
     * `npm start`. Default: an empty `createMockHost()`. `false`: fail instead.
     */
    mock?: MockHostSource | false;
    /** Use the mock host even inside a frame. Default `false`. */
    forceMock?: boolean;
    /** Keep EpicStaff's address bar in sync with the app's hash route. Default `true`. */
    navSync?: boolean | NavSyncConnectOptions;
    /** Apply EpicStaff's theme tokens to `<html>` and follow `theme.changed`. Default `true`. */
    theme?: boolean;
    /** The app's window. Default: the global `window`. */
    window?: Window;
}

/** `params` may be left out when every param of the method is optional. */
type CallArguments<Method extends MethodName> =
    Record<string, never> extends MethodParams<Method>
        ? [params?: MethodParams<Method>, options?: CallOptions]
        : [params: MethodParams<Method>, options?: CallOptions];

export interface BridgeNav {
    /** The app path EpicStaff shows for the current URL, e.g. `/conversations?page=2`. */
    readonly path: string;
    /**
     * Reports a path yourself, for apps that turn nav sync off (`navSync: false`).
     * With nav sync on, history changes are reported automatically.
     */
    report(path: string, replace?: boolean): Promise<void>;
    /** Called after every `nav.navigate` from EpicStaff. Returns the unsubscribe function. */
    onNavigate(handler: (path: string) => void): () => void;
}

export interface BridgeTheme {
    readonly current: ThemeState;
    /** Called after every `theme.changed`. Returns the unsubscribe function. */
    onChange(handler: (theme: ThemeState) => void): () => void;
}

/** The connected bridge. One per page: `connect()` returns the same instance on every call. */
export interface EpicStaffBridge {
    readonly context: InitContext;
    /** True when the mock host answers instead of EpicStaff. */
    readonly mocked: boolean;
    /** Calls any v2 method by name. */
    call<Method extends MethodName>(method: Method, ...args: CallArguments<Method>): Promise<MethodResult<Method>>;
    /** Subscribes to an event topic. Returns the unsubscribe function. */
    on<Topic extends EventTopic>(topic: Topic, handler: EventHandler<Topic>): () => void;
    readonly flows: {
        run(flow: string, variables?: Record<string, unknown>): Promise<FlowsRunResult>;
        /** Runs the flow and resolves with its End node output. See {@link runAndWait}. */
        runAndWait<Output = unknown>(
            flow: string,
            variables?: Record<string, unknown>,
            options?: RunAndWaitOptions
        ): Promise<Output>;
    };
    readonly sessions: {
        get(sessionId: number): Promise<SessionRecord>;
        subscribe(sessionId: number): Promise<SubscribeResult>;
        unsubscribe(subscription: string): Promise<EmptyResult>;
        stop(sessionId: number): Promise<EmptyResult>;
    };
    readonly kv: {
        list(params: KvListParams): Promise<KvListResult>;
        get<Value = unknown>(table: string, key: string): Promise<KvEntry<Value>>;
    };
    readonly nav: BridgeNav;
    readonly theme: BridgeTheme;
    /** Closes the port, rejects waiting calls and restores `history`. */
    close(): void;
}

const DEFAULT_HANDSHAKE_TIMEOUT_MS = 10_000;
const DEFAULT_REQUEST_TIMEOUT_MS = 30_000;

const connections = new WeakMap<Window, Promise<EpicStaffBridge>>();

/** True when the page runs inside a frame (EpicStaff opens plugin apps in a sandboxed iframe). */
export function isFramed(win: Window = window): boolean {
    try {
        return win.parent !== null && win.parent !== undefined && win.parent !== win;
    } catch {
        return true;
    }
}

/**
 * Connects to EpicStaff: installs nav sync (before the app's first navigation, so call it early —
 * in Angular inside `provideAppInitializer`), posts `ready` to `window.parent`, waits for `init`
 * with the port, then applies the theme. Outside a frame it connects to the mock host instead.
 *
 * Rejects with `BridgeCallError` (`timeout`, `unsupported`, …) when the handshake fails.
 */
export function connect(options: ConnectOptions = {}): Promise<EpicStaffBridge> {
    const win = options.window ?? (typeof window === 'undefined' ? undefined : window);
    if (win === undefined) {
        return Promise.reject(new BridgeCallError('unsupported', 'connect() needs a browser window.'));
    }
    const existing = connections.get(win);
    if (existing) return existing;

    const attempt = establish(win, options);
    connections.set(win, attempt);
    attempt.catch(() => {
        if (connections.get(win) === attempt) connections.delete(win);
    });
    return attempt;
}

async function establish(win: Window, options: ConnectOptions): Promise<EpicStaffBridge> {
    const framed = isFramed(win);
    const mocked = options.forceMock === true || !framed;
    const navOption = options.navSync ?? true;
    const navSync =
        navOption === false
            ? null
            : installNavSync(win, {
                  convertPush: framed,
                  ...(typeof navOption === 'object' && navOption.onNavigate
                      ? { onNavigate: navOption.onNavigate }
                      : {}),
              });
    try {
        const pagePath = navSync ? navSync.initialPath : hashToNavPath(win.location.hash);
        const { port, context } = mocked
            ? await handshakeWithMock(options.mock, pagePath)
            : await handshakeWithParent(win, options.timeoutMs ?? DEFAULT_HANDSHAKE_TIMEOUT_MS);
        const connection = new BridgeConnection(port, options.requestTimeoutMs ?? DEFAULT_REQUEST_TIMEOUT_MS);
        return new Bridge(win, connection, parseContext(context), mocked, navSync, options.theme !== false);
    } catch (error) {
        navSync?.uninstall();
        throw error;
    }
}

interface Handshake {
    port: MessagePort;
    context: unknown;
}

function handshakeWithParent(win: Window, timeoutMs: number): Promise<Handshake> {
    return new Promise<Handshake>((resolve, reject) => {
        const timer = setTimeout(() => {
            cleanup();
            reject(
                new BridgeCallError(
                    'timeout',
                    `EpicStaff did not answer the bridge handshake within ${timeoutMs} ms. Is this page open inside EpicStaff?`
                )
            );
        }, timeoutMs);
        const listener = (event: MessageEvent): void => {
            // Only the embedding EpicStaff page; anything else in the frame's window is ignored.
            if (event.source !== win.parent) return;
            const data: unknown = event.data;
            if (!isRecord(data)) return;
            if (data['kind'] === 'error') {
                // EpicStaff answers a version mismatch with its own `v`, so `v` is not checked here.
                cleanup();
                const error = isRecord(data['error']) ? data['error'] : {};
                reject(
                    new BridgeCallError(
                        isBridgeErrorCode(error['code']) ? error['code'] : 'unsupported',
                        typeof error['message'] === 'string'
                            ? error['message']
                            : 'EpicStaff refused the bridge handshake.'
                    )
                );
                return;
            }
            const port = event.ports?.[0];
            if (data['kind'] !== 'init' || data['v'] !== BRIDGE_VERSION || event.ports.length !== 1 || !port) return;
            cleanup();
            resolve({ port, context: data['context'] });
        };
        function cleanup(): void {
            clearTimeout(timer);
            win.removeEventListener('message', listener);
        }
        win.addEventListener('message', listener);
        const ready: ReadyMessage = { v: BRIDGE_VERSION, kind: 'ready' };
        // The sandboxed page has an opaque origin and cannot name EpicStaff's; the reply is checked by `source`.
        win.parent.postMessage(ready, '*');
    });
}

async function handshakeWithMock(source: MockHostSource | false | undefined, path: string | null): Promise<Handshake> {
    if (source === false) {
        throw new BridgeCallError(
            'unsupported',
            'This page is not open inside EpicStaff, and the mock host is turned off.'
        );
    }
    const host =
        source === undefined
            ? (await import('./mock-host.js')).createMockHost()
            : typeof source === 'function'
              ? await source()
              : source;
    const ready: ReadyMessage = { v: BRIDGE_VERSION, kind: 'ready' };
    const result = host.handshake(ready, { path });
    if (!result.ok) throw new BridgeCallError(result.error.error.code, result.error.error.message);
    return { port: result.port, context: result.init.context };
}

class ThemeChannel implements BridgeTheme {
    current: ThemeState;
    private readonly handlers = new Set<(theme: ThemeState) => void>();

    constructor(initial: ThemeState) {
        this.current = initial;
    }

    onChange(handler: (theme: ThemeState) => void): () => void {
        return subscribeTo(this.handlers, handler);
    }

    update(theme: ThemeState): void {
        this.current = theme;
        for (const handler of [...this.handlers]) notify(handler, theme);
    }

    clear(): void {
        this.handlers.clear();
    }
}

class NavChannel implements BridgeNav {
    private readonly handlers = new Set<(path: string) => void>();

    constructor(
        private readonly win: Window,
        private readonly navSync: NavSync | null,
        private readonly hostPath: string,
        private readonly connection: BridgeConnection
    ) {}

    get path(): string {
        return this.navSync?.currentPath() ?? hashToNavPath(this.win.location.hash) ?? this.hostPath;
    }

    async report(path: string, replace = false): Promise<void> {
        await this.connection.call('nav.changed', { path, replace });
    }

    onNavigate(handler: (path: string) => void): () => void {
        return subscribeTo(this.handlers, handler);
    }

    dispatch(path: string): void {
        for (const handler of [...this.handlers]) notify(handler, path);
    }

    clear(): void {
        this.handlers.clear();
    }
}

class Bridge implements EpicStaffBridge {
    readonly flows: EpicStaffBridge['flows'];
    readonly sessions: EpicStaffBridge['sessions'];
    readonly kv: EpicStaffBridge['kv'];
    readonly nav: NavChannel;
    readonly theme: ThemeChannel;

    private readonly warnedNavCodes = new Set<string>();

    constructor(
        private readonly win: Window,
        private readonly connection: BridgeConnection,
        readonly context: InitContext,
        readonly mocked: boolean,
        private readonly navSync: NavSync | null,
        private readonly applyThemeToDocument: boolean
    ) {
        this.theme = new ThemeChannel(context.theme);
        this.nav = new NavChannel(win, navSync, context.nav.path, connection);
        if (applyThemeToDocument) applyTheme(win.document, context.theme);
        connection.on('theme.changed', (data) => this.handleThemeChanged(data));
        connection.on('nav.navigate', (data) => this.handleNavigate(isRecord(data) ? data['path'] : null));

        const call = this.call.bind(this);
        this.flows = {
            run: (flow, variables = {}) => call('flows.run', { flow, variables }),
            runAndWait: (flow, variables = {}, runOptions = {}) => runAndWait(connection, flow, variables, runOptions),
        };
        this.sessions = {
            get: (sessionId) => call('sessions.get', { session_id: sessionId }),
            subscribe: (sessionId) => call('sessions.subscribe', { session_id: sessionId }),
            unsubscribe: (subscription) => call('sessions.unsubscribe', { subscription }),
            stop: (sessionId) => call('sessions.stop', { session_id: sessionId }),
        };
        this.kv = {
            list: (params) => call('kv.list', params),
            get: <Value>(table: string, key: string) => call('kv.get', { table, key }) as Promise<KvEntry<Value>>,
        };

        navSync?.connect((report) => this.reportNavigation(report), context.nav.path);
    }

    call<Method extends MethodName>(method: Method, ...args: CallArguments<Method>): Promise<MethodResult<Method>> {
        const [params, options] = args;
        return this.connection.call(method, (params ?? {}) as Record<string, unknown>, options ?? {}) as Promise<
            MethodResult<Method>
        >;
    }

    on<Topic extends EventTopic>(topic: Topic, handler: EventHandler<Topic>): () => void {
        return this.connection.on(topic, handler);
    }

    close(): void {
        this.navSync?.uninstall();
        this.connection.close();
        this.theme.clear();
        this.nav.clear();
        connections.delete(this.win);
    }

    private handleThemeChanged(data: unknown): void {
        const theme = parseTheme(data);
        if (this.applyThemeToDocument) applyTheme(this.win.document, theme);
        this.theme.update(theme);
    }

    private handleNavigate(path: unknown): void {
        const target = canonicalNavPath(path);
        if (target === null) return;
        this.navSync?.navigate(target);
        this.nav.dispatch(target);
    }

    private reportNavigation(report: NavReport): void {
        this.connection.call('nav.changed', { path: report.path, replace: report.replace }).catch((error: unknown) => {
            const code = error instanceof BridgeCallError ? error.code : 'internal';
            if (code === 'closed' || this.warnedNavCodes.has(code)) return;
            this.warnedNavCodes.add(code);
            console.warn(`[epicstaff] EpicStaff did not take the navigation to ${report.path} (${code}).`, error);
        });
    }
}

function subscribeTo<Handler>(handlers: Set<Handler>, handler: Handler): () => void {
    handlers.add(handler);
    return () => {
        handlers.delete(handler);
    };
}

/** Reads `init.context` defensively: a malformed field falls back instead of breaking the app. */
function parseContext(raw: unknown): InitContext {
    const context = isRecord(raw) ? raw : {};
    const plugin = isRecord(context['plugin']) ? context['plugin'] : {};
    const nav = isRecord(context['nav']) ? context['nav'] : {};
    return {
        plugin: {
            id: stringOr(plugin['id'], ''),
            version: stringOr(plugin['version'], ''),
            name: stringOr(plugin['name'], ''),
        },
        access: Array.isArray(context['access']) ? context['access'].flatMap(parseAccessEntry) : [],
        nav: { path: canonicalNavPath(nav['path']) ?? '/' },
        theme: parseTheme(context['theme']),
    };
}

function parseAccessEntry(raw: unknown): AccessDescription[] {
    if (!isRecord(raw) || typeof raw['alias'] !== 'string') return [];
    const type = raw['type'];
    if (type !== 'flow' && type !== 'key_value_table') return [];
    const allowed: readonly AccessAction[] = ACCESS_ACTIONS_BY_TYPE[type as AccessType];
    const actions = Array.isArray(raw['actions'])
        ? raw['actions'].filter((action): action is AccessAction => allowed.includes(action as AccessAction))
        : [];
    return [{ alias: raw['alias'], type, actions }];
}

function parseTheme(raw: unknown): ThemeState {
    const theme = isRecord(raw) ? raw : {};
    const tokens: Record<`--es-${string}`, string> = {};
    if (isRecord(theme['tokens'])) {
        for (const [name, value] of Object.entries(theme['tokens'])) {
            if (name.startsWith('--es-') && typeof value === 'string') tokens[name as `--es-${string}`] = value;
        }
    }
    return { mode: normalizeThemeMode(theme['mode']), tokens };
}

function stringOr(value: unknown, fallback: string): string {
    return typeof value === 'string' ? value : fallback;
}
