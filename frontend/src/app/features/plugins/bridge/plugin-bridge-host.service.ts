import { DOCUMENT } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { effect, inject, Injectable, OnDestroy, signal, untracked } from '@angular/core';
import { defer, Subscription } from 'rxjs';

import { ActiveOrgService } from '../../../services/auth/active-org.service';
import { SseTicketService } from '../../../services/auth/sse-ticket.service';
import { PluginUiSession } from '../models/plugin.model';
import { AccessPolicy, buildAccessPolicy, describeAccess } from './access-policy';
import { BridgeMethodContext } from './bridge-method';
import {
    BRIDGE_LIMITS,
    BridgeError,
    BridgeEvent,
    BridgeEventTopic,
    BridgeHandshakeErrorMessage,
    BridgeInitContext,
    BridgeInitMessage,
    BridgeParams,
    BridgeRequestId,
    BridgeResponse,
    isBridgeRequestId,
    isReadyMessage,
    isRecord,
} from './bridge-protocol';
import { findBridgeMethod, isSupportedBridgeVersion } from './bridge-tables';
import { PluginBridgeApiService } from './plugin-bridge-api.service';
import { PLUGIN_EVENT_SOURCE_FACTORY, PluginSessionStream } from './plugin-session-stream';

/** Why the host tore a plugin page down. */
export type PluginBridgeStopReason = 'navigated' | 'org_changed';

const REQUEST_KEYS: ReadonlySet<string> = new Set(['v', 'kind', 'id', 'method', 'params']);
const RUN_WINDOW_MS = 60_000;

/** Everything that belongs to one attached plugin page; dropped as a whole on detach. */
interface Attachment {
    readonly frame: HTMLIFrameElement;
    readonly frameWindow: Window;
    readonly orgId: number | null;
    readonly bridgeVersion: number;
    readonly initContext: BridgeInitContext;
    readonly policy: AccessPolicy;
    readonly requests: Set<Subscription>;
    readonly streams: Map<string, PluginSessionStream>;
    /**
     * Sessions this page started with a successful `flows.run`. The page can read, subscribe to and
     * stop only these, so it never reaches another user's session of the same flow, nor a session
     * of an organization flow that embeds the plugin's flow. Dropped with the attachment, so a
     * reloaded page starts empty.
     */
    readonly ownSessionIds: Set<number>;
    port: MessagePort | null;
    ownLoadSeen: boolean;
    runTimestamps: number[];
    subscriptionCounter: number;
    methodContext: BridgeMethodContext | null;
}

/**
 * The EpicStaff side of the plugin bridge for one plugin page (provide it on the page component).
 *
 * Handshake: accepts one `{v, kind: 'ready'}` posted on `window` whose `event.source` is the
 * plugin iframe's window and whose `event.origin` is `"null"` (an opaque, sandboxed origin), then
 * replies `init` with a `MessagePort`. All requests travel on that port and are checked — version,
 * size, in-flight cap, method, params, alias and action, rate limits — before any HTTP call, which
 * then runs as the signed-in user.
 *
 * Sessions are page-scoped: a page reaches only the sessions it started itself with `flows.run`.
 *
 * Teardown: a second `load` of the iframe means the page navigated (possibly off-site), so the
 * port and every stream are closed, the iframe is removed and {@link stopped} is set. The same
 * happens when the active organization changes. Destroying the page closes everything.
 */
@Injectable()
export class PluginBridgeHost implements OnDestroy {
    private readonly stoppedSignal = signal<PluginBridgeStopReason | null>(null);
    /** Set when the host tore the page down; reset by the next `attach`. */
    public readonly stopped = this.stoppedSignal.asReadonly();

    private readonly connectedSignal = signal(false);
    /** True once the handshake completed for the attached page. */
    public readonly connected = this.connectedSignal.asReadonly();

    private readonly orgPinEffect = effect(() => {
        const orgId = this.activeOrgService.activeOrgId();
        untracked(() => {
            if (this.attachment && orgId !== this.attachment.orgId) this.stop('org_changed');
        });
    });

    private readonly api = inject(PluginBridgeApiService);
    private readonly sseTicketService = inject(SseTicketService);
    private readonly createEventSource = inject(PLUGIN_EVENT_SOURCE_FACTORY);
    private readonly activeOrgService = inject(ActiveOrgService);
    private readonly hostWindow = inject(DOCUMENT).defaultView;
    private attachment: Attachment | null = null;
    private readonly windowMessageListener = (event: MessageEvent): void => this.handleWindowMessage(event);

    ngOnDestroy(): void {
        this.detach();
    }

    /**
     * Starts serving the plugin page in `frame` (rendered with the session's URL). Call it before
     * the page can post `ready`: in the same change detection pass that set the iframe's `src`.
     */
    attach(frame: HTMLIFrameElement, session: PluginUiSession): void {
        this.detach();
        this.stoppedSignal.set(null);
        const frameWindow = frame.contentWindow;
        if (!frameWindow || !this.hostWindow) return;

        const policy = buildAccessPolicy(session.access);
        this.attachment = {
            frame,
            frameWindow,
            orgId: this.activeOrgService.activeOrgId(),
            bridgeVersion: session.bridge_version,
            initContext: {
                plugin: { id: session.plugin.plugin_id, version: session.plugin.version, name: session.plugin.name },
                access: describeAccess(policy),
            },
            policy,
            requests: new Set(),
            streams: new Map(),
            ownSessionIds: new Set(),
            port: null,
            ownLoadSeen: false,
            runTimestamps: [],
            subscriptionCounter: 0,
            methodContext: null,
        };
        this.hostWindow.addEventListener('message', this.windowMessageListener);
    }

    /**
     * Forward every `load` of the iframe. The first after `attach` is the plugin page itself; any
     * later one is a navigation, which stops the page. (An initial `about:blank` load fired while
     * the iframe was inserted, before `attach`, is not counted.)
     *
     * This teardown is cleanup only, NOT a security boundary. Some ways for a page to send data out
     * never fire a `load` here: navigating to a URL that answers 204 (the navigation is dropped and
     * the page keeps running, bridge included), a navigation whose response never arrives, DNS
     * prefetch or WebRTC, which CSP does not fully cover. And when a second `load` does fire, the
     * request carrying the data has already left. What limits a plugin is what the bridge refuses
     * to hand out: the access policy, page-scoped sessions and the caps.
     */
    onFrameLoad(): void {
        const attachment = this.attachment;
        if (!attachment) return;
        if (!attachment.ownLoadSeen) {
            attachment.ownLoadSeen = true;
            return;
        }
        this.stop('navigated');
    }

    /** Closes the port, every stream and every pending request. Leaves the iframe in place. */
    detach(): void {
        const attachment = this.attachment;
        if (!attachment) return;
        this.attachment = null;
        this.hostWindow?.removeEventListener('message', this.windowMessageListener);
        attachment.requests.forEach((request) => request.unsubscribe());
        attachment.requests.clear();
        attachment.streams.forEach((stream) => stream.close());
        attachment.streams.clear();
        if (attachment.port) {
            attachment.port.onmessage = null;
            attachment.port.close();
            attachment.port = null;
        }
        this.connectedSignal.set(false);
    }

    private stop(reason: PluginBridgeStopReason): void {
        const attachment = this.attachment;
        if (!attachment) return;
        this.detach();
        // Remove the frame now rather than on the next render; the page template drops it too.
        attachment.frame.remove();
        this.stoppedSignal.set(reason);
    }

    private handleWindowMessage(event: MessageEvent): void {
        const attachment = this.attachment;
        if (!attachment || attachment.port) return;
        if (event.source !== attachment.frameWindow || event.origin !== 'null') return;
        const data: unknown = event.data;
        if (!isReadyMessage(data)) return;

        if (data.v !== attachment.bridgeVersion || !isSupportedBridgeVersion(attachment.bridgeVersion)) {
            const message: BridgeHandshakeErrorMessage = {
                v: attachment.bridgeVersion,
                kind: 'error',
                error: {
                    code: 'unsupported',
                    message: `This plugin declares bridge version ${attachment.bridgeVersion}; the page asked for ${data.v}.`,
                },
            };
            attachment.frameWindow.postMessage(message, '*');
            return;
        }

        const channel = new MessageChannel();
        attachment.port = channel.port1;
        attachment.port.onmessage = (portEvent: MessageEvent) => this.handleRequest(attachment, portEvent.data);
        const init: BridgeInitMessage = { v: attachment.bridgeVersion, kind: 'init', context: attachment.initContext };
        // An opaque-origin frame can only be addressed with '*'; `event.source` above pins the target.
        attachment.frameWindow.postMessage(init, '*', [channel.port2]);
        this.connectedSignal.set(true);
    }

    private handleRequest(attachment: Attachment, data: unknown): void {
        if (this.attachment !== attachment) return;
        // Without a usable id the answer could not be matched to the request; drop it.
        if (!isRecord(data) || !isBridgeRequestId(data['id'])) return;
        const id = data['id'];

        let method: string;
        let params: BridgeParams;
        try {
            ({ method, params } = parseRequest(data, attachment.bridgeVersion));
        } catch (error) {
            this.respondError(attachment, id, error);
            return;
        }

        if (attachment.requests.size >= BRIDGE_LIMITS.maxInFlight) {
            this.respondError(
                attachment,
                id,
                new BridgeError('rate_limited', `At most ${BRIDGE_LIMITS.maxInFlight} requests may wait for an answer.`)
            );
            return;
        }
        const definition = findBridgeMethod(attachment.bridgeVersion, method);
        if (!definition) {
            this.respondError(
                attachment,
                id,
                new BridgeError('unsupported', `Unknown method "${method.slice(0, 64)}".`)
            );
            return;
        }
        const unknownKey = Object.keys(params).find((key) => !definition.paramKeys.includes(key));
        if (unknownKey !== undefined) {
            this.respondError(
                attachment,
                id,
                new BridgeError('bad_request', `Unknown param "${unknownKey.slice(0, 64)}" for ${method}.`)
            );
            return;
        }
        if (this.activeOrgService.activeOrgId() !== attachment.orgId) {
            this.stop('org_changed');
            return;
        }

        const context = this.methodContextFor(attachment);
        let answered = false;
        // Assigned after `subscribe` returns; a method that answers synchronously never counts as in flight.
        let request: Subscription | null = null;
        const settle = (): void => {
            if (request) attachment.requests.delete(request);
        };
        request = defer(() => definition.invoke(context, params)).subscribe({
            next: (result) => {
                if (answered) return;
                answered = true;
                this.respond(attachment, { v: attachment.bridgeVersion, kind: 'response', id, ok: true, result });
            },
            error: (error: unknown) => {
                settle();
                if (answered) return;
                answered = true;
                this.respondError(attachment, id, error);
            },
            complete: () => {
                settle();
                if (!answered) this.respondError(attachment, id, new BridgeError('internal', 'No result.'));
            },
        });
        if (!request.closed) attachment.requests.add(request);
    }

    private methodContextFor(attachment: Attachment): BridgeMethodContext {
        attachment.methodContext ??= {
            bridgeVersion: attachment.bridgeVersion,
            plugin: attachment.initContext.plugin,
            access: attachment.policy,
            api: this.api,
            consumeRun: () => this.consumeRun(attachment),
            assertCanSubscribe: () => assertSubscriptionCapacity(attachment),
            openSubscription: (sessionId) => this.openSubscription(attachment, sessionId),
            closeSubscription: (subscription) => this.closeSubscription(attachment, subscription),
            rememberOwnSession: (sessionId) => {
                attachment.ownSessionIds.add(sessionId);
            },
            isOwnSession: (sessionId) => attachment.ownSessionIds.has(sessionId),
        };
        return attachment.methodContext;
    }

    private consumeRun(attachment: Attachment): void {
        const now = Date.now();
        attachment.runTimestamps = attachment.runTimestamps.filter((time) => now - time < RUN_WINDOW_MS);
        if (attachment.runTimestamps.length >= BRIDGE_LIMITS.maxRunsPerMinute) {
            throw new BridgeError('rate_limited', `At most ${BRIDGE_LIMITS.maxRunsPerMinute} flow runs per minute.`);
        }
        attachment.runTimestamps.push(now);
    }

    private openSubscription(attachment: Attachment, sessionId: number): string {
        assertSubscriptionCapacity(attachment);
        attachment.subscriptionCounter++;
        const subscription = `sub-${attachment.subscriptionCounter}`;
        const stream = new PluginSessionStream({
            sessionId,
            fetchTicket: () => this.sseTicketService.fetchTicket(),
            streamUrl: (id, ticket) => this.api.sessionStreamUrl(id, ticket),
            createEventSource: this.createEventSource,
            onMessage: (data) => this.postEvent(attachment, 'session.message', subscription, data),
            onStatus: (data) => this.postEvent(attachment, 'session.status', subscription, data),
            onClosed: (data) => {
                attachment.streams.delete(subscription);
                this.postEvent(attachment, 'subscription.closed', subscription, data);
            },
        });
        attachment.streams.set(subscription, stream);
        // Start after the subscribe response is posted, so the page knows the id before any event.
        queueMicrotask(() => {
            if (attachment.streams.get(subscription) === stream) stream.start();
        });
        return subscription;
    }

    private closeSubscription(attachment: Attachment, subscription: string): boolean {
        const stream = attachment.streams.get(subscription);
        if (!stream) return false;
        stream.close();
        attachment.streams.delete(subscription);
        return true;
    }

    private postEvent(attachment: Attachment, topic: BridgeEventTopic, subscription: string, data: unknown): void {
        if (this.attachment !== attachment || !attachment.port) return;
        const event: BridgeEvent = { v: attachment.bridgeVersion, kind: 'event', topic, subscription, data };
        attachment.port.postMessage(event);
    }

    private respond(attachment: Attachment, response: BridgeResponse): void {
        if (this.attachment !== attachment || !attachment.port) return;
        attachment.port.postMessage(response);
    }

    private respondError(attachment: Attachment, id: BridgeRequestId, error: unknown): void {
        const body = toBridgeError(error).toBody();
        this.respond(attachment, { v: attachment.bridgeVersion, kind: 'response', id, ok: false, error: body });
    }
}

function assertSubscriptionCapacity(attachment: Attachment): void {
    if (attachment.streams.size >= BRIDGE_LIMITS.maxSubscriptions) {
        throw new BridgeError('rate_limited', `At most ${BRIDGE_LIMITS.maxSubscriptions} subscriptions may be open.`);
    }
}

/**
 * Validates one request on the port: plain JSON within the size cap, the request envelope, the
 * right version, a method name and an object of params. Works on a JSON copy, so nothing but
 * plain data reaches a method.
 */
function parseRequest(data: Record<string, unknown>, bridgeVersion: number): { method: string; params: BridgeParams } {
    let json: string;
    try {
        json = JSON.stringify(data);
    } catch {
        throw new BridgeError('bad_request', 'The request must be plain JSON data.');
    }
    if (new TextEncoder().encode(json).length > BRIDGE_LIMITS.maxRequestBytes) {
        throw new BridgeError('bad_request', `The request is larger than ${BRIDGE_LIMITS.maxRequestBytes / 1024} KB.`);
    }
    const request: unknown = JSON.parse(json);
    if (!isRecord(request) || request['kind'] !== 'request') {
        throw new BridgeError('bad_request', 'Expected {v, kind: "request", id, method, params}.');
    }
    if (request['v'] !== bridgeVersion) {
        throw new BridgeError('unsupported', `This plugin uses bridge version ${bridgeVersion}.`);
    }
    if (Object.keys(request).some((key) => !REQUEST_KEYS.has(key))) {
        throw new BridgeError('bad_request', 'The request has unknown fields.');
    }
    const method = request['method'];
    if (typeof method !== 'string' || method === '') {
        throw new BridgeError('bad_request', '"method" must be a method name.');
    }
    const params = request['params'] ?? {};
    if (!isRecord(params)) {
        throw new BridgeError('bad_request', '"params" must be an object.');
    }
    return { method, params };
}

/** Maps any failure to what the page may see; server error bodies are never passed through. */
export function toBridgeError(error: unknown): BridgeError {
    if (error instanceof BridgeError) return error;
    if (error instanceof HttpErrorResponse) {
        switch (error.status) {
            case 400:
                return new BridgeError('bad_request', 'EpicStaff rejected the request.');
            case 401:
            case 403:
                return new BridgeError('forbidden', 'The signed-in user is not allowed to do this.');
            case 404:
                return new BridgeError('not_found', 'Not found.');
            case 409:
                return isRecord(error.error) && error.error['code'] === 'plugin_suspended'
                    ? new BridgeError('forbidden', 'This plugin is suspended.')
                    : new BridgeError('bad_request', 'The request conflicts with the current state.');
            case 429:
                return new BridgeError('rate_limited', 'Too many requests; try again later.');
        }
    }
    return new BridgeError('internal', 'EpicStaff could not complete the request.');
}
