import type { PlatformConfig, PlatformLogin } from './config.js';
import { gatewayRefusal, passedGateway } from './gateway.js';
import { describeError, PluginLoginError } from './login-error.js';
import {
    GATEWAY_DENY_HEADER,
    type LoginCallbackError,
    LOGIN_CALLBACK_ERRORS,
    LOGIN_CODE_CHALLENGE_METHOD,
    LOGIN_LIMITS,
    LOGIN_MESSAGE_TYPES,
    LOGIN_ORG_STORAGE_KEY,
    LOGIN_PATTERNS,
    LOGIN_PROTOCOL_VERSION,
    LOGIN_STORAGE_KEYS,
} from './login-protocol.js';
import { createPkcePair, randomToken } from './pkce.js';
import {
    completePopup,
    type CompletePopupOptions,
    type CompletePopupOutcome,
    openPopup,
    type OpenPopupOptions,
    type PopupLoginPort,
    type PopupResult,
    sessionStorageOf,
} from './popup.js';
import { isRecord, type PluginAvailability } from './protocol.js';

/**
 * Where the person's sign-in stands.
 *
 * - `idle`: `start()` has not run.
 * - `signing-in`: a sign-in is under way, or the page is on its way to EpicStaff to sign in.
 * - `signed-in`: there is a token; `fetch` sends it to the plugin's own API.
 * - `access-denied`: the person may not use the plugin in this organization (or in any of theirs).
 * - `session-ended`: the EpicStaff session ended while the page was open. Inside EpicStaff, offer "Sign in again"
 *   (`signIn()`); a page opened on its own goes to EpicStaff's login at once.
 * - `maintenance`: the plugin is being updated in the person's organization, so EpicStaff signs nobody in to it there
 *   for now (`availability` is `maintenance` too). Say so, and call `renew()` now and then to try again.
 * - `failed`: something unexpected stopped the sign-in; `error` says what.
 */
export type LoginState =
    | 'idle'
    | 'signing-in'
    | 'signed-in'
    | 'access-denied'
    | 'session-ended'
    | 'maintenance'
    | 'failed';

/** Who is signed in, from the token endpoint's answer. The token itself stays inside the SDK. */
export interface PluginSession {
    readonly plugin: { readonly identifier: string; readonly version: string };
    readonly org: { readonly id: number; readonly name: string };
    readonly user: { readonly id: number; readonly email: string; readonly name: string };
    /** The person's actions on the plugin in this organization, in manifest order; always contains `read`. */
    readonly permissions: readonly string[];
    /** When the token expires, in milliseconds since the epoch, by this browser's clock. */
    readonly expiresAt: number;
}

export interface PluginLoginOptions {
    /** Defaults to the global `window`; the same window `startPlugin` was given. */
    window?: Window;
    /** Defaults to the global `fetch`. */
    fetch?: typeof fetch;
}

/** What `createPluginLogin` needs from `startPlugin`'s result. */
export interface PluginLoginSource {
    readonly config: PlatformConfig;
    /** The `es_org` hint, already removed from the address. */
    readonly orgHint: number | null;
    /** Tells EpicStaff about a change of {@link PluginLogin.availability}; `startPlugin`'s result has it. */
    readonly reportAvailability?: (availability: PluginAvailability) => void;
}

/** A person's sign-in to the plugin through EpicStaff, and the requests that carry it. */
export interface PluginLogin {
    readonly state: LoginState;
    /** Who is signed in; `null` unless `state` is `signed-in`. */
    readonly session: PluginSession | null;
    /** Why `state` is `failed`; `null` otherwise. */
    readonly error: PluginLoginError | null;
    /**
     * Whether the plugin's own API can be reached, from the last answer {@link fetch} got from it: `maintenance` or
     * `unavailable` after the gateway answered `503` with that reason, `available` again after any answer that passed
     * the gateway. A sign-in refused for maintenance sets `maintenance`; one that succeeds clears it. `available` until
     * then.
     */
    readonly availability: PluginAvailability;
    /** Calls `listener` on every state change and every renewed token. Returns the function that stops it. */
    onChange(listener: (state: LoginState) => void): () => void;
    /** Calls `listener` on every change of {@link availability}. Returns the function that stops it. */
    onAvailabilityChange(listener: (availability: PluginAvailability) => void): () => void;
    /**
     * Signs the person in: finishes a sign-in that just came back from EpicStaff, else tries silently (a hidden frame,
     * no visible change), else sends the page to EpicStaff's login, which brings it back to the same address. Resolves
     * with the state it reached; `signing-in` means the page is navigating away. Runs once; later calls share it.
     */
    start(): Promise<LoginState>;
    /** Gets a new token silently for the same organization. Never navigates. */
    renew(): Promise<LoginState>;
    /** Sends the page to EpicStaff to sign in, for "Sign in again". Resolves once the navigation has started. */
    signIn(): Promise<void>;
    /**
     * `fetch` for the plugin's own API. Resolves `input` against the page's origin and adds `Authorization: Bearer
     * <token>` only to requests to that origin under `api_base`. When EpicStaff's gateway refuses the token (`401`
     * with `X-EpicStaff-Gateway-Deny: login`) it renews once and retries once; when the gateway refuses the person
     * (`403` with `X-EpicStaff-Gateway-Deny: forbidden`) the state becomes `access-denied`. The plugin's own 401 and
     * 403 responses (without the header) are returned as they are. A retried request must have a body that can be
     * sent twice (not a stream). A `503` from the gateway (`maintenance` or `unavailable`) sets {@link availability},
     * is returned as it is, and never renews.
     */
    fetch(input: string | URL, init?: RequestInit): Promise<Response>;
    /** See {@link openPopup}. Call it from a click or key press handler, before any `await`. */
    openPopup(url: string | URL, options: OpenPopupOptions): Promise<PopupResult>;
    /** See {@link completePopup}. Call it instead of `start()` on the page an external provider returns to. */
    completePopup(options?: CompletePopupOptions): Promise<CompletePopupOutcome>;
    /** Stops renewals, removes the hidden frame and rejects a pending popup with `closed`. */
    close(): void;
}

/**
 * Prepares the person's sign-in for a plugin page started with `startPlugin`. Nothing happens until `start()`.
 *
 * Throws {@link PluginLoginError} `insecure_context` outside a secure context (plain http other than `*.localhost`),
 * and `login_unavailable` for a plugin without a backend.
 */
export function createPluginLogin(plugin: PluginLoginSource, options: PluginLoginOptions = {}): PluginLogin {
    const win = options.window ?? window;
    if (!win.isSecureContext || !win.crypto?.subtle) {
        throw new PluginLoginError(
            'insecure_context',
            'Signing in needs a secure context (https, or http on a *.localhost host) for the Web Crypto API.'
        );
    }
    if (plugin.config.login === null) {
        throw new PluginLoginError(
            'login_unavailable',
            'This plugin has no backend, so EpicStaff offers no sign-in for it ("login" is null in the platform config).'
        );
    }
    const fetchImplementation = options.fetch ?? globalThis.fetch.bind(globalThis);
    const reportAvailability = plugin.reportAvailability;
    return new BrowserPluginLogin(
        win,
        plugin.config,
        plugin.config.login,
        plugin.orgHint,
        fetchImplementation,
        (state) => reportAvailability?.(state)
    );
}

/** What EpicStaff answered on the callback page: a code, or an error from the OAuth vocabulary. */
type AuthorizeAnswer = { code: string } | { error: LoginCallbackError };

/** An interactive sign-in that came back: the answer, and the verifier and org kept for it. */
interface ReturnedLogin {
    verifier: string;
    org: number | null;
    answer: AuthorizeAnswer | null;
}

/** The interactive sign-in under way, as `sessionStorage[pending]` holds it. The callback page reads it too. */
interface PendingLogin {
    state: string;
    code_verifier: string;
    return_path: string;
    org: number | null;
    /** Milliseconds since the epoch. */
    created_at: number;
}

interface TokenAnswer {
    token: string;
    lifetimeSeconds: number;
    session: Omit<PluginSession, 'expiresAt'>;
}

const ORG_ID_TEXT = /^[1-9][0-9]{0,15}$/;

class BrowserPluginLogin implements PluginLogin {
    private readonly win: Window;
    private readonly config: PlatformConfig;
    private readonly endpoints: PlatformLogin;
    private readonly fetchImplementation: typeof fetch;
    private readonly reportAvailability: (availability: PluginAvailability) => void;
    /** The org to sign in to when there is no token yet: `es_org`, else the org of this tab's last token. */
    private orgHint: number | null;
    /** `orgHint` came from this tab's last token, not from EpicStaff: it may name an org the person has lost. */
    private orgHintIsStored: boolean;
    private readonly listeners = new Set<(state: LoginState) => void>();
    private readonly availabilityListeners = new Set<(availability: PluginAvailability) => void>();
    /** Cancels whatever is still running (a silent frame, a popup) when the login is closed. */
    private readonly cancellations = new Set<() => void>();
    private currentState: LoginState = 'idle';
    private currentSession: PluginSession | null = null;
    private currentError: PluginLoginError | null = null;
    private currentAvailability: PluginAvailability = 'available';
    /** The maintenance came from a sign-in EpicStaff refused for an update, not from the API's own answer. */
    private maintenanceFromSignIn = false;
    /** Kept only here, never in any storage. */
    private token: string | null = null;
    /** The org of the latest token, kept after it ends, for renewals and "Sign in again". */
    private lastOrgId: number | null = null;
    private startRun: Promise<LoginState> | null = null;
    private renewRun: Promise<LoginState> | null = null;
    private renewTimer: ReturnType<typeof setTimeout> | null = null;
    private closed = false;

    /** Back in view after a while (a background tab, a sleeping laptop): renew a token that fell due meanwhile. */
    private readonly onVisibilityChange = (): void => {
        if (this.win.document.visibilityState === 'visible' && this.renewRun === null && this.isRenewalDue()) {
            void this.renew();
        }
    };

    constructor(
        win: Window,
        config: PlatformConfig,
        endpoints: PlatformLogin,
        orgHint: number | null,
        fetchImplementation: typeof fetch,
        reportAvailability: (availability: PluginAvailability) => void
    ) {
        this.win = win;
        this.config = config;
        this.endpoints = endpoints;
        this.fetchImplementation = fetchImplementation;
        this.reportAvailability = reportAvailability;
        const storedOrg = orgHint === null ? this.readStoredOrg() : null;
        this.orgHint = orgHint ?? storedOrg;
        this.orgHintIsStored = storedOrg !== null;
        this.win.document.addEventListener('visibilitychange', this.onVisibilityChange);
    }

    get state(): LoginState {
        return this.currentState;
    }

    get session(): PluginSession | null {
        return this.currentSession;
    }

    get error(): PluginLoginError | null {
        return this.currentError;
    }

    get availability(): PluginAvailability {
        return this.currentAvailability;
    }

    onChange(listener: (state: LoginState) => void): () => void {
        this.listeners.add(listener);
        return () => this.listeners.delete(listener);
    }

    onAvailabilityChange(listener: (availability: PluginAvailability) => void): () => void {
        this.availabilityListeners.add(listener);
        return () => this.availabilityListeners.delete(listener);
    }

    start(): Promise<LoginState> {
        this.startRun ??= this.runStart();
        return this.startRun;
    }

    renew(): Promise<LoginState> {
        this.renewRun ??= this.runRenew().finally(() => {
            this.renewRun = null;
        });
        return this.renewRun;
    }

    signIn(): Promise<void> {
        return this.navigateToLogin(this.currentOrg(), currentReturnPath(this.win));
    }

    async fetch(input: string | URL, init: RequestInit = {}): Promise<Response> {
        const url = new URL(input, this.win.location.origin);
        if (!this.isOwnApi(url)) return this.fetchImplementation(url.href, init);

        await this.settled();
        const sentToken = this.token;
        const response = await this.sendToApi(url, init, sentToken);
        if (sentToken === null) return response;

        // Only the gateway's own refusals change the sign-in; a 401 or 403 from the plugin is the caller's to handle.
        const gatewayDeny = response.headers.get(GATEWAY_DENY_HEADER);
        if (response.status === 403 && gatewayDeny === 'forbidden') {
            this.deny();
            return response;
        }
        if (response.status !== 401 || gatewayDeny !== 'login') return response;
        // A request that failed alongside this one may have renewed already.
        if (this.token === sentToken) await this.renew();
        if (this.currentState !== 'signed-in' || this.token === null || !isReplayable(init)) return response;
        return this.sendToApi(url, init, this.token);
    }

    openPopup(url: string | URL, options: OpenPopupOptions): Promise<PopupResult> {
        return openPopup(this.popupPort(), url, options);
    }

    completePopup(options: CompletePopupOptions = {}): Promise<CompletePopupOutcome> {
        return completePopup(this.popupPort(), options);
    }

    close(): void {
        this.closed = true;
        this.win.document.removeEventListener('visibilitychange', this.onVisibilityChange);
        this.clearRenewal();
        for (const cancel of [...this.cancellations]) cancel();
        this.cancellations.clear();
        this.listeners.clear();
        this.availabilityListeners.clear();
    }

    private async runStart(): Promise<LoginState> {
        this.setState('signing-in');
        const returned = this.takeReturnedLogin();
        if (returned !== null) return this.finishReturnedLogin(returned, true);
        return this.signInSilently(this.orgHint, 'start');
    }

    private async runRenew(): Promise<LoginState> {
        if (this.startRun !== null) await this.startRun;
        return this.signInSilently(this.currentOrg(), 'renew');
    }

    /** At start, a person EpicStaff cannot sign in silently goes to the login; on renewal the session has ended. */
    private async signInSilently(org: number | null, purpose: 'start' | 'renew'): Promise<LoginState> {
        const pkce = await createPkcePair(this.win.crypto);
        const state = randomToken(this.win.crypto);
        const answer = await this.authorizeInFrame(state, pkce.challenge, org);
        if (this.closed) return this.currentState;
        if ('code' in answer) return this.exchange(answer.code, pkce.verifier);
        if (answer.error === 'access_denied') {
            return purpose === 'start' && this.isStaleStoredOrg(org) ? this.signInWithoutStoredOrg() : this.deny();
        }
        if (answer.error === 'temporarily_unavailable') return this.holdForMaintenance();
        if (purpose === 'start') {
            await this.navigateToLogin(org, currentReturnPath(this.win));
            return this.currentState;
        }
        return this.endSession();
    }

    /**
     * Loads the authorize endpoint with `prompt=none` in a hidden frame. EpicStaff answers on the silent callback page,
     * which posts the answer to this page; only a message from that frame, from this page's own origin and with this
     * `state` counts. No answer in time counts as `login_required`.
     */
    private authorizeInFrame(state: string, challenge: string, org: number | null): Promise<AuthorizeAnswer> {
        const document = this.win.document;
        const frame = document.createElement('iframe');
        return new Promise((resolve) => {
            let settled = false;
            const finish = (answer: AuthorizeAnswer): void => {
                if (settled) return;
                settled = true;
                clearTimeout(timer);
                this.win.removeEventListener('message', onMessage);
                this.cancellations.delete(cancel);
                frame.remove();
                resolve(answer);
            };
            const cancel = (): void => finish({ error: 'login_required' });
            const onMessage = (event: MessageEvent): void => {
                if (event.origin !== this.win.location.origin || event.source !== frame.contentWindow) return;
                const data: unknown = event.data;
                if (
                    !isRecord(data) ||
                    data['type'] !== LOGIN_MESSAGE_TYPES.loginResult ||
                    data['protocol'] !== LOGIN_PROTOCOL_VERSION ||
                    data['state'] !== state
                ) {
                    return;
                }
                finish(readAnswer(data) ?? { error: 'login_required' });
            };
            const timer = setTimeout(() => finish({ error: 'login_required' }), LOGIN_LIMITS.silentTimeoutMs);
            this.cancellations.add(cancel);
            this.win.addEventListener('message', onMessage);
            // Hidden with an inline style too: a page's own `iframe { display: … }` rule would beat `[hidden]`.
            frame.hidden = true;
            frame.style.display = 'none';
            frame.tabIndex = -1;
            frame.title = 'EpicStaff sign-in';
            frame.setAttribute('aria-hidden', 'true');
            frame.src = this.authorizeUrl(state, challenge, org, true);
            (document.body ?? document.documentElement).append(frame);
        });
    }

    /**
     * Keeps a PKCE verifier and the page's address in `sessionStorage`, then replaces the page with the authorize
     * endpoint: a frame navigation must not add an entry to EpicStaff's history. The callback page brings the answer
     * back to `returnPath`, where `start()` finishes the sign-in.
     */
    private async navigateToLogin(org: number | null, returnPath: string): Promise<void> {
        const pkce = await createPkcePair(this.win.crypto);
        const pending: PendingLogin = {
            state: randomToken(this.win.crypto),
            code_verifier: pkce.verifier,
            return_path: returnPath,
            org,
            created_at: Date.now(),
        };
        try {
            this.win.sessionStorage.setItem(LOGIN_STORAGE_KEYS.pending, JSON.stringify(pending));
        } catch {
            this.fail('storage_unavailable', 'sessionStorage is not available, so the sign-in cannot return here.');
            return;
        }
        this.clearRenewal();
        this.setState('signing-in');
        this.win.location.replace(this.authorizeUrl(pending.state, pkce.challenge, org, false));
    }

    /** Takes the callback page's answer and the pending sign-in it belongs to out of `sessionStorage`. */
    private takeReturnedLogin(): ReturnedLogin | null {
        const storage = sessionStorageOf(this.win);
        const rawResult = storage?.getItem(LOGIN_STORAGE_KEYS.result) ?? null;
        if (storage === null || rawResult === null) return null;
        const rawPending = storage.getItem(LOGIN_STORAGE_KEYS.pending);
        storage.removeItem(LOGIN_STORAGE_KEYS.result);
        storage.removeItem(LOGIN_STORAGE_KEYS.pending);

        const result = parseJson(rawResult);
        const pending = parseJson(rawPending);
        if (!isRecord(result) || !isRecord(pending)) return null;
        const state = pending['state'];
        const verifier = pending['code_verifier'];
        const createdAt = pending['created_at'];
        if (typeof state !== 'string' || !LOGIN_PATTERNS.state.test(state) || result['state'] !== state) return null;
        if (typeof verifier !== 'string' || !LOGIN_PATTERNS.codeVerifier.test(verifier)) return null;
        if (typeof createdAt !== 'number' || Date.now() - createdAt >= LOGIN_LIMITS.pendingMaxAgeSeconds * 1000) {
            return null;
        }
        const org = pending['org'];
        return { verifier, org: isPositiveId(org) ? org : null, answer: readAnswer(result) };
    }

    /** `retryStaleOrg`: whether a refusal of a stored org hint may start over without it (not for a popup's org). */
    private async finishReturnedLogin(returned: ReturnedLogin, retryStaleOrg: boolean): Promise<LoginState> {
        const answer = returned.answer;
        if (answer !== null && 'code' in answer) return this.exchange(answer.code, returned.verifier);
        if (answer?.error === 'access_denied') {
            return retryStaleOrg && this.isStaleStoredOrg(returned.org) ? this.signInWithoutStoredOrg() : this.deny();
        }
        if (answer?.error === 'temporarily_unavailable') return this.holdForMaintenance();
        return this.fail(
            'callback_failed',
            answer === null
                ? 'EpicStaff sent no sign-in result back.'
                : `EpicStaff answered "${answer.error}" to an interactive sign-in.`
        );
    }

    /** Exchanges a code for a token: cross-origin JSON, never with cookies. */
    private async exchange(code: string, verifier: string): Promise<LoginState> {
        let response: Response;
        try {
            response = await this.fetchImplementation(this.endpoints.token_url, {
                method: 'POST',
                credentials: 'omit',
                headers: { 'content-type': 'application/json' },
                body: JSON.stringify({ code, code_verifier: verifier }),
            });
        } catch (error) {
            return this.fail(
                'exchange_failed',
                `EpicStaff's token endpoint could not be reached: ${describeError(error)}`
            );
        }
        const body = await readJsonBody(response);
        if (this.closed) return this.currentState;
        if (!response.ok) {
            const errorCode = isRecord(body) && typeof body['code'] === 'string' ? body['code'] : null;
            if (response.status === 403 && errorCode === 'plugin_access_denied') return this.deny();
            return this.fail(
                'exchange_failed',
                `EpicStaff refused the sign-in (HTTP ${response.status}${errorCode ? `, ${errorCode}` : ''}).`
            );
        }
        const answer = parseTokenAnswer(body, this.config.plugin.identifier);
        if (answer === null) {
            return this.fail('invalid_token_response', "EpicStaff's token endpoint answered with an unexpected body.");
        }
        this.token = answer.token;
        this.currentSession = { ...answer.session, expiresAt: Date.now() + answer.lifetimeSeconds * 1000 };
        this.currentError = null;
        this.lastOrgId = answer.session.org.id;
        this.storeOrg(answer.session.org.id);
        this.scheduleRenewal(answer.lifetimeSeconds);
        // EpicStaff signs nobody in while the plugin is being updated in the organization: that is over.
        this.maintenanceFromSignIn = false;
        if (this.currentAvailability === 'maintenance') this.setAvailability('available');
        this.setState('signed-in', true);
        return this.currentState;
    }

    private deny(): LoginState {
        this.dropToken();
        this.currentError = null;
        this.endSignInMaintenance();
        this.setState('access-denied');
        return this.currentState;
    }

    /**
     * The plugin is being updated in the person's organization: no token until it is back. Never navigates, so a page
     * opened on its own does not loop through EpicStaff's login; `renew()` tries again.
     */
    private holdForMaintenance(): LoginState {
        this.dropToken();
        this.currentError = null;
        this.setAvailability('maintenance');
        this.maintenanceFromSignIn = true;
        this.setState('maintenance');
        return this.currentState;
    }

    /** Inside EpicStaff the page offers "Sign in again"; on its own it goes to EpicStaff's login at once. */
    private endSession(): LoginState {
        this.dropToken();
        this.currentError = null;
        this.endSignInMaintenance();
        this.setState('session-ended');
        if (this.win.parent === this.win) void this.signIn();
        return this.currentState;
    }

    private fail(code: PluginLoginError['code'], message: string): LoginState {
        this.dropToken();
        this.currentError = new PluginLoginError(code, message);
        this.endSignInMaintenance();
        this.setState('failed');
        return this.currentState;
    }

    /**
     * A sign-in answered something other than maintenance (denied, ended or failed): EpicStaff no longer refuses
     * sign-in for an update, so a maintenance that sign-in reported is over. Otherwise a page would show "being
     * updated" for good after an upgrade that failed for the organization. A maintenance or `unavailable` the API
     * answered is the API's own state: only the API says it is back.
     */
    private endSignInMaintenance(): void {
        if (!this.maintenanceFromSignIn) return;
        this.maintenanceFromSignIn = false;
        if (this.currentAvailability === 'maintenance') this.setAvailability('available');
    }

    private dropToken(): void {
        this.token = null;
        this.currentSession = null;
        this.clearRenewal();
    }

    /** Renews `renew_before_expiry_seconds` before expiry, but never sooner than halfway through the token's life. */
    private scheduleRenewal(lifetimeSeconds: number): void {
        this.clearRenewal();
        if (this.closed) return;
        const lifetimeMs = lifetimeSeconds * 1000;
        const delay = Math.max(lifetimeMs / 2, lifetimeMs - LOGIN_LIMITS.renewBeforeExpirySeconds * 1000);
        this.renewTimer = setTimeout(() => {
            this.renewTimer = null;
            void this.renew();
        }, delay);
    }

    private clearRenewal(): void {
        if (this.renewTimer !== null) clearTimeout(this.renewTimer);
        this.renewTimer = null;
    }

    private setState(next: LoginState, notifyUnchanged = false): void {
        if (next === this.currentState && !notifyUnchanged) return;
        this.currentState = next;
        for (const listener of [...this.listeners]) listener(next);
    }

    private setAvailability(next: PluginAvailability): void {
        if (next === this.currentAvailability || this.closed) return;
        this.currentAvailability = next;
        this.reportAvailability(next);
        for (const listener of [...this.availabilityListeners]) listener(next);
    }

    /**
     * What the gateway's answer says about the plugin's API: a `503` with `maintenance` or `unavailable` is that state;
     * anything that passed the gateway is `available`. Its other refusals say nothing about it.
     */
    private observeAvailability(response: Response): void {
        if (passedGateway(response)) {
            this.maintenanceFromSignIn = false;
            this.setAvailability('available');
            return;
        }
        const refusal = gatewayRefusal(response);
        if (response.status !== 503 || refusal === null) return;
        if (refusal.reason === 'maintenance' || refusal.reason === 'unavailable') {
            this.maintenanceFromSignIn = false;
            this.setAvailability(refusal.reason);
        }
    }

    /**
     * Waits for a sign-in or renewal under way, and renews a token that is due, so a request goes out with the newest
     * token. The renewal timer alone is not enough: browsers delay timers in background tabs and while asleep.
     */
    private async settled(): Promise<void> {
        if (this.startRun !== null && this.currentState === 'signing-in') await this.startRun;
        if (this.renewRun === null && this.isRenewalDue()) void this.renew();
        if (this.renewRun !== null) await this.renewRun;
    }

    /** A token is due for renewal from `renew_before_expiry_seconds` before it expires. */
    private isRenewalDue(): boolean {
        const session = this.currentSession;
        return (
            this.currentState === 'signed-in' &&
            session !== null &&
            Date.now() >= session.expiresAt - LOGIN_LIMITS.renewBeforeExpirySeconds * 1000
        );
    }

    /**
     * The org hint came from this tab's last token and EpicStaff refused it (the person lost access there, or the org
     * is gone). Only on the plugin's own address: inside EpicStaff, `es_org` is the org the person opened, and a refusal
     * there is the answer.
     */
    private isStaleStoredOrg(org: number | null): boolean {
        return org !== null && this.orgHintIsStored && org === this.orgHint && this.win.parent === this.win;
    }

    /** Forgets the stored org and signs in again without one: EpicStaff takes the person's only org, or asks. */
    private async signInWithoutStoredOrg(): Promise<LoginState> {
        try {
            this.win.sessionStorage.removeItem(LOGIN_ORG_STORAGE_KEY);
        } catch {
            // Nothing stored to forget.
        }
        this.orgHint = null;
        this.orgHintIsStored = false;
        await this.navigateToLogin(null, currentReturnPath(this.win));
        return this.currentState;
    }

    /** Sends a request to the plugin's own API, with the token when there is one, and notes its availability. */
    private async sendToApi(url: URL, init: RequestInit, token: string | null): Promise<Response> {
        const headers = new Headers(init.headers);
        if (token !== null) headers.set('authorization', `Bearer ${token}`);
        const response = await this.fetchImplementation(url.href, { ...init, headers });
        if (!this.closed) this.observeAvailability(response);
        return response;
    }

    /** The plugin's own API: this page's origin, and a path at or below `api_base`. */
    private isOwnApi(url: URL): boolean {
        if (url.origin !== this.win.location.origin) return false;
        const base = this.config.api_base.endsWith('/') ? this.config.api_base : `${this.config.api_base}/`;
        return url.pathname.startsWith(base) || url.pathname === base.slice(0, -1);
    }

    /** The parameters in the order of `authorize_params` in login-protocol.json; `prompt=none` only for a silent sign-in. */
    private authorizeUrl(state: string, challenge: string, org: number | null, silent: boolean): string {
        const query = new URLSearchParams();
        query.set('plugin', this.config.plugin.identifier);
        query.set('state', state);
        query.set('code_challenge', challenge);
        query.set('code_challenge_method', LOGIN_CODE_CHALLENGE_METHOD);
        if (org !== null) query.set('org', String(org));
        if (silent) query.set('prompt', 'none');
        return `${this.endpoints.authorize_url}?${query.toString()}`;
    }

    private currentOrg(): number | null {
        return this.currentSession?.org.id ?? this.lastOrgId ?? this.orgHint;
    }

    private readStoredOrg(): number | null {
        const stored = sessionStorageOf(this.win)?.getItem(LOGIN_ORG_STORAGE_KEY) ?? null;
        if (stored === null || !ORG_ID_TEXT.test(stored)) return null;
        const org = Number(stored);
        return Number.isSafeInteger(org) ? org : null;
    }

    private storeOrg(org: number): void {
        try {
            this.win.sessionStorage.setItem(LOGIN_ORG_STORAGE_KEY, String(org));
        } catch {
            // Only a hint for the next load; signing in still works without it.
        }
    }

    private popupPort(): PopupLoginPort {
        return {
            window: this.win,
            fetch: (input, init) => this.fetch(input, init),
            finishReturnedLogin: async () => {
                const returned = this.takeReturnedLogin();
                if (returned === null) return null;
                this.setState('signing-in');
                // A popup signs in to the org its provider state names, never another one.
                const state = await this.finishReturnedLogin(returned, false);
                return state === 'signed-in' || state === 'access-denied' ? state : 'failed';
            },
            signInTo: (org, returnPath) => this.navigateToLogin(org, returnPath),
            lastError: () => this.currentError,
            track: (cancel) => {
                this.cancellations.add(cancel);
                return () => this.cancellations.delete(cancel);
            },
        };
    }
}

/** The page's address to come back to after an interactive sign-in; `/` when it is not a valid return path. */
function currentReturnPath(win: Window): string {
    const { pathname, search, hash } = win.location;
    const path = pathname + search + hash;
    return LOGIN_PATTERNS.returnPath.test(path) ? path : '/';
}

/** A known `error` wins over a `code`; a code must have the code's shape. `null` when there is neither. */
function readAnswer(data: Record<string, unknown>): AuthorizeAnswer | null {
    const error = LOGIN_CALLBACK_ERRORS.find((known) => known === data['error']);
    if (error !== undefined) return { error };
    const code = data['code'];
    return typeof code === 'string' && LOGIN_PATTERNS.code.test(code) ? { code } : null;
}

function parseTokenAnswer(body: unknown, identifier: string): TokenAnswer | null {
    if (!isRecord(body)) return null;
    const token = body['access_token'];
    const lifetime = body['expires_in'];
    const plugin = body['plugin'];
    const org = body['org'];
    const user = body['user'];
    const permissions = body['plugin_permissions'];
    if (typeof token !== 'string' || token === '' || body['token_type'] !== 'Bearer') return null;
    if (typeof lifetime !== 'number' || !Number.isSafeInteger(lifetime) || lifetime <= 0) return null;
    if (!isRecord(plugin) || plugin['identifier'] !== identifier || typeof plugin['version'] !== 'string') return null;
    if (!isRecord(org) || !isPositiveId(org['id']) || typeof org['name'] !== 'string') return null;
    if (!isRecord(user) || !isPositiveId(user['id'])) return null;
    if (typeof user['email'] !== 'string' || typeof user['name'] !== 'string') return null;
    if (!Array.isArray(permissions) || !permissions.every((action) => typeof action === 'string')) return null;
    return {
        token,
        lifetimeSeconds: lifetime,
        session: {
            plugin: { identifier, version: plugin['version'] },
            org: { id: org['id'], name: org['name'] },
            user: { id: user['id'], email: user['email'], name: user['name'] },
            permissions: [...permissions] as string[],
        },
    };
}

function isPositiveId(value: unknown): value is number {
    return typeof value === 'number' && Number.isSafeInteger(value) && value > 0;
}

function parseJson(text: string | null): unknown {
    if (text === null) return null;
    try {
        return JSON.parse(text);
    } catch {
        return null;
    }
}

async function readJsonBody(response: Response): Promise<unknown> {
    try {
        return await response.json();
    } catch {
        return null;
    }
}

/** A stream body can be sent only once. */
function isReplayable(init: RequestInit): boolean {
    return !(typeof ReadableStream === 'function' && init.body instanceof ReadableStream);
}
