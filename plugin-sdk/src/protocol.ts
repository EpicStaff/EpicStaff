/**
 * EpicStaff frame protocol 1: the messages a plugin page and the EpicStaff page that frames it exchange.
 *
 * Handshake on `window`: the plugin page posts `es:ready` to `window.parent` with the EpicStaff origin from the
 * platform config as the target; EpicStaff answers with `es:init` and transfers one `MessagePort`, or with `es:error`.
 * Every later message travels on that port. Unknown `type` values are ignored on both sides.
 *
 * `contracts/frame-protocol.json` is the single source of these values; a test asserts the constants below equal it.
 */

export const FRAME_PROTOCOL_VERSION = 1;

export const FRAME_MESSAGE_TYPES = {
    ready: 'es:ready',
    init: 'es:init',
    error: 'es:error',
    navChanged: 'nav.changed',
    navNavigate: 'nav.navigate',
    themeChanged: 'theme.changed',
    availabilityChanged: 'availability.changed',
} as const;

export const FRAME_ERROR_CODES = ['unsupported_protocol'] as const;

/** Why EpicStaff refused the handshake. */
export type FrameErrorCode = (typeof FRAME_ERROR_CODES)[number];

export const FRAME_LIMITS = {
    /** Longest navigation path, in characters. A longer one is dropped. */
    maxNavPathLength: 1024,
    /** `nav.changed` messages EpicStaff accepts per frame in any 60-second window; the rest are dropped. */
    maxNavChangesPerMinute: 120,
    /** How long the SDK waits for `es:init` before it runs unframed. */
    initTimeoutMs: 3000,
    /** `availability.changed` messages EpicStaff accepts per frame in any 60-second window; the rest are dropped. */
    maxAvailabilityChangesPerMinute: 6,
} as const;

/**
 * A navigation path: an absolute path of non-empty segments of unreserved characters and `%` escapes, and an optional
 * query of the same plus `=`, `&` and `+`. No fragment. Dot segments and bad escapes are checked separately.
 */
export const NAV_PATH_PATTERN = /^\/([A-Za-z0-9\-._~%]+(\/[A-Za-z0-9\-._~%]+)*)?(\?[A-Za-z0-9\-._~%=&+]*)?$/;

export const THEME_MODES = ['dark', 'light'] as const;

export type ThemeMode = (typeof THEME_MODES)[number];

/**
 * Whether the plugin's own API can be reached, as the page last saw it: `maintenance` while the plugin, or the
 * organization, is being updated; `unavailable` while the plugin is not running or not answering.
 */
export const AVAILABILITY_STATES = ['available', 'maintenance', 'unavailable'] as const;

export type PluginAvailability = (typeof AVAILABILITY_STATES)[number];

/** The public theme tokens. EpicStaff only ever adds tokens; it never renames or removes one. */
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

/** The query parameter that carries the active organization id in the frame URL. The SDK removes it at start-up. */
export const ORG_HINT_PARAMETER = 'es_org';

/** CSS custom properties keyed by name (`--es-…`), values as CSS text. A token EpicStaff does not define is absent. */
export type ThemeTokens = Readonly<Record<string, string>>;

export interface ThemeState {
    mode: ThemeMode;
    tokens: ThemeTokens;
}

/** The organization the user opened the plugin page in. */
export interface OrgContext {
    id: number;
    name: string;
}

export interface ReadyMessage {
    type: typeof FRAME_MESSAGE_TYPES.ready;
    protocol: typeof FRAME_PROTOCOL_VERSION;
}

export interface InitMessage {
    type: typeof FRAME_MESSAGE_TYPES.init;
    protocol: typeof FRAME_PROTOCOL_VERSION;
    theme: ThemeState;
    nav: { path: string };
    org: OrgContext;
}

export interface ErrorMessage {
    type: typeof FRAME_MESSAGE_TYPES.error;
    protocol: typeof FRAME_PROTOCOL_VERSION;
    code: FrameErrorCode;
}

export interface NavChangedMessage {
    type: typeof FRAME_MESSAGE_TYPES.navChanged;
    path: string;
    /** `true`: replace EpicStaff's history entry; `false`: push one. */
    replace: boolean;
}

export interface NavNavigateMessage {
    type: typeof FRAME_MESSAGE_TYPES.navNavigate;
    path: string;
}

export interface ThemeChangedMessage {
    type: typeof FRAME_MESSAGE_TYPES.themeChanged;
    theme: ThemeState;
}

/** The page tells EpicStaff its API answers `maintenance` or `unavailable`; EpicStaff then asks its own server. */
export interface AvailabilityChangedMessage {
    type: typeof FRAME_MESSAGE_TYPES.availabilityChanged;
    state: PluginAvailability;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}
