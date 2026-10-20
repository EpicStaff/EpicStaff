import { loadPlatformConfig, type PlatformConfig } from './config.js';
import {
    FrameChannel,
    type HandshakeOutcome,
    isFramed,
    performHandshake,
    takeOrgHint,
    type UnframedReason,
} from './frame.js';
import type { RoutingMode } from './nav-path.js';
import { installNavSync, type NavSync } from './nav-sync.js';
import type { OrgContext, ThemeState } from './protocol.js';
import { applyTheme } from './theme.js';

export {
    loadPlatformConfig,
    parsePlatformConfig,
    PLATFORM_CONFIG_PATH,
    type PlatformConfig,
    PlatformConfigError,
} from './config.js';
export {
    type FrameInit,
    type HandshakeOutcome,
    isFramed,
    performHandshake,
    takeOrgHint,
    type UnframedReason,
} from './frame.js';
export {
    addressToNavPath,
    canonicalNavPath,
    hashToNavPath,
    isValidNavPath,
    locationToNavPath,
    type RoutingMode,
} from './nav-path.js';
export { installNavSync, type NavReport, type NavSync } from './nav-sync.js';
export {
    FRAME_ERROR_CODES,
    FRAME_LIMITS,
    FRAME_MESSAGE_TYPES,
    FRAME_PROTOCOL_VERSION,
    type FrameErrorCode,
    NAV_PATH_PATTERN,
    ORG_HINT_PARAMETER,
    type OrgContext,
    THEME_MODES,
    THEME_TOKENS,
    type ThemeMode,
    type ThemeState,
    type ThemeToken,
} from './protocol.js';
export { applyTheme, normalizeThemeMode } from './theme.js';

export interface StartPluginOptions {
    /** Defaults to the global `window`. */
    window?: Window;
    /** How the page keeps its route. Default `pathname`. */
    routing?: RoutingMode;
    /** Apply EpicStaff's theme tokens to `<html>`. Default `true`. */
    applyTheme?: boolean;
    /**
     * Moves the page when EpicStaff navigates (back/forward, a link in EpicStaff). Without it the SDK replaces the
     * address and fires a synthetic `popstate` (and `hashchange` in hash mode), which most routers follow.
     */
    onNavigate?: (path: string) => void;
    /** Defaults to the global `fetch`. */
    fetch?: typeof fetch;
    /** How long to wait for EpicStaff's answer before running unframed. Default 3 seconds. */
    initTimeoutMs?: number;
}

export interface EpicStaffPlugin {
    readonly config: PlatformConfig;
    /** True when the page runs in EpicStaff's frame and the handshake succeeded. */
    readonly framed: boolean;
    /** Why the page runs unframed; `null` when framed. */
    readonly unframedReason: UnframedReason | null;
    /** The organization the user opened the page in (from the handshake); `null` unframed. */
    readonly org: OrgContext | null;
    /** The organization id EpicStaff put into the frame URL, kept even when the handshake fails. */
    readonly orgHint: number | null;
    /** EpicStaff's current theme; `null` unframed. */
    theme(): ThemeState | null;
    /** Calls `listener` on every theme change. Returns the function that stops it. */
    onThemeChange(listener: (theme: ThemeState) => void): () => void;
    /** Closes the port and restores `history`. */
    close(): void;
}

/**
 * Starts a plugin page: removes the `es_org` hint from the address, loads the platform config, and — inside EpicStaff's
 * frame — runs the handshake, applies the theme and keeps EpicStaff's address in step with the page's route.
 *
 * Call it before the page's router starts, so the router never sees `es_org` and its first navigation is captured.
 * Never sends credentials anywhere: the config is a public document on the plugin's own origin.
 */
export async function startPlugin(options: StartPluginOptions = {}): Promise<EpicStaffPlugin> {
    const win = options.window ?? window;
    const orgHint = takeOrgHint(win);
    // Installed before anything waits, so a route change made while the config loads is not lost.
    const navSync = isFramed(win)
        ? installNavSync(win, {
              mode: options.routing ?? 'pathname',
              ...(options.onNavigate ? { onNavigate: options.onNavigate } : {}),
          })
        : null;

    let config: PlatformConfig;
    try {
        config = await loadPlatformConfig(options.fetch ? { fetch: options.fetch } : {});
    } catch (error) {
        navSync?.uninstall();
        throw error;
    }

    const outcome = await performHandshake(win, {
        epicstaffOrigin: config.epicstaff_origin,
        ...(options.initTimeoutMs === undefined ? {} : { timeoutMs: options.initTimeoutMs }),
    });
    if (!outcome.framed) {
        navSync?.uninstall();
        return unframedPlugin(config, orgHint, outcome.reason);
    }
    return framedPlugin(win, config, orgHint, outcome, navSync, options.applyTheme ?? true);
}

function unframedPlugin(config: PlatformConfig, orgHint: number | null, reason: UnframedReason): EpicStaffPlugin {
    return {
        config,
        framed: false,
        unframedReason: reason,
        org: null,
        orgHint,
        theme: () => null,
        onThemeChange: () => () => undefined,
        close: () => undefined,
    };
}

function framedPlugin(
    win: Window,
    config: PlatformConfig,
    orgHint: number | null,
    outcome: Extract<HandshakeOutcome, { framed: true }>,
    navSync: NavSync | null,
    shouldApplyTheme: boolean
): EpicStaffPlugin {
    let theme = outcome.init.theme;
    const listeners = new Set<(theme: ThemeState) => void>();
    if (shouldApplyTheme) applyTheme(win.document, theme);

    const channel = new FrameChannel(outcome.port, {
        onNavigate: (path) => navSync?.navigate(path),
        onThemeChanged: (next) => {
            theme = next;
            if (shouldApplyTheme) applyTheme(win.document, next);
            for (const listener of [...listeners]) listener(next);
        },
    });
    navSync?.connect((report) => channel.reportNavigation(report.path, report.replace), outcome.init.navPath);

    return {
        config,
        framed: true,
        unframedReason: null,
        org: outcome.init.org,
        orgHint,
        theme: () => theme,
        onThemeChange(listener) {
            listeners.add(listener);
            return () => listeners.delete(listener);
        },
        close() {
            channel.close();
            navSync?.uninstall();
            listeners.clear();
        },
    };
}
