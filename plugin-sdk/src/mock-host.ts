import { canonicalNavPath } from './nav-path.js';
import type { NavReport } from './nav-sync.js';
import {
    type AccessAction,
    type AccessDescription,
    type AccessType,
    BRIDGE_LIMITS,
    BRIDGE_VERSION,
    type BridgeErrorBody,
    type BridgeErrorCode,
    type EventMessage,
    type EventTopic,
    type BridgeEvents,
    type HandshakeErrorMessage,
    type InitMessage,
    isRecord,
    isRequestId,
    isValidKvKey,
    KV_KEY_MAX_LENGTH,
    KV_LIST_DEFAULT_LIMIT,
    KV_LIST_MAX_LIMIT,
    KV_ORDERINGS,
    KV_SEARCH_MAX_LENGTH,
    KV_VALUE_PREVIEW_CHARS,
    type KvEntry,
    type KvListItem,
    type KvOrdering,
    METHOD_PARAM_KEYS,
    type MethodName,
    type PluginIdentity,
    type RequestId,
    type SessionMessageData,
    TERMINAL_SESSION_STATUSES,
    type ThemeState,
} from './protocol.js';

/** Runs one mocked flow: gets the run's `variables`, returns what the End node would output. Throw to fail the run. */
export type MockFlowHandler = (variables: Record<string, unknown>, context: MockFlowContext) => unknown;

export interface MockFlowContext {
    readonly sessionId: number;
    /** The mock's key-value tables, so a mocked flow can write rows like the real flow does. */
    readonly kv: MockKeyValueStore;
}

/** A seed row; timestamps default to "now". */
export interface MockKvEntry {
    key: string;
    value: unknown;
    created_at?: string;
    updated_at?: string;
}

/** The mock's key-value tables, keyed by the table alias. */
export interface MockKeyValueStore {
    get(table: string, key: string): KvEntry | null;
    set(table: string, key: string, value: unknown): KvEntry;
    delete(table: string, key: string): boolean;
    list(table: string): KvEntry[];
}

export interface MockHostOptions {
    plugin?: Partial<PluginIdentity>;
    /** Default: every flow in `flows` with all flow actions, every table in `kvTables` with `read`. */
    access?: readonly AccessDescription[];
    flows?: Readonly<Record<string, MockFlowHandler>>;
    kvTables?: Readonly<Record<string, readonly MockKvEntry[]>>;
    /** Default: EpicStaff's dark theme. */
    theme?: ThemeState;
    /** The path `init` reports. Default: the path the app's URL shows at the handshake. */
    initialPath?: string;
    /** Delay before each answer, in ms. Default 120. */
    latencyMs?: number;
    /** How long a subscription stays open after a final status, in ms. EpicStaff waits 3000. Default 300. */
    closeGraceMs?: number;
    /** Called for every accepted `nav.changed`. */
    onNavChanged?: (report: NavReport) => void;
}

export type MockHandshakeResult =
    | { ok: true; init: InitMessage; port: MessagePort }
    | { ok: false; error: HandshakeErrorMessage };

/** A stand-in for EpicStaff that answers the bridge v2 protocol from local data. */
export interface MockHost {
    readonly kv: MockKeyValueStore;
    /** Every accepted `nav.changed`, oldest first. */
    readonly navChanges: readonly NavReport[];
    /** Answers the app's `ready` as EpicStaff would. A second handshake resets the first (like dev mode). */
    handshake(ready: unknown, page?: { path?: string | null }): MockHandshakeResult;
    /** Sends `nav.navigate`, as EpicStaff does after Back/Forward or a sidenav click. */
    navigate(path: string): void;
    /** Sends `theme.changed`. */
    setTheme(theme: ThemeState): void;
    close(): void;
}

/** EpicStaff's dark theme tokens (the default). */
export const MOCK_DARK_THEME: ThemeState = {
    mode: 'dark',
    tokens: {
        '--es-color-background': '#212325',
        '--es-color-surface': '#232323',
        '--es-color-surface-raised': '#222225',
        '--es-color-sidenav': '#222225',
        '--es-color-text': '#d9d9de',
        '--es-color-text-secondary': 'rgba(217, 217, 222, 0.6)',
        '--es-color-text-tertiary': 'rgba(217, 217, 222, 0.4)',
        '--es-color-text-disabled': '#676767',
        '--es-color-accent': '#685fff',
        '--es-color-accent-hover': '#574fd6',
        '--es-color-accent-active': '#473fb3',
        '--es-color-input-background': '#27272b',
        '--es-color-input-border': '#c8ceda24',
        '--es-color-input-placeholder': '#c8ceda4d',
        '--es-color-border': '#c8ceda24',
        '--es-color-divider': '#c8ceda24',
        '--es-color-divider-subtle': '#c8ceda14',
        '--es-color-success': '#2aba6b',
        '--es-color-warning': '#f5a623',
        '--es-color-error': '#f54242',
        '--es-focus-ring': '0 0 0 2px rgba(104, 95, 255, 0.4)',
        '--es-font-family': "Inter, 'Helvetica Neue', sans-serif",
    },
};

/** EpicStaff's light theme tokens. */
export const MOCK_LIGHT_THEME: ThemeState = {
    mode: 'light',
    tokens: {
        ...MOCK_DARK_THEME.tokens,
        '--es-color-background': '#f8fafc',
        '--es-color-surface': '#ffffff',
        '--es-color-surface-raised': '#ffffff',
        '--es-color-sidenav': '#ffffff',
        '--es-color-text': '#1e293b',
        '--es-color-text-secondary': '#64748b',
        '--es-color-text-tertiary': 'rgba(30, 41, 59, 0.4)',
        '--es-color-text-disabled': '#cbd5e1',
        '--es-color-input-background': '#ffffff',
        '--es-color-input-border': '#e2e8f0',
        '--es-color-input-placeholder': '#94a3b8',
        '--es-color-border': '#e2e8f0',
        '--es-color-divider': '#e2e8f0',
        '--es-color-divider-subtle': '#f1f5f9',
    },
};

const DEFAULT_PLUGIN: PluginIdentity = { id: 'mock-plugin', version: '0.0.0', name: 'Mock plugin' };
const ENVELOPE_KEYS: ReadonlySet<string> = new Set(['v', 'kind', 'id', 'method', 'params']);
const RATE_WINDOW_MS = 60_000;
const SESSION_NOT_FOUND = 'No session with that id is available to this plugin.';

export function createMockHost(options: MockHostOptions = {}): MockHost {
    return new MockBridgeHost(options);
}

class MockError extends Error {
    constructor(
        readonly code: BridgeErrorCode,
        message: string
    ) {
        super(message);
    }

    toBody(): BridgeErrorBody {
        return { code: this.code, message: this.message };
    }
}

interface MockSession {
    readonly id: number;
    readonly flow: string;
    readonly variables: Record<string, unknown>;
    readonly messages: SessionMessageData[];
    status: string | null;
    output: unknown;
}

interface Answer {
    result: unknown;
    /** Runs right after the response is posted (a subscription replays history only then). */
    after?: () => void;
}

class MockKeyValueTables implements MockKeyValueStore {
    private readonly tables = new Map<string, Map<string, KvEntry>>();

    constructor(seed: Readonly<Record<string, readonly MockKvEntry[]>>) {
        for (const [table, entries] of Object.entries(seed)) {
            const rows = this.table(table);
            for (const entry of entries) {
                const created = entry.created_at ?? new Date().toISOString();
                rows.set(entry.key, {
                    key: entry.key,
                    value: structuredClone(entry.value),
                    created_at: created,
                    updated_at: entry.updated_at ?? created,
                });
            }
        }
    }

    get(table: string, key: string): KvEntry | null {
        const entry = this.tables.get(table)?.get(key);
        return entry ? structuredClone(entry) : null;
    }

    set(table: string, key: string, value: unknown): KvEntry {
        if (!isValidKvKey(key)) throw new Error(`"${String(key).slice(0, 64)}" is not a valid key-value key.`);
        const rows = this.table(table);
        const now = new Date().toISOString();
        const entry: KvEntry = {
            key,
            value: structuredClone(value),
            created_at: rows.get(key)?.created_at ?? now,
            updated_at: now,
        };
        rows.set(key, entry);
        return structuredClone(entry);
    }

    delete(table: string, key: string): boolean {
        return this.tables.get(table)?.delete(key) ?? false;
    }

    list(table: string): KvEntry[] {
        return [...(this.tables.get(table)?.values() ?? [])].map((entry) => structuredClone(entry));
    }

    private table(name: string): Map<string, KvEntry> {
        let rows = this.tables.get(name);
        if (!rows) {
            rows = new Map();
            this.tables.set(name, rows);
        }
        return rows;
    }
}

class MockBridgeHost implements MockHost {
    readonly kv: MockKeyValueStore;
    readonly navChanges: NavReport[] = [];

    private readonly plugin: PluginIdentity;
    private readonly access: readonly AccessDescription[];
    private readonly flows: Readonly<Record<string, MockFlowHandler>>;
    private readonly latencyMs: number;
    private readonly closeGraceMs: number;
    private readonly sessions = new Map<number, MockSession>();
    private readonly subscriptions = new Map<string, number>();
    private readonly timers = new Set<ReturnType<typeof setTimeout>>();
    private readonly encoder = new TextEncoder();
    private theme: ThemeState;
    private port: MessagePort | null = null;
    private nextSessionId = 1001;
    private subscriptionCounter = 0;
    private inFlight = 0;
    private runTimes: number[] = [];
    private navTimes: number[] = [];

    constructor(private readonly options: MockHostOptions) {
        this.plugin = { ...DEFAULT_PLUGIN, ...options.plugin };
        this.flows = options.flows ?? {};
        this.access = (options.access ?? defaultAccess(options)).map((entry) => ({
            alias: entry.alias,
            type: entry.type,
            actions: [...entry.actions],
        }));
        this.kv = new MockKeyValueTables(options.kvTables ?? {});
        this.theme = options.theme ?? MOCK_DARK_THEME;
        this.latencyMs = options.latencyMs ?? 120;
        this.closeGraceMs = options.closeGraceMs ?? 300;
    }

    handshake(ready: unknown, page: { path?: string | null } = {}): MockHandshakeResult {
        const version = isRecord(ready) && typeof ready['v'] === 'number' ? ready['v'] : null;
        if (!isRecord(ready) || ready['kind'] !== 'ready' || version !== BRIDGE_VERSION) {
            return {
                ok: false,
                error: {
                    v: BRIDGE_VERSION,
                    kind: 'error',
                    error: {
                        code: 'unsupported',
                        message: `This plugin declares bridge version ${BRIDGE_VERSION}; the page asked for ${version}.`,
                    },
                },
            };
        }
        this.reset();
        const channel = new MessageChannel();
        this.port = channel.port1;
        this.port.onmessage = (event: MessageEvent) => this.handleRequest(event.data);
        const path = canonicalNavPath(this.options.initialPath ?? page.path ?? '/') ?? '/';
        const init: InitMessage = {
            v: BRIDGE_VERSION,
            kind: 'init',
            context: {
                plugin: { ...this.plugin },
                access: this.access.map((entry) => ({ ...entry, actions: [...entry.actions] })),
                nav: { path },
                theme: structuredClone(this.theme),
            },
        };
        return { ok: true, init, port: channel.port2 };
    }

    navigate(path: string): void {
        const canonical = canonicalNavPath(path);
        if (canonical === null) throw new Error(`"${path}" is not a valid plugin path.`);
        this.postEvent('nav.navigate', null, { path: canonical });
    }

    setTheme(theme: ThemeState): void {
        this.theme = structuredClone(theme);
        this.postEvent('theme.changed', null, structuredClone(theme));
    }

    close(): void {
        this.reset();
    }

    private reset(): void {
        this.timers.forEach((timer) => clearTimeout(timer));
        this.timers.clear();
        this.sessions.clear();
        this.subscriptions.clear();
        this.inFlight = 0;
        if (this.port) {
            this.port.onmessage = null;
            this.port.close();
            this.port = null;
        }
    }

    // --- requests -------------------------------------------------------------------------------

    private handleRequest(data: unknown): void {
        if (!isRecord(data) || !isRequestId(data['id'])) return;
        const id = data['id'];
        try {
            const { method, params } = this.parseRequest(data);
            if (this.inFlight >= BRIDGE_LIMITS.maxInFlight) {
                throw new MockError(
                    'rate_limited',
                    `At most ${BRIDGE_LIMITS.maxInFlight} requests may wait for an answer.`
                );
            }
            this.inFlight++;
            this.later(this.latencyMs, () => {
                this.inFlight--;
                let answer: Answer;
                try {
                    answer = this.invoke(method, params);
                } catch (error) {
                    this.respondError(id, error);
                    return;
                }
                this.post({ v: BRIDGE_VERSION, kind: 'response', id, ok: true, result: answer.result });
                answer.after?.();
            });
        } catch (error) {
            this.respondError(id, error);
        }
    }

    private parseRequest(data: Record<string, unknown>): { method: MethodName; params: Record<string, unknown> } {
        let json: string;
        try {
            json = JSON.stringify(data);
        } catch {
            throw new MockError('bad_request', 'The request must be plain JSON data.');
        }
        if (this.encoder.encode(json).length > BRIDGE_LIMITS.maxRequestBytes) {
            throw new MockError(
                'bad_request',
                `The request is larger than ${BRIDGE_LIMITS.maxRequestBytes / 1024} KB.`
            );
        }
        if (data['kind'] !== 'request')
            throw new MockError('bad_request', 'Expected {v, kind: "request", id, method, params}.');
        if (data['v'] !== BRIDGE_VERSION)
            throw new MockError('unsupported', `This plugin uses bridge version ${BRIDGE_VERSION}.`);
        if (Object.keys(data).some((key) => !ENVELOPE_KEYS.has(key))) {
            throw new MockError('bad_request', 'The request has unknown fields.');
        }
        const method = data['method'];
        if (typeof method !== 'string' || method === '')
            throw new MockError('bad_request', '"method" must be a method name.');
        const params = data['params'] ?? {};
        if (!isRecord(params)) throw new MockError('bad_request', '"params" must be an object.');
        if (!Object.hasOwn(METHOD_PARAM_KEYS, method)) {
            throw new MockError('unsupported', `Unknown method "${method.slice(0, 64)}".`);
        }
        const known = METHOD_PARAM_KEYS[method as MethodName];
        const unknownKey = Object.keys(params).find((key) => !known.includes(key));
        if (unknownKey !== undefined) {
            throw new MockError('bad_request', `Unknown param "${unknownKey.slice(0, 64)}" for ${method}.`);
        }
        return { method: method as MethodName, params: structuredClone(params) };
    }

    private invoke(method: MethodName, params: Record<string, unknown>): Answer {
        switch (method) {
            case 'bridge.hello':
                return {
                    result: {
                        bridge_version: BRIDGE_VERSION,
                        plugin: { ...this.plugin },
                        access: structuredClone(this.access),
                        methods: Object.keys(METHOD_PARAM_KEYS),
                    },
                };
            case 'flows.run':
                return { result: this.runFlow(params) };
            case 'sessions.get': {
                const session = this.ownSession(params, 'sessions.read');
                const output = isRecord(session.output) ? session.output : {};
                return {
                    result: {
                        status: session.status ?? 'pending',
                        variables: { ...session.variables, ...output },
                        flow: session.flow,
                    },
                };
            }
            case 'sessions.subscribe':
                return this.subscribe(params);
            case 'sessions.unsubscribe': {
                const subscription = params['subscription'];
                if (typeof subscription !== 'string' || subscription === '') {
                    throw new MockError('bad_request', '"subscription" must be a subscription id.');
                }
                if (!this.subscriptions.delete(subscription))
                    throw new MockError('not_found', 'No open subscription with that id.');
                return { result: {} };
            }
            case 'sessions.stop': {
                const session = this.ownSession(params, 'sessions.stop');
                if (!isTerminal(session)) this.setStatus(session, 'stop');
                return { result: {} };
            }
            case 'kv.list':
                return { result: this.listEntries(params) };
            case 'kv.get':
                return { result: this.getEntry(params) };
            case 'nav.changed':
                return { result: this.navChanged(params) };
        }
    }

    private runFlow(params: Record<string, unknown>): { session_id: number } {
        const variables = params['variables'] ?? {};
        if (!isRecord(variables)) throw new MockError('bad_request', '"variables" must be an object.');
        const flow = this.resolve(params['flow'], 'flow', 'run');
        this.runTimes = consumeRate(this.runTimes, BRIDGE_LIMITS.maxRunsPerMinute, 'flow runs');

        const session: MockSession = {
            id: this.nextSessionId++,
            flow,
            variables: structuredClone(variables),
            messages: [],
            status: null,
            output: undefined,
        };
        this.sessions.set(session.id, session);
        this.setStatus(session, 'pending');
        this.later(this.latencyMs, () => this.execute(session));
        return { session_id: session.id };
    }

    private execute(session: MockSession): void {
        if (isTerminal(session)) return;
        this.setStatus(session, 'run');
        const handler = Object.hasOwn(this.flows, session.flow) ? this.flows[session.flow] : undefined;
        const context: MockFlowContext = { sessionId: session.id, kv: this.kv };
        Promise.resolve()
            .then(() => (handler ? handler(structuredClone(session.variables), context) : {}))
            .then(
                (output: unknown) => {
                    if (isTerminal(session) || !this.sessions.has(session.id)) return;
                    session.output = output;
                    this.addMessage(session, {
                        message_type: 'graph_end',
                        name: 'End',
                        created_at: new Date().toISOString(),
                        message_data: { message_type: 'graph_end', end_node_result: output ?? {} },
                    });
                    this.setStatus(session, 'end');
                },
                (error: unknown) => {
                    if (isTerminal(session) || !this.sessions.has(session.id)) return;
                    this.addMessage(session, {
                        message_type: 'error',
                        name: 'Error',
                        created_at: new Date().toISOString(),
                        message_data: {
                            message_type: 'error',
                            details: error instanceof Error ? error.message : String(error),
                        },
                    });
                    this.setStatus(session, 'error');
                }
            );
    }

    private subscribe(params: Record<string, unknown>): Answer {
        const session = this.ownSession(params, 'sessions.read');
        if (this.subscriptions.size >= BRIDGE_LIMITS.maxSubscriptions) {
            throw new MockError('rate_limited', `At most ${BRIDGE_LIMITS.maxSubscriptions} subscriptions may be open.`);
        }
        const subscription = `sub-${++this.subscriptionCounter}`;
        this.subscriptions.set(subscription, session.id);
        return {
            result: { subscription },
            after: () => {
                for (const message of session.messages) this.postEvent('session.message', subscription, message);
                if (session.status !== null) this.postEvent('session.status', subscription, { status: session.status });
                if (isTerminal(session)) this.closeLater(subscription);
            },
        };
    }

    private ownSession(params: Record<string, unknown>, action: 'sessions.read' | 'sessions.stop'): MockSession {
        const sessionId = params['session_id'];
        if (typeof sessionId !== 'number' || !Number.isSafeInteger(sessionId) || sessionId <= 0) {
            throw new MockError('bad_request', '"session_id" must be a positive integer.');
        }
        if (!this.access.some((entry) => entry.actions.includes(action))) {
            throw new MockError('forbidden', `This plugin may not "${action}" anything.`);
        }
        const session = this.sessions.get(sessionId);
        const grant = session ? this.grant(session.flow) : undefined;
        if (!session || !grant || grant.type !== 'flow' || !grant.actions.includes(action)) {
            throw new MockError('not_found', SESSION_NOT_FOUND);
        }
        return session;
    }

    private listEntries(params: Record<string, unknown>): { count: number; items: KvListItem[] } {
        const table = this.resolve(params['table'], 'key_value_table', 'read');
        const search = params['search'];
        if (search !== undefined && (typeof search !== 'string' || search.length > KV_SEARCH_MAX_LENGTH)) {
            throw new MockError(
                'bad_request',
                `"search" must be a string of at most ${KV_SEARCH_MAX_LENGTH} characters.`
            );
        }
        const ordering = params['ordering'] ?? 'key';
        if (typeof ordering !== 'string' || !(KV_ORDERINGS as readonly string[]).includes(ordering)) {
            throw new MockError('bad_request', `"ordering" must be one of ${KV_ORDERINGS.join(', ')}.`);
        }
        const limit = params['limit'] ?? KV_LIST_DEFAULT_LIMIT;
        if (!Number.isSafeInteger(limit) || (limit as number) < 1 || (limit as number) > KV_LIST_MAX_LIMIT) {
            throw new MockError('bad_request', `"limit" must be an integer from 1 to ${KV_LIST_MAX_LIMIT}.`);
        }
        const offset = params['offset'] ?? 0;
        if (!Number.isSafeInteger(offset) || (offset as number) < 0) {
            throw new MockError('bad_request', '"offset" must be an integer of at least 0.');
        }

        const terms = (search ?? '')
            .toLowerCase()
            .split(/[\s,]+/)
            .filter((term) => term !== '');
        const matches = this.kv
            .list(table)
            .filter((entry) => terms.every((term) => entry.key.toLowerCase().includes(term)))
            .sort(compareEntries(ordering as KvOrdering));
        const page = matches.slice(offset as number, (offset as number) + (limit as number));
        return {
            count: matches.length,
            items: page.map((entry) => {
                const text = jsonbText(entry.value);
                const characters = Array.from(text);
                return {
                    key: entry.key,
                    value_preview: characters.slice(0, KV_VALUE_PREVIEW_CHARS).join(''),
                    value_truncated: characters.length > KV_VALUE_PREVIEW_CHARS,
                    created_at: entry.created_at,
                    updated_at: entry.updated_at,
                };
            }),
        };
    }

    private getEntry(params: Record<string, unknown>): KvEntry {
        if (!isValidKvKey(params['key'])) {
            throw new MockError(
                'bad_request',
                `"key" must match ^[A-Za-z_][A-Za-z0-9_]*$ and have at most ${KV_KEY_MAX_LENGTH} characters.`
            );
        }
        const table = this.resolve(params['table'], 'key_value_table', 'read');
        const entry = this.kv.get(table, params['key']);
        if (!entry) throw new MockError('not_found', 'No entry with that key.');
        return entry;
    }

    private navChanged(params: Record<string, unknown>): Record<string, never> {
        const path = canonicalNavPath(params['path']);
        if (path === null) throw new MockError('bad_request', '"path" is not a valid plugin path.');
        const replace = params['replace'] ?? false;
        if (typeof replace !== 'boolean') throw new MockError('bad_request', '"replace" must be true or false.');
        this.navTimes = consumeRate(this.navTimes, BRIDGE_LIMITS.maxNavChangesPerMinute, 'navigation reports');
        const report: NavReport = { path, replace };
        this.navChanges.push(report);
        this.options.onNavChanged?.(report);
        return {};
    }

    private resolve(alias: unknown, type: AccessType, action: AccessAction): string {
        const grant = typeof alias === 'string' ? this.grant(alias) : undefined;
        if (!grant || grant.type !== type) {
            const name = typeof alias === 'string' ? `"${alias.slice(0, 64)}"` : 'with that alias';
            throw new MockError('forbidden', `This plugin has no access to a ${type} ${name}.`);
        }
        if (!grant.actions.includes(action)) {
            throw new MockError('forbidden', `This plugin may not "${action}" the ${type} "${grant.alias}".`);
        }
        return grant.alias;
    }

    private grant(alias: string): AccessDescription | undefined {
        return this.access.find((entry) => entry.alias === alias);
    }

    // --- sessions and events --------------------------------------------------------------------

    private setStatus(session: MockSession, status: string): void {
        session.status = status;
        for (const subscription of this.subscriptionsOf(session)) {
            this.postEvent('session.status', subscription, { status });
            if (isTerminal(session)) this.closeLater(subscription);
        }
    }

    private addMessage(session: MockSession, message: SessionMessageData): void {
        session.messages.push(message);
        for (const subscription of this.subscriptionsOf(session))
            this.postEvent('session.message', subscription, message);
    }

    private closeLater(subscription: string): void {
        this.later(this.closeGraceMs, () => {
            if (!this.subscriptions.delete(subscription)) return;
            this.postEvent('subscription.closed', subscription, { reason: 'ended' });
        });
    }

    private subscriptionsOf(session: MockSession): string[] {
        return [...this.subscriptions]
            .filter(([, sessionId]) => sessionId === session.id)
            .map(([subscription]) => subscription);
    }

    private postEvent<Topic extends EventTopic>(
        topic: Topic,
        subscription: string | null,
        data: BridgeEvents[Topic]
    ): void {
        const event: EventMessage<Topic> = { v: BRIDGE_VERSION, kind: 'event', topic, subscription, data };
        this.post(event);
    }

    private respondError(id: RequestId, error: unknown): void {
        const body =
            error instanceof MockError
                ? error.toBody()
                : { code: 'internal' as const, message: 'The mock host failed.' };
        this.post({ v: BRIDGE_VERSION, kind: 'response', id, ok: false, error: body });
    }

    private post(message: unknown): void {
        this.port?.postMessage(message);
    }

    private later(delayMs: number, task: () => void): void {
        const timer = setTimeout(() => {
            this.timers.delete(timer);
            task();
        }, delayMs);
        this.timers.add(timer);
    }
}

function defaultAccess(options: MockHostOptions): AccessDescription[] {
    return [
        ...Object.keys(options.flows ?? {}).map(
            (alias): AccessDescription => ({ alias, type: 'flow', actions: ['run', 'sessions.read', 'sessions.stop'] })
        ),
        ...Object.keys(options.kvTables ?? {}).map(
            (alias): AccessDescription => ({ alias, type: 'key_value_table', actions: ['read'] })
        ),
    ];
}

function isTerminal(session: MockSession): boolean {
    return session.status !== null && TERMINAL_SESSION_STATUSES.has(session.status);
}

function consumeRate(times: readonly number[], limit: number, what: string): number[] {
    const now = Date.now();
    const recent = times.filter((time) => now - time < RATE_WINDOW_MS);
    if (recent.length >= limit) throw new MockError('rate_limited', `At most ${limit} ${what} per minute.`);
    return [...recent, now];
}

function compareEntries(ordering: KvOrdering): (left: KvEntry, right: KvEntry) => number {
    const descending = ordering.startsWith('-');
    const field = descending ? ordering.slice(1) : ordering;
    return (left, right) => {
        const primary =
            field === 'key' ? compareText(left.key, right.key) : compareText(left.updated_at, right.updated_at);
        const result = primary !== 0 ? primary : compareText(left.key, right.key);
        return descending ? -result : result;
    };
}

function compareText(left: string, right: string): number {
    if (left === right) return 0;
    return left < right ? -1 : 1;
}

/**
 * A value's JSON text as Postgres `jsonb` prints it, which is what `value_preview` is cut from:
 * object keys shortest first (then by byte order), `", "` and `": "` separators.
 */
export function jsonbText(value: unknown): string {
    if (value === null || value === undefined) return 'null';
    if (Array.isArray(value)) return '[' + value.map((item) => jsonbText(item)).join(', ') + ']';
    if (isRecord(value)) {
        const keys = Object.keys(value).sort((left, right) => left.length - right.length || compareText(left, right));
        return '{' + keys.map((key) => `${JSON.stringify(key)}: ${jsonbText(value[key])}`).join(', ') + '}';
    }
    return JSON.stringify(value) ?? 'null';
}
