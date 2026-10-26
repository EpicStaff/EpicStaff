import { describeError, PluginLoginError } from './login-error.js';
import {
    LOGIN_LIMITS,
    LOGIN_MESSAGE_TYPES,
    LOGIN_PATTERNS,
    LOGIN_PROTOCOL_VERSION,
    LOGIN_STORAGE_KEYS,
} from './login-protocol.js';
import { randomToken } from './pkce.js';
import { isRecord } from './protocol.js';

/** The size of the window `openPopup` opens; providers' sign-in pages fit it. */
const POPUP_FEATURES = 'popup,width=520,height=680';

export interface OpenPopupOptions {
    /** The `state` the plugin gave the provider, made by {@link createPopupState}. */
    state: string;
    /**
     * The plugin's relay, for a provider that severs the popup from its opener (`Cross-Origin-Opener-Policy`). The
     * SDK asks `statusPath` on the plugin's own API every 2 seconds, with the person's token, until it answers
     * `200 {"status":"done", …}`.
     */
    relay?: { statusPath: string };
}

export interface PopupResult {
    /** How the result came back: the popup's message to its opener, or the plugin's relay. */
    via: 'opener' | 'relay';
    /** The parameters the provider sent to the plugin's return page (query and fragment). */
    params: Record<string, string>;
    /** The relay's whole answer (`{"status":"done", …}`); `null` when the opener path won. */
    relayBody: Record<string, unknown> | null;
}

export interface CompletePopupOptions {
    /**
     * The plugin's relay endpoint on its own API (`POST {"state", "params"}`). Without it, a popup the provider
     * severed from its opener cannot hand its result back.
     */
    relayPath?: string;
}

export type CompletePopupOutcome =
    /** Handed to the opener; the window closes. */
    | { status: 'posted' }
    /** Handed to the plugin's relay; the window closes where the browser allows it. */
    | { status: 'relayed' }
    /** The window is on its way to EpicStaff to sign in; the page calls `completePopup` again when it returns. */
    | { status: 'signing-in' }
    /** No opener and no `relayPath`: the result cannot be handed back. */
    | { status: 'no-opener' }
    /** The page has no provider result with a valid `state`. */
    | { status: 'invalid' }
    /** The person may not use the plugin in the organization the `state` names. */
    | { status: 'access-denied' }
    | { status: 'failed'; error: PluginLoginError };

/** What the popup helpers need from the person's sign-in. */
export interface PopupLoginPort {
    readonly window: Window;
    /** `PluginLogin.fetch`: adds the person's token on the plugin's own API. */
    fetch(input: string, init?: RequestInit): Promise<Response>;
    /** Finishes an interactive sign-in that just came back; `null` when none did. */
    finishReturnedLogin(): Promise<'signed-in' | 'access-denied' | 'failed' | null>;
    /** Starts an interactive sign-in for this organization that returns to `returnPath`. */
    signInTo(org: number, returnPath: string): Promise<void>;
    /** Why the last sign-in failed. */
    lastError(): PluginLoginError | null;
    /** Runs `cancel` when the sign-in is closed; returns the function that forgets it. */
    track(cancel: () => void): () => void;
}

interface SavedPopupResult {
    state: string;
    params: Record<string, string>;
}

/**
 * A `state` for an external provider's OAuth request: `<org id>.<random>`. The organization lets a popup that lost its
 * opener sign in to the same organization; the random part (32 bytes) makes it unguessable. The plugin keeps it and
 * checks the provider sends it back unchanged.
 */
export function createPopupState(orgId: number, crypto: Crypto = globalThis.crypto): string {
    const state = `${orgId}.${randomToken(crypto)}`;
    if (!Number.isSafeInteger(orgId) || !LOGIN_PATTERNS.popupState.test(state)) {
        throw new PluginLoginError('invalid_popup_state', 'The organization id must be a positive integer.');
    }
    return state;
}

/**
 * Opens `url` in a popup and resolves with the provider's result: the first of the popup's message to this page and,
 * with `relay`, the relay's answer. Call it from a click or key press handler, before any `await`: browsers block
 * popups opened later. `popup.closed` is not used, because it reads `true` once a provider severs the popup.
 */
export function openPopup(port: PopupLoginPort, url: string | URL, options: OpenPopupOptions): Promise<PopupResult> {
    const win = port.window;
    if (!LOGIN_PATTERNS.popupState.test(options.state)) {
        return Promise.reject(
            new PluginLoginError('invalid_popup_state', 'The popup state must come from createPopupState.')
        );
    }
    const target = httpUrl(url, win.location.origin);
    if (target === null) {
        return Promise.reject(new PluginLoginError('invalid_popup_url', 'A popup can open only an http(s) address.'));
    }
    const popup = win.open(target, '_blank', POPUP_FEATURES);
    if (popup === null) {
        return Promise.reject(
            new PluginLoginError('popup_blocked', 'The browser blocked the popup. Open it from a click handler.')
        );
    }

    return new Promise<PopupResult>((resolve, reject) => {
        let settled = false;
        let pollTimer: ReturnType<typeof setTimeout> | null = null;

        const settle = (): boolean => {
            if (settled) return false;
            settled = true;
            clearTimeout(deadline);
            if (pollTimer !== null) clearTimeout(pollTimer);
            win.removeEventListener('message', onMessage);
            untrack();
            return true;
        };
        const succeed = (result: PopupResult): void => {
            if (settle()) resolve(result);
        };
        const fail = (error: PluginLoginError): void => {
            if (settle()) reject(error);
        };

        const onMessage = (event: MessageEvent): void => {
            if (event.origin !== win.location.origin || event.source !== popup) return;
            const data: unknown = event.data;
            if (
                !isRecord(data) ||
                data['type'] !== LOGIN_MESSAGE_TYPES.popupResult ||
                data['protocol'] !== LOGIN_PROTOCOL_VERSION ||
                data['state'] !== options.state
            ) {
                return;
            }
            const params = readStringRecord(data['params']);
            if (params !== null) succeed({ via: 'opener', params, relayBody: null });
        };

        const poll = async (statusPath: string): Promise<void> => {
            pollTimer = null;
            try {
                const response = await port.fetch(statusPath);
                if (response.status === 200) {
                    const body: unknown = await response.json();
                    if (isRecord(body) && body['status'] === 'done') {
                        succeed({ via: 'relay', params: readStringRecord(body['params']) ?? {}, relayBody: body });
                        return;
                    }
                }
            } catch {
                // A failed poll is retried on the next tick, until the deadline.
            }
            if (!settled) pollTimer = setTimeout(() => void poll(statusPath), LOGIN_LIMITS.popupRelayPollMs);
        };

        const deadline = setTimeout(
            () => fail(new PluginLoginError('popup_timeout', 'No result came back from the popup in time.')),
            LOGIN_LIMITS.popupRelayTimeoutSeconds * 1000
        );
        const untrack = port.track(() => fail(new PluginLoginError('closed', 'The sign-in was closed.')));
        win.addEventListener('message', onMessage);
        const statusPath = options.relay?.statusPath;
        if (statusPath !== undefined) {
            pollTimer = setTimeout(() => void poll(statusPath), LOGIN_LIMITS.popupRelayPollMs);
        }
    });
}

/**
 * Runs on the plugin's own page the provider returns to. With an opener, posts the provider's parameters to it (own
 * origin only) and closes. Without one, and with `relayPath`, keeps the parameters in `sessionStorage`, removes them
 * from the address, signs in to the organization the `state` names (a top-level navigation; the parameters never go to
 * EpicStaff), and then posts them to the plugin's relay.
 */
export async function completePopup(
    port: PopupLoginPort,
    options: CompletePopupOptions = {}
): Promise<CompletePopupOutcome> {
    const win = port.window;
    const params = collectParams(win.location);
    const hasParams = Object.keys(params).length > 0;
    const opener = win.opener as Window | null;

    if (opener !== null && !opener.closed) {
        const state = params['state'];
        if (state === undefined) return { status: 'invalid' };
        opener.postMessage(
            { type: LOGIN_MESSAGE_TYPES.popupResult, protocol: LOGIN_PROTOCOL_VERSION, state, params },
            win.location.origin
        );
        win.close();
        return { status: 'posted' };
    }
    if (options.relayPath === undefined) return { status: 'no-opener' };

    const storage = sessionStorageOf(win);
    if (storage === null) {
        return {
            status: 'failed',
            error: new PluginLoginError('storage_unavailable', 'sessionStorage is not available on this page.'),
        };
    }
    if (hasParams) {
        const state = params['state'];
        if (state === undefined || !LOGIN_PATTERNS.popupState.test(state)) return { status: 'invalid' };
        storage.setItem(LOGIN_STORAGE_KEYS.popup, JSON.stringify({ state, params } satisfies SavedPopupResult));
        win.history.replaceState(win.history.state, '', win.location.pathname);
    }
    const saved = readSavedPopupResult(storage);
    if (saved === null) return { status: 'invalid' };

    const signedIn = await port.finishReturnedLogin();
    if (signedIn === null) {
        await port.signInTo(Number(saved.state.split('.', 1)[0]), win.location.pathname);
        return { status: 'signing-in' };
    }
    if (signedIn === 'access-denied') return { status: 'access-denied' };
    if (signedIn === 'failed') {
        return {
            status: 'failed',
            error: port.lastError() ?? new PluginLoginError('callback_failed', 'The sign-in did not complete.'),
        };
    }

    let response: Response;
    try {
        response = await port.fetch(options.relayPath, {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({ state: saved.state, params: saved.params }),
        });
    } catch (error) {
        return {
            status: 'failed',
            error: new PluginLoginError('relay_failed', `The relay could not be reached: ${describeError(error)}`),
        };
    }
    if (!response.ok) {
        return {
            status: 'failed',
            error: new PluginLoginError('relay_failed', `The relay answered HTTP ${response.status}.`),
        };
    }
    storage.removeItem(LOGIN_STORAGE_KEYS.popup);
    win.close();
    return { status: 'relayed' };
}

/** `url` resolved against the page's origin, when it is an `http:` or `https:` address; `null` otherwise. */
function httpUrl(url: string | URL, origin: string): string | null {
    try {
        const target = new URL(url, origin);
        return target.protocol === 'https:' || target.protocol === 'http:' ? target.href : null;
    } catch {
        return null;
    }
}

/** The query and fragment parameters of the address; a fragment parameter wins over a query one of the same name. */
function collectParams(location: Location): Record<string, string> {
    const collected = new Map<string, string>();
    for (const source of [location.search.slice(1), location.hash.slice(1)]) {
        for (const [name, value] of new URLSearchParams(source)) collected.set(name, value);
    }
    return Object.fromEntries(collected);
}

function readSavedPopupResult(storage: Storage): SavedPopupResult | null {
    let saved: unknown;
    try {
        saved = JSON.parse(storage.getItem(LOGIN_STORAGE_KEYS.popup) ?? 'null');
    } catch {
        return null;
    }
    if (!isRecord(saved)) return null;
    const state = saved['state'];
    const params = readStringRecord(saved['params']);
    if (typeof state !== 'string' || !LOGIN_PATTERNS.popupState.test(state) || params === null) return null;
    return { state, params };
}

/** A JSON object of string values, rebuilt so no key can reach the prototype; `null` for anything else. */
function readStringRecord(value: unknown): Record<string, string> | null {
    if (!isRecord(value)) return null;
    const entries = Object.entries(value);
    if (entries.some(([, item]) => typeof item !== 'string')) return null;
    return Object.fromEntries(entries) as Record<string, string>;
}

export function sessionStorageOf(win: Window): Storage | null {
    try {
        return win.sessionStorage;
    } catch {
        return null;
    }
}
