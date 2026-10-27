import { canonicalNavPath, locationToNavPath, type RoutingMode } from './nav-path.js';
import { FRAME_LIMITS } from './protocol.js';

/** One address change to tell EpicStaff about. */
export interface NavReport {
    path: string;
    /** `true`: replace EpicStaff's history entry; `false`: push one. */
    replace: boolean;
}

export type NavReporter = (report: NavReport) => void;

export interface NavSyncOptions {
    mode: RoutingMode;
    /**
     * Replaces the default handling of `nav.navigate` (replace the address, then fire a synthetic `popstate`, and
     * `hashchange` in hash mode). Give it when the page's router has its own navigate function.
     */
    onNavigate?: (path: string) => void;
    /** Clock for the report rate limiter. */
    now?: () => number;
}

export interface NavSync {
    /** The page's path when nav sync was installed; `null` when the address had no canonical form. */
    readonly initialPath: string | null;
    /** The page's path the address shows now. */
    currentPath(): string | null;
    /**
     * Starts reporting. `hostPath` is the path EpicStaff showed at the handshake. When the page started on that path,
     * the latest change made before the handshake is reported (if any); otherwise EpicStaff's address moved after it
     * opened the frame, so the page is moved there instead.
     */
    connect(reporter: NavReporter, hostPath: string): void;
    /** Moves the page to a path EpicStaff navigated to (`nav.navigate`). Never reported back. */
    navigate(path: string): void;
    /** Restores `history.pushState` / `replaceState` and stops listening. */
    uninstall(): void;
}

const RATE_WINDOW_MS = 60_000;
/** Stay a little under EpicStaff's cap so clock differences never trip it. */
const REPORT_HEADROOM = 10;

/**
 * Keeps EpicStaff's address in step with the page's route while the page runs in EpicStaff's frame. EpicStaff's
 * history is the only history: a push inside a cross-origin frame would still add an entry to the browser's session
 * history, so `history.pushState` becomes `replaceState` plus a `{replace: false}` report, and `replaceState` is
 * reported with `{replace: true}`. `popstate` and `hashchange` catch changes made without them.
 *
 * Paths are compared in their canonical spelling, and a change to the path EpicStaff already shows is never reported,
 * which stops echoes of `nav.navigate`. Reports made before {@link NavSync.connect} are queued; the latest wins.
 * Reports over EpicStaff's rate are held back and the latest is sent when the window allows.
 */
export function installNavSync(win: Window, options: NavSyncOptions): NavSync {
    const history = win.history;
    const originalPushState = history.pushState;
    const originalReplaceState = history.replaceState;
    const hadOwnPushState = Object.hasOwn(history, 'pushState');
    const hadOwnReplaceState = Object.hasOwn(history, 'replaceState');
    const now = options.now ?? (() => Date.now());
    const reportLimit = FRAME_LIMITS.maxNavChangesPerMinute - REPORT_HEADROOM;

    const readPath = (): string | null => locationToNavPath(win.location, options.mode);
    const initialPath = readPath();
    let lastPath = initialPath;
    let reporter: NavReporter | null = null;
    let queued: NavReport | null = null;
    let deferred: NavReport | null = null;
    let deferTimer: ReturnType<typeof setTimeout> | null = null;
    let warned = false;
    const sentAt: number[] = [];

    function pushState(data: unknown, unused: string, url?: string | URL | null): void {
        originalReplaceState.call(history, data, unused, url);
        locationChanged(false);
    }

    function replaceState(data: unknown, unused: string, url?: string | URL | null): void {
        originalReplaceState.call(history, data, unused, url);
        locationChanged(true);
    }

    const onBrowserNavigation = (): void => locationChanged(true);

    history.pushState = pushState;
    history.replaceState = replaceState;
    win.addEventListener('popstate', onBrowserNavigation);
    win.addEventListener('hashchange', onBrowserNavigation);

    function locationChanged(replace: boolean): void {
        const path = readPath();
        if (path === null) {
            warnUnrepresentable();
            return;
        }
        if (path === lastPath) return;
        lastPath = path;
        if (reporter === null) {
            queued = { path, replace: queued === null ? replace : queued.replace && replace };
            return;
        }
        report({ path, replace });
    }

    function report(next: NavReport): void {
        const time = now();
        while (sentAt.length > 0 && time - (sentAt[0] ?? 0) >= RATE_WINDOW_MS) sentAt.shift();
        if (sentAt.length >= reportLimit || deferTimer !== null) {
            deferred = {
                path: next.path,
                replace: deferred === null ? next.replace : deferred.replace && next.replace,
            };
            scheduleDeferred(time);
            return;
        }
        sentAt.push(time);
        reporter?.(next);
    }

    function scheduleDeferred(time: number): void {
        if (deferTimer !== null) return;
        const wait = Math.max(0, (sentAt[0] ?? time) + RATE_WINDOW_MS - time + 1);
        deferTimer = setTimeout(() => {
            deferTimer = null;
            const next = deferred;
            deferred = null;
            if (next !== null) report(next);
        }, wait);
    }

    function warnUnrepresentable(): void {
        if (warned) return;
        warned = true;
        console.warn(
            '[epicstaff] The page moved to an address EpicStaff cannot show (a "." or ".." segment, or over 1024 ' +
                "characters); EpicStaff's address bar keeps the previous path."
        );
    }

    function navigate(path: string): void {
        const target = canonicalNavPath(path);
        if (target === null) return;
        lastPath = target;
        if (options.onNavigate) {
            options.onNavigate(target);
            return;
        }
        if (readPath() === target) return;
        const oldUrl = win.location.href;
        originalReplaceState.call(history, null, '', options.mode === 'hash' ? '#' + target : target);
        const view = win as Window & typeof globalThis;
        win.dispatchEvent(
            typeof view.PopStateEvent === 'function'
                ? new view.PopStateEvent('popstate', { state: null })
                : new Event('popstate')
        );
        if (options.mode === 'hash') {
            win.dispatchEvent(
                typeof view.HashChangeEvent === 'function'
                    ? new view.HashChangeEvent('hashchange', { oldURL: oldUrl, newURL: win.location.href })
                    : new Event('hashchange')
            );
        }
    }

    return {
        initialPath,
        currentPath: readPath,
        connect(nextReporter: NavReporter, hostPath: string): void {
            reporter = nextReporter;
            const pending = queued;
            queued = null;
            const shown = canonicalNavPath(hostPath) ?? '/';
            if (shown !== initialPath) {
                navigate(shown);
                return;
            }
            lastPath = shown;
            const current = readPath();
            if (current !== null && current !== shown) {
                lastPath = current;
                report({ path: current, replace: pending?.replace ?? true });
            }
        },
        navigate,
        uninstall(): void {
            if (hadOwnPushState) history.pushState = originalPushState;
            else Reflect.deleteProperty(history, 'pushState');
            if (hadOwnReplaceState) history.replaceState = originalReplaceState;
            else Reflect.deleteProperty(history, 'replaceState');
            win.removeEventListener('popstate', onBrowserNavigation);
            win.removeEventListener('hashchange', onBrowserNavigation);
            if (deferTimer !== null) clearTimeout(deferTimer);
            deferTimer = null;
            reporter = null;
        },
    };
}
