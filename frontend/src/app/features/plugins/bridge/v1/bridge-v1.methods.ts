/**
 * Plugin bridge v1 — PUBLIC CONTRACT. Installed plugins call these methods by name.
 *
 * Never change v1: not a method name, a param, a result key, an error code or the HTTP call
 * behind it. Add a `v2/` table and register it in `BRIDGE_TABLES` instead. Plugins that declare
 * `bridge: 1` must keep working on every later EpicStaff. `bridge-v1.contract.spec.ts` pins it.
 *
 * Plugins name flows by alias only; ids come from the plugin's resolved access list. A session
 * is reachable only when this page started it with `flows.run` AND its flow is one of the
 * plugin's flows with the needed action. Any other session answers `not_found` (for a session the
 * page didn't start, before any HTTP call), so its existence is not revealed.
 */

import { map, Observable, of, switchMap } from 'rxjs';

import { aliasForResource, assertAnyGrant, describeAccess, resolveAlias } from '../access-policy';
import { BridgeMethodContext, BridgeMethodDefinition, BridgeMethodTable } from '../bridge-method';
import { BridgeError, BridgeParams, isRecord } from '../bridge-protocol';
import { BridgeSessionRecord } from '../plugin-bridge-api.service';

/** One answer for every unreachable session, so the page can't tell why it is out of reach. */
const SESSION_NOT_FOUND_MESSAGE = 'No session with that id is available to this plugin.';

export const BRIDGE_V1_METHODS = Object.freeze({
    /** → `{bridge_version, plugin: {id, version, name}, access: [{alias, type, actions}], methods}` */
    'bridge.hello': {
        paramKeys: [],
        resultKeys: ['bridge_version', 'plugin', 'access', 'methods'],
        invoke: (context) =>
            of({
                bridge_version: context.bridgeVersion,
                plugin: { ...context.plugin },
                access: describeAccess(context.access),
                methods: listMethodNames(),
            }),
    },

    /** `{flow: alias, variables?: object}` → `POST /api/run-session/ {graph_id, variables}` → `{session_id}` */
    'flows.run': {
        paramKeys: ['flow', 'variables'],
        resultKeys: ['session_id'],
        invoke: (context, params) => {
            const variables = optionalObject(params, 'variables');
            const graphId = resolveAlias(context.access, params['flow'], 'flow', 'run');
            context.consumeRun();
            return context.api.runSession(graphId, variables).pipe(
                map((response) => {
                    if (!Number.isSafeInteger(response?.session_id)) {
                        throw new BridgeError('internal', 'EpicStaff did not return a session.');
                    }
                    context.rememberOwnSession(response.session_id);
                    return { session_id: response.session_id };
                })
            );
        },
    },

    /** `{session_id}` → `GET /api/sessions/{id}/` → `{status, variables, flow: alias}` */
    'sessions.get': {
        paramKeys: ['session_id'],
        resultKeys: ['status', 'variables', 'flow'],
        invoke: (context, params) => {
            const sessionId = requireSessionId(params);
            assertAnyGrant(context.access, 'sessions.read');
            return loadOwnSession(context, sessionId, 'sessions.read').pipe(
                map(({ session, flow }) => ({ status: session.status, variables: session.variables ?? {}, flow }))
            );
        },
    },

    /** `{session_id}` → session check, SSE ticket, stream → `{subscription}`; then `session.*` events */
    'sessions.subscribe': {
        paramKeys: ['session_id'],
        resultKeys: ['subscription'],
        invoke: (context, params) => {
            const sessionId = requireSessionId(params);
            assertAnyGrant(context.access, 'sessions.read');
            context.assertCanSubscribe();
            return loadOwnSession(context, sessionId, 'sessions.read').pipe(
                map(() => ({ subscription: context.openSubscription(sessionId) }))
            );
        },
    },

    /** `{subscription}` → closes it → `{}` */
    'sessions.unsubscribe': {
        paramKeys: ['subscription'],
        resultKeys: [],
        invoke: (context, params) => {
            const subscription = params['subscription'];
            if (typeof subscription !== 'string' || subscription === '') {
                throw new BridgeError('bad_request', '"subscription" must be a subscription id.');
            }
            if (!context.closeSubscription(subscription)) {
                throw new BridgeError('not_found', 'No open subscription with that id.');
            }
            return of({});
        },
    },

    /** `{session_id}` → session check → `POST /api/sessions/{id}/stop/` → `{}` */
    'sessions.stop': {
        paramKeys: ['session_id'],
        resultKeys: [],
        invoke: (context, params) => {
            const sessionId = requireSessionId(params);
            assertAnyGrant(context.access, 'sessions.stop');
            return loadOwnSession(context, sessionId, 'sessions.stop').pipe(
                switchMap(() => context.api.stopSession(sessionId)),
                map(() => ({}))
            );
        },
    },
} as const satisfies Readonly<Record<string, BridgeMethodDefinition>>) satisfies BridgeMethodTable;

export type BridgeV1MethodName = keyof typeof BRIDGE_V1_METHODS;

interface OwnSession {
    session: BridgeSessionRecord;
    flow: string;
}

/**
 * Reads a session this page started and requires its flow to be one of the plugin's flows
 * granting `action`. Any other session id is refused with `not_found` before the HTTP call.
 */
function loadOwnSession(
    context: BridgeMethodContext,
    sessionId: number,
    action: 'sessions.read' | 'sessions.stop'
): Observable<OwnSession> {
    if (!context.isOwnSession(sessionId)) {
        throw new BridgeError('not_found', SESSION_NOT_FOUND_MESSAGE);
    }
    return context.api.getSession(sessionId).pipe(
        map((session) => {
            const graph: unknown = isRecord(session) ? session['graph'] : null;
            const graphId = typeof graph === 'number' && Number.isSafeInteger(graph) ? graph : null;
            const flow = graphId === null ? null : aliasForResource(context.access, 'flow', graphId, action);
            if (flow === null) {
                throw new BridgeError('not_found', SESSION_NOT_FOUND_MESSAGE);
            }
            return { session, flow };
        })
    );
}

function listMethodNames(): string[] {
    return Object.keys(BRIDGE_V1_METHODS);
}

function requireSessionId(params: BridgeParams): number {
    const sessionId = params['session_id'];
    if (typeof sessionId !== 'number' || !Number.isSafeInteger(sessionId) || sessionId <= 0) {
        throw new BridgeError('bad_request', '"session_id" must be a positive integer.');
    }
    return sessionId;
}

function optionalObject(params: BridgeParams, key: string): Record<string, unknown> {
    const value = params[key];
    if (value === undefined) return {};
    if (!isRecord(value)) throw new BridgeError('bad_request', `"${key}" must be an object.`);
    return value;
}
