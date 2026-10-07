/**
 * EpicStaff plugin bridge, version 2: every message a plugin app and EpicStaff exchange.
 *
 * Handshake: the app posts `{v: 2, kind: "ready"}` to `window.parent`; EpicStaff answers with
 * `{v: 2, kind: "init", context}` and transfers one `MessagePort`. All later traffic uses the port:
 * requests from the app, responses and events from EpicStaff. Every message carries `v`.
 *
 * Version 2 keeps every v1 method, envelope, error code and limit, and adds `kv.list`, `kv.get`,
 * `nav.changed`, the host events `nav.navigate` / `theme.changed`, and `nav` / `theme` in `init`.
 */

export const BRIDGE_VERSION = 2;

export const BRIDGE_ERROR_CODES = [
    'bad_request',
    'forbidden',
    'not_found',
    'rate_limited',
    'unsupported',
    'internal',
] as const;

/** An error code EpicStaff answers with. */
export type BridgeErrorCode = (typeof BRIDGE_ERROR_CODES)[number];

export interface BridgeErrorBody {
    code: BridgeErrorCode;
    message: string;
}

/** Limits EpicStaff enforces per open plugin app. */
export const BRIDGE_LIMITS = {
    /** One request, measured as UTF-8 JSON. Over it: `bad_request`. */
    maxRequestBytes: 64 * 1024,
    /** Requests waiting for their response. Over it: `rate_limited`. */
    maxInFlight: 10,
    /** Open `sessions.subscribe` streams. Over it: `rate_limited`. */
    maxSubscriptions: 4,
    /** `flows.run` calls in any 60-second window. Over it: `rate_limited`. */
    maxRunsPerMinute: 20,
    /** `nav.changed` calls in any 60-second window. Over it: `rate_limited`. */
    maxNavChangesPerMinute: 120,
} as const;

// ---------------------------------------------------------------------------------------------
// Access list and init context
// ---------------------------------------------------------------------------------------------

export type AccessType = 'flow' | 'key_value_table';
export type FlowAction = 'run' | 'sessions.read' | 'sessions.stop';
export type KeyValueTableAction = 'read';
export type AccessAction = FlowAction | KeyValueTableAction;

export const ACCESS_ACTIONS_BY_TYPE: Readonly<Record<AccessType, readonly AccessAction[]>> = {
    flow: ['run', 'sessions.read', 'sessions.stop'],
    key_value_table: ['read'],
};

/** One access entry as the app sees it: an alias, never a database id. */
export interface AccessDescription {
    alias: string;
    type: AccessType;
    actions: AccessAction[];
}

/** `id` is the manifest id (for example `chat-admin`), not a database id. */
export interface PluginIdentity {
    id: string;
    version: string;
    name: string;
}

export type ThemeMode = 'dark' | 'light';

/** The stable public token set. EpicStaff only ever adds tokens; it never renames one. */
export const THEME_TOKENS = [
    '--es-color-background',
    '--es-color-surface',
    '--es-color-surface-raised',
    '--es-color-sidenav',
    '--es-color-text',
    '--es-color-text-secondary',
    '--es-color-text-tertiary',
    '--es-color-text-disabled',
    '--es-color-accent',
    '--es-color-accent-hover',
    '--es-color-accent-active',
    '--es-color-input-background',
    '--es-color-input-border',
    '--es-color-input-placeholder',
    '--es-color-border',
    '--es-color-divider',
    '--es-color-divider-subtle',
    '--es-color-success',
    '--es-color-warning',
    '--es-color-error',
    '--es-focus-ring',
    '--es-font-family',
] as const;

export type ThemeToken = (typeof THEME_TOKENS)[number];

/** CSS custom properties keyed by name (`--es-…`, see {@link THEME_TOKENS}), values as CSS text. */
export type ThemeTokens = Readonly<Record<`--es-${string}`, string>>;

export interface ThemeState {
    mode: ThemeMode;
    tokens: ThemeTokens;
}

export interface NavState {
    /** The app path EpicStaff's address bar shows, for example `/conversations/c_…?page=2`. */
    path: string;
}

export interface InitContext {
    plugin: PluginIdentity;
    access: AccessDescription[];
    nav: NavState;
    theme: ThemeState;
}

// ---------------------------------------------------------------------------------------------
// Envelope
// ---------------------------------------------------------------------------------------------

/** A request id is chosen by the app: a string of at most 64 characters or a safe integer. */
export type RequestId = string | number;

export interface ReadyMessage {
    v: number;
    kind: 'ready';
}

export interface InitMessage {
    v: number;
    kind: 'init';
    context: InitContext;
}

/** Posted on `window` instead of `init` when the handshake can't complete (for example a wrong `v`). */
export interface HandshakeErrorMessage {
    v: number;
    kind: 'error';
    error: BridgeErrorBody;
}

export interface RequestMessage {
    v: number;
    kind: 'request';
    id: RequestId;
    method: string;
    params: Record<string, unknown>;
}

export interface SuccessResponseMessage {
    v: number;
    kind: 'response';
    id: RequestId;
    ok: true;
    result: unknown;
}

export interface ErrorResponseMessage {
    v: number;
    kind: 'response';
    id: RequestId;
    ok: false;
    error: BridgeErrorBody;
}

export type ResponseMessage = SuccessResponseMessage | ErrorResponseMessage;

/** Events on a session subscription carry its id; host-pushed topics carry `subscription: null`. */
export interface EventMessage<Topic extends EventTopic = EventTopic> {
    v: number;
    kind: 'event';
    topic: Topic;
    subscription: string | null;
    data: BridgeEvents[Topic];
}

// ---------------------------------------------------------------------------------------------
// Methods
// ---------------------------------------------------------------------------------------------

export type EmptyParams = Record<string, never>;
export type EmptyResult = Record<string, never>;

export interface HelloResult {
    bridge_version: number;
    plugin: PluginIdentity;
    access: AccessDescription[];
    methods: string[];
}

export interface FlowsRunParams {
    /** The flow's alias from the access list. */
    flow: string;
    variables?: Record<string, unknown>;
}

export interface FlowsRunResult {
    session_id: number;
}

export interface SessionParams {
    session_id: number;
}

export interface SessionRecord {
    status: string;
    variables: Record<string, unknown>;
    /** The alias of the session's flow. */
    flow: string;
}

export interface SubscribeResult {
    subscription: string;
}

export interface UnsubscribeParams {
    subscription: string;
}

export type KvOrdering = 'key' | '-key' | 'updated_at' | '-updated_at';

export const KV_ORDERINGS: readonly KvOrdering[] = ['key', '-key', 'updated_at', '-updated_at'];

export interface KvListParams {
    /** The table's alias from the access list. */
    table: string;
    /** Case-insensitive search in keys, at most 512 characters. */
    search?: string;
    /** Default `"key"`. */
    ordering?: KvOrdering;
    /** 1..100, default 20. */
    limit?: number;
    /** ≥ 0, default 0. */
    offset?: number;
}

export interface KvListItem {
    key: string;
    /** The first 200 characters of the value's JSON text. */
    value_preview: string;
    value_truncated: boolean;
    created_at: string;
    updated_at: string;
}

export interface KvListResult {
    count: number;
    items: KvListItem[];
}

export interface KvGetParams {
    table: string;
    /** `^[A-Za-z_][A-Za-z0-9_]*$`, at most 512 characters. */
    key: string;
}

export interface KvEntry<Value = unknown> {
    key: string;
    value: Value;
    created_at: string;
    updated_at: string;
}

export interface NavChangedParams {
    path: string;
    /** `true`: replace EpicStaff's history entry; otherwise push one. */
    replace?: boolean;
}

/** Every v2 method with its params and result. */
export interface BridgeMethods {
    'bridge.hello': { params: EmptyParams; result: HelloResult };
    'flows.run': { params: FlowsRunParams; result: FlowsRunResult };
    'sessions.get': { params: SessionParams; result: SessionRecord };
    'sessions.subscribe': { params: SessionParams; result: SubscribeResult };
    'sessions.unsubscribe': { params: UnsubscribeParams; result: EmptyResult };
    'sessions.stop': { params: SessionParams; result: EmptyResult };
    'kv.list': { params: KvListParams; result: KvListResult };
    'kv.get': { params: KvGetParams; result: KvEntry };
    'nav.changed': { params: NavChangedParams; result: EmptyResult };
}

export type MethodName = keyof BridgeMethods;
export type MethodParams<Method extends MethodName> = BridgeMethods[Method]['params'];
export type MethodResult<Method extends MethodName> = BridgeMethods[Method]['result'];

/** Every param each method accepts; any other key is `bad_request`. */
export const METHOD_PARAM_KEYS: Readonly<Record<MethodName, readonly string[]>> = {
    'bridge.hello': [],
    'flows.run': ['flow', 'variables'],
    'sessions.get': ['session_id'],
    'sessions.subscribe': ['session_id'],
    'sessions.unsubscribe': ['subscription'],
    'sessions.stop': ['session_id'],
    'kv.list': ['table', 'search', 'ordering', 'limit', 'offset'],
    'kv.get': ['table', 'key'],
    'nav.changed': ['path', 'replace'],
};

// ---------------------------------------------------------------------------------------------
// Events
// ---------------------------------------------------------------------------------------------

/** `session.message`: one flow message. `graph_end` carries `message_data.end_node_result`. */
export interface SessionMessageData {
    message_type: string | null;
    name: string;
    created_at: string | null;
    message_data: unknown;
}

export interface SessionStatusData {
    status: string;
}

/** `ended`: the session reached a final status. `error`: the stream failed and gave up. */
export interface SubscriptionClosedData {
    reason: 'ended' | 'error';
}

export interface NavNavigateData {
    path: string;
}

export interface BridgeEvents {
    'session.message': SessionMessageData;
    'session.status': SessionStatusData;
    'subscription.closed': SubscriptionClosedData;
    'nav.navigate': NavNavigateData;
    'theme.changed': ThemeState;
}

export type EventTopic = keyof BridgeEvents;

/** Session statuses as EpicStaff reports them. */
export const SESSION_STATUSES = ['pending', 'run', 'wait_for_user', 'end', 'error', 'stop', 'expired'] as const;

/** Final statuses that mean the flow did not finish normally. */
export const FAILED_SESSION_STATUSES: ReadonlySet<string> = new Set(['error', 'stop', 'expired']);

/** Every final status. */
export const TERMINAL_SESSION_STATUSES: ReadonlySet<string> = new Set(['end', 'error', 'stop', 'expired']);

// ---------------------------------------------------------------------------------------------
// Value grammar shared by the client, the mock host and EpicStaff
// ---------------------------------------------------------------------------------------------

export const NAV_PATH_MAX_LENGTH = 1024;

export const NAV_PATH_PATTERN = /^\/([A-Za-z0-9\-._~%]+(\/[A-Za-z0-9\-._~%]+)*)?(\?[A-Za-z0-9\-._~%=&+]*)?$/;

/**
 * True for a path EpicStaff accepts in `nav.changed`: the grammar above, at most 1024 characters,
 * every `%` escape decodable as UTF-8, and no `.` / `..` segment (also when `%`-encoded).
 */
export function isValidNavPath(path: unknown): path is string {
    if (typeof path !== 'string' || path.length > NAV_PATH_MAX_LENGTH || !NAV_PATH_PATTERN.test(path)) return false;
    const queryStart = path.indexOf('?');
    const pathname = queryStart === -1 ? path : path.slice(0, queryStart);
    const query = queryStart === -1 ? '' : path.slice(queryStart + 1);
    for (const segment of pathname.split('/').slice(1)) {
        if (segment === '') continue;
        const decoded = decodeNavComponent(segment);
        if (decoded === null || isDotSegment(segment) || isDotSegment(decoded)) return false;
    }
    for (const part of query.split('&')) {
        // A param without a name is dropped, as EpicStaff's router drops it.
        if (part === '' || part.startsWith('=')) continue;
        if (decodeNavComponent(part.replaceAll('+', '%20')) === null) return false;
    }
    return true;
}

/** `decodeURIComponent`, or `null` for a malformed escape or invalid UTF-8. */
export function decodeNavComponent(text: string): string | null {
    try {
        return decodeURIComponent(text);
    } catch {
        return null;
    }
}

function isDotSegment(segment: string): boolean {
    return segment === '.' || segment === '..';
}

export const KV_KEY_PATTERN = /^[A-Za-z_][A-Za-z0-9_]*$/;
export const KV_KEY_MAX_LENGTH = 512;
export const KV_SEARCH_MAX_LENGTH = 512;
export const KV_LIST_DEFAULT_LIMIT = 20;
export const KV_LIST_MAX_LIMIT = 100;
/** Characters of a value's JSON text that `kv.list` returns as `value_preview`. */
export const KV_VALUE_PREVIEW_CHARS = 200;

/** True for a key `kv.get` accepts. */
export function isValidKvKey(key: unknown): key is string {
    return typeof key === 'string' && key.length <= KV_KEY_MAX_LENGTH && KV_KEY_PATTERN.test(key);
}

export function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function isRequestId(value: unknown): value is RequestId {
    if (typeof value === 'string') return value.length > 0 && value.length <= 64;
    return typeof value === 'number' && Number.isSafeInteger(value);
}

export function isBridgeErrorCode(value: unknown): value is BridgeErrorCode {
    return typeof value === 'string' && (BRIDGE_ERROR_CODES as readonly string[]).includes(value);
}
