/**
 * Plugin bridge protocol: the messages a plugin page and EpicStaff exchange.
 *
 * Handshake on `window.postMessage`: the page posts {@link BridgeReadyMessage}; the host answers
 * with {@link BridgeInitMessage} and transfers a `MessagePort`. Everything after that travels on
 * the port: requests from the page, responses and events from the host. Every message carries
 * `v`, which must equal the plugin's bridge version.
 *
 * The shapes here are part of the public plugin contract — see `v1/bridge-v1.methods.ts`.
 */

import { PluginAccessAction, PluginAccessTargetType } from '../models/plugin.model';

export const BRIDGE_ERROR_CODES = [
    'bad_request',
    'forbidden',
    'not_found',
    'rate_limited',
    'unsupported',
    'internal',
] as const;

export type BridgeErrorCode = (typeof BRIDGE_ERROR_CODES)[number];

/** Event topics the host sends on a subscription. */
export const BRIDGE_EVENT_TOPICS = ['session.message', 'session.status', 'subscription.closed'] as const;

export type BridgeEventTopic = (typeof BRIDGE_EVENT_TOPICS)[number];

/** Host-enforced limits per open plugin page. */
export const BRIDGE_LIMITS = {
    /** Size of one request, measured as UTF-8 JSON. */
    maxRequestBytes: 64 * 1024,
    /** Requests waiting for their response. */
    maxInFlight: 10,
    /** Open `sessions.subscribe` streams. */
    maxSubscriptions: 4,
    /** `flows.run` calls in any 60-second window. */
    maxRunsPerMinute: 20,
} as const;

/** Request ids are chosen by the page: a string of at most 64 characters or a safe integer. */
export type BridgeRequestId = string | number;

export interface BridgeErrorBody {
    code: BridgeErrorCode;
    message: string;
}

/** What a plugin sees about one of its access entries: the alias, never the database id. */
export interface BridgeAccessDescription {
    alias: string;
    type: PluginAccessTargetType;
    actions: PluginAccessAction[];
}

export interface BridgeInitContext {
    /** `id` is the plugin's manifest id (for example `chat-bot`), not a database id. */
    plugin: { id: string; version: string; name: string };
    access: BridgeAccessDescription[];
}

export interface BridgeReadyMessage {
    v: number;
    kind: 'ready';
}

export interface BridgeInitMessage {
    v: number;
    kind: 'init';
    context: BridgeInitContext;
}

/** Sent on `window` instead of `init` when the handshake can't complete (for example a wrong `v`). */
export interface BridgeHandshakeErrorMessage {
    v: number;
    kind: 'error';
    error: BridgeErrorBody;
}

export type BridgeParams = Record<string, unknown>;

export interface BridgeRequest {
    v: number;
    kind: 'request';
    id: BridgeRequestId;
    method: string;
    params?: BridgeParams;
}

export interface BridgeSuccessResponse {
    v: number;
    kind: 'response';
    id: BridgeRequestId;
    ok: true;
    result: unknown;
}

export interface BridgeErrorResponse {
    v: number;
    kind: 'response';
    id: BridgeRequestId;
    ok: false;
    error: BridgeErrorBody;
}

export type BridgeResponse = BridgeSuccessResponse | BridgeErrorResponse;

export interface BridgeEvent {
    v: number;
    kind: 'event';
    topic: BridgeEventTopic;
    subscription: string;
    data: unknown;
}

/** `session.message` data: one flow message, as the running-session page receives it. */
export interface BridgeSessionMessageData {
    message_type: string | null;
    name: string;
    created_at: string | null;
    message_data: unknown;
}

/** `session.status` data. */
export interface BridgeSessionStatusData {
    status: string;
}

/** `subscription.closed` data: the host closed the subscription on its own. */
export interface BridgeSubscriptionClosedData {
    /** `ended`: the session reached a final status. `error`: the stream failed and gave up. */
    reason: 'ended' | 'error';
}

/** A failure a method reports to the page; anything else thrown becomes `internal`. */
export class BridgeError extends Error {
    constructor(
        readonly code: BridgeErrorCode,
        message: string
    ) {
        super(message);
        this.name = 'BridgeError';
    }

    toBody(): BridgeErrorBody {
        return { code: this.code, message: this.message };
    }
}

export function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function isBridgeRequestId(value: unknown): value is BridgeRequestId {
    if (typeof value === 'string') return value.length > 0 && value.length <= 64;
    return typeof value === 'number' && Number.isSafeInteger(value);
}

export function isReadyMessage(value: unknown): value is BridgeReadyMessage {
    return isRecord(value) && value['kind'] === 'ready' && typeof value['v'] === 'number';
}
