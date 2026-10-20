/**
 * Frame protocol 1, EpicStaff's side: the values the host page and a framed plugin page agree on. The single source is
 * `plugin-sdk/contracts/frame-protocol.json`; `plugin-frame-protocol.contract.spec.ts` asserts these equal it.
 */

export const PLUGIN_FRAME_PROTOCOL_VERSION = 1;

export const PLUGIN_FRAME_MESSAGE_TYPES = {
    ready: 'es:ready',
    init: 'es:init',
    error: 'es:error',
    navChanged: 'nav.changed',
    navNavigate: 'nav.navigate',
    themeChanged: 'theme.changed',
} as const;

export const PLUGIN_FRAME_ERROR_CODES = {
    unsupportedProtocol: 'unsupported_protocol',
} as const;

export const PLUGIN_FRAME_LIMITS = {
    /** Longest navigation path a plugin page may report, in characters. */
    maxNavPathLength: 1024,
    /** `nav.changed` messages accepted per frame in any 60-second window; the rest are dropped. */
    maxNavChangesPerMinute: 120,
} as const;

/**
 * A plugin page's navigation path: an absolute path of non-empty segments of unreserved characters and `%` escapes,
 * and an optional query of the same plus `=`, `&` and `+`. No fragment. Dot segments and bad escapes are checked
 * separately, before and after decoding.
 */
export const PLUGIN_NAV_PATH_PATTERN = /^\/([A-Za-z0-9\-._~%]+(\/[A-Za-z0-9\-._~%]+)*)?(\?[A-Za-z0-9\-._~%=&+]*)?$/;

export const PLUGIN_THEME_MODES = ['dark', 'light'] as const;

/** The query parameter of the frame URL that carries the active organization id. Reserved: never a page's own. */
export const PLUGIN_ORG_HINT_PARAMETER = 'es_org';
