import { FRAME_PROTOCOL_VERSION, isRecord } from './protocol.js';

/** Where every plugin host serves the platform config, on the plugin's own origin. */
export const PLATFORM_CONFIG_PATH = '/.well-known/epicstaff/config.json';

/** What EpicStaff tells a plugin page about the platform it runs on. */
export interface PlatformConfig {
    plugin: { identifier: string; name: string; version: string };
    /** EpicStaff's origin, for example `https://epicstaff.example.com`: the only parent the frame protocol talks to. */
    epicstaff_origin: string;
    frame_protocol: typeof FRAME_PROTOCOL_VERSION;
    /** The plugin's own API prefix, on the plugin's origin. */
    api_base: string;
    /** EpicStaff's sign-in endpoints; `null` for a plugin without a backend, which has nothing to sign in to. */
    login: PlatformLogin | null;
}

/** Where a plugin page signs a person in. Both URLs are on `epicstaff_origin`. */
export interface PlatformLogin {
    /** EpicStaff's authorize endpoint, opened as a navigation (never fetched). */
    authorize_url: string;
    /** EpicStaff's token endpoint, which exchanges a code for a plugin login token. */
    token_url: string;
}

export class PlatformConfigError extends Error {
    override readonly name = 'PlatformConfigError';
}

export interface LoadPlatformConfigOptions {
    /** Defaults to the global `fetch`. */
    fetch?: typeof fetch;
    /** Origin to load from; defaults to the page's own (a relative request). */
    baseUrl?: string;
}

/** Loads and checks the platform config of the plugin host the page was served from. */
export async function loadPlatformConfig(options: LoadPlatformConfigOptions = {}): Promise<PlatformConfig> {
    const fetchConfig = options.fetch ?? globalThis.fetch.bind(globalThis);
    const url =
        options.baseUrl === undefined ? PLATFORM_CONFIG_PATH : new URL(PLATFORM_CONFIG_PATH, options.baseUrl).href;
    let response: Response;
    try {
        response = await fetchConfig(url, { headers: { accept: 'application/json' }, credentials: 'omit' });
    } catch (error) {
        throw new PlatformConfigError(`Could not load ${PLATFORM_CONFIG_PATH}: ${describe(error)}`);
    }
    if (!response.ok) {
        throw new PlatformConfigError(`Could not load ${PLATFORM_CONFIG_PATH}: HTTP ${response.status}.`);
    }
    let body: unknown;
    try {
        body = await response.json();
    } catch {
        throw new PlatformConfigError(`${PLATFORM_CONFIG_PATH} is not JSON.`);
    }
    return parsePlatformConfig(body);
}

/** Checks a platform config document; throws {@link PlatformConfigError} naming the first problem. */
export function parsePlatformConfig(value: unknown): PlatformConfig {
    if (!isRecord(value)) throw new PlatformConfigError('The platform config must be a JSON object.');
    const plugin = value['plugin'];
    if (
        !isRecord(plugin) ||
        !isNonEmptyString(plugin['identifier']) ||
        !isNonEmptyString(plugin['name']) ||
        !isNonEmptyString(plugin['version'])
    ) {
        throw new PlatformConfigError('"plugin" must name the identifier, name and version.');
    }
    const epicstaffOrigin = value['epicstaff_origin'];
    if (!isHttpOrigin(epicstaffOrigin)) {
        throw new PlatformConfigError('"epicstaff_origin" must be an http(s) origin.');
    }
    if (value['frame_protocol'] !== FRAME_PROTOCOL_VERSION) {
        throw new PlatformConfigError(`"frame_protocol" must be ${FRAME_PROTOCOL_VERSION}.`);
    }
    const apiBase = value['api_base'];
    if (!isNonEmptyString(apiBase) || !apiBase.startsWith('/')) {
        throw new PlatformConfigError('"api_base" must be a path.');
    }
    return {
        plugin: { identifier: plugin['identifier'], name: plugin['name'], version: plugin['version'] },
        epicstaff_origin: epicstaffOrigin,
        frame_protocol: FRAME_PROTOCOL_VERSION,
        api_base: apiBase,
        login: parseLogin(value['login'] ?? null, epicstaffOrigin),
    };
}

function parseLogin(value: unknown, epicstaffOrigin: string): PlatformLogin | null {
    if (value === null) return null;
    if (!isRecord(value)) throw new PlatformConfigError('"login" must be null or an object.');
    const authorizeUrl = value['authorize_url'];
    const tokenUrl = value['token_url'];
    if (!isEndpointOn(authorizeUrl, epicstaffOrigin) || !isEndpointOn(tokenUrl, epicstaffOrigin)) {
        throw new PlatformConfigError(
            '"login.authorize_url" and "login.token_url" must be URLs on "epicstaff_origin", without a query.'
        );
    }
    return { authorize_url: authorizeUrl, token_url: tokenUrl };
}

/** An absolute URL on `origin` with a path and no credentials, query or fragment. */
function isEndpointOn(value: unknown, origin: string): value is string {
    if (typeof value !== 'string') return false;
    try {
        const url = new URL(value);
        return (
            url.origin === origin &&
            url.href === value &&
            url.search === '' &&
            url.hash === '' &&
            !url.username &&
            !url.password
        );
    } catch {
        return false;
    }
}

function isNonEmptyString(value: unknown): value is string {
    return typeof value === 'string' && value !== '';
}

/** `scheme://host[:port]` exactly, with no path, query or credentials. */
function isHttpOrigin(value: unknown): value is string {
    if (typeof value !== 'string') return false;
    try {
        const url = new URL(value);
        return (url.protocol === 'https:' || url.protocol === 'http:') && url.origin === value;
    } catch {
        return false;
    }
}

function describe(error: unknown): string {
    return error instanceof Error ? error.message : String(error);
}
