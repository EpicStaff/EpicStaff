/**
 * EpicStaff's side of a sign-in, faked: the platform config with login endpoints, the token endpoint and the plugin's
 * own API behind one `fetch`, and answers to the hidden sign-in frame.
 */
import { performance } from 'node:perf_hooks';

import { parsePlatformConfig, type PluginLoginSource } from '../../dist/index.js';
import { EPICSTAFF_ORIGIN, type FakeFrame, type FakeWindow, PLUGIN_ORIGIN } from './fake-window.ts';

export const AUTHORIZE_URL = `${EPICSTAFF_ORIGIN}/api/auth/plugin-authorize/`;
export const TOKEN_URL = `${EPICSTAFF_ORIGIN}/api/auth/plugin-token/`;
/** Authorization codes have exactly 43 base64url characters. */
export const CODE = 'C'.repeat(43);
export const OTHER_CODE = 'D'.repeat(43);

export function pluginSource(orgHint: number | null = 3): PluginLoginSource {
    return {
        config: parsePlatformConfig({
            plugin: { identifier: 'weather', name: 'Weather', version: '0.3.0' },
            epicstaff_origin: EPICSTAFF_ORIGIN,
            frame_protocol: 1,
            api_base: '/api/',
            login: { authorize_url: AUTHORIZE_URL, token_url: TOKEN_URL },
        }),
        orgHint,
    };
}

export function tokenBody(token: string, overrides: Record<string, unknown> = {}): Record<string, unknown> {
    return {
        access_token: token,
        token_type: 'Bearer',
        expires_in: 900,
        plugin: { identifier: 'weather', version: '0.3.0' },
        org: { id: 3, name: 'Acme' },
        user: { id: 42, email: 'ada@acme.test', name: 'Ada' },
        plugin_permissions: ['read'],
        ...overrides,
    };
}

export function json(status: number, body: unknown, headers: Record<string, string> = {}): Response {
    return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json', ...headers } });
}

/** A refusal EpicStaff's gateway answers itself, with its body and the header only the gateway sets. */
export function gatewayDeny(
    status: 401 | 403,
    reason: string,
    code = status === 401 ? 'login_required' : 'forbidden'
): Response {
    return json(status, { status_code: status, code, message: '' }, { 'X-EpicStaff-Gateway-Deny': reason });
}

export interface RecordedRequest {
    url: string;
    init: RequestInit;
    authorization: string | null;
}

type Responder = (request: RecordedRequest) => Response | Promise<Response>;

/** EpicStaff's token endpoint and the plugin's API, recording every request. */
export class FakeServer {
    readonly requests: RecordedRequest[] = [];
    /** Hands out `token-1`, `token-2`, … unless replaced. */
    tokenResponder: Responder;
    apiResponder: Responder = () => json(200, { ok: true });
    private issued = 0;

    constructor() {
        this.tokenResponder = () => json(200, tokenBody(`token-${++this.issued}`));
    }

    readonly fetch = (async (input: string | URL | Request, init: RequestInit = {}): Promise<Response> => {
        const request: RecordedRequest = {
            url: String(input),
            init,
            authorization: new Headers(init.headers).get('authorization'),
        };
        this.requests.push(request);
        return request.url === TOKEN_URL ? this.tokenResponder(request) : this.apiResponder(request);
    }) as typeof fetch;

    get tokenRequests(): RecordedRequest[] {
        return this.requests.filter((request) => request.url === TOKEN_URL);
    }

    get apiRequests(): RecordedRequest[] {
        return this.requests.filter((request) => request.url !== TOKEN_URL);
    }
}

/**
 * Resolves once `predicate` holds. Polls with `setImmediate` and the real clock, so it also works while a test mocks
 * `setTimeout`.
 */
export async function until(predicate: () => boolean, timeoutMs = 2000): Promise<void> {
    const start = performance.now();
    while (!predicate()) {
        if (performance.now() - start > timeoutMs) throw new Error('Timed out waiting for a condition.');
        await new Promise((resolve) => setImmediate(resolve));
    }
}

/** Lets pending promise chains and `setImmediate` work run: a few turns of the event loop, real timers untouched. */
export async function flush(turns = 10): Promise<void> {
    for (let turn = 0; turn < turns; turn++) await new Promise((resolve) => setImmediate(resolve));
}

export interface SilentFrame {
    frame: FakeFrame;
    url: URL;
    state: string;
}

/** Frames {@link nextSilentFrame} already handed out. */
const takenFrames = new WeakSet<FakeFrame>();

/** The next hidden sign-in frame the page attached and has not removed, which no earlier call handed out. */
export async function nextSilentFrame(win: FakeWindow): Promise<SilentFrame> {
    const untaken = (): FakeFrame | undefined =>
        win.document.body.children.find((frame) => !frame.removed && !takenFrames.has(frame));
    await until(() => untaken() !== undefined);
    const frame = untaken() as FakeFrame;
    takenFrames.add(frame);
    const url = new URL(frame.src);
    return { frame, url, state: url.searchParams.get('state') ?? '' };
}

/** What the silent callback page posts, delivered as coming from the frame on the plugin's origin. */
export function postFromFrame(win: FakeWindow, silent: SilentFrame, reply: Record<string, unknown>): void {
    win.deliverMessage(
        { type: 'es:login-result', protocol: 1, state: silent.state, ...reply },
        silent.frame.contentWindow,
        PLUGIN_ORIGIN
    );
}

/** Waits for the next hidden frame and answers it. */
export async function answerSilently(win: FakeWindow, reply: Record<string, unknown>): Promise<SilentFrame> {
    const silent = await nextSilentFrame(win);
    postFromFrame(win, silent, reply);
    return silent;
}
