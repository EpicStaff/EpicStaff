import { canonicalNavPath, hashToNavPath } from './nav-path.js';
import { BRIDGE_LIMITS } from './protocol.js';

/** One URL change to tell EpicStaff about. */
export interface NavReport {
    path: string;
    /** `true`: replace EpicStaff's history entry; `false`: push one. */
    replace: boolean;
}

export type NavReporter = (report: NavReport) => void;

export interface NavSyncOptions {
    /**
     * Turn the app's `history.pushState` into `replaceState`. Inside EpicStaff this must be on: a
     * push inside the frame would add a second entry to the browser's history, so EpicStaff owns
     * history and the app only reports. Off when the app runs standalone with the mock host.
     */
    convertPush: boolean;
    /** Replaces the default handling of `nav.navigate` (set the hash, then synthetic `popstate` + `hashchange`). */
    onNavigate?: (path: string) => void;
    /** Clock for the report rate limiter. */
    now?: () => number;
}

export interface NavSync {
    /** The app path when nav sync was installed; `null` when the hash had no canonical form. */
    readonly initialPath: string | null;
    /** The app path the frame's URL shows now. */
    currentPath(): string | null;
    /**
     * Starts reporting. `hostPath` is the path EpicStaff showed at the handshake. When the frame
     * started on that path, the latest change made before the handshake is reported (if any);
     * otherwise the frame was not opened on EpicStaff's path, so the app is moved there instead.
     */
    connect(reporter: NavReporter, hostPath: string): void;
    /** Moves the app to a path EpicStaff navigated to (`nav.navigate`). Never reported back. */
    navigate(path: string): void;
    /** Restores `history.pushState` / `replaceState` and stops listening. */
    uninstall(): void;
}

const RATE_WINDOW_MS = 60_000;
/** Stay a little under EpicStaff's cap so clock differences never trip it. */
const REPORT_HEADROOM = 10;

/**
 * Keeps EpicStaff's address bar in sync with the app's hash route.
 *
 * Patches `history.pushState` (→ `replaceState` inside EpicStaff + `{replace: false}` report) and
 * `history.replaceState` (→ `{replace: true}` report), and watches `popstate` / `hashchange` for
 * changes made without them (reported with `replace: true`: the browser already added its own
 * history entry). Paths are compared in their canonical spelling (the one EpicStaff uses), and a
 * change to the path EpicStaff already shows is never reported, which stops echoes of `nav.navigate`. Reports made before {@link NavSync.connect} are queued; the
 * latest wins. Reports over EpicStaff's rate are held back and the latest is sent when allowed.
 */
export function installNavSync(win: Window, options: NavSyncOptions): NavSync {
    const history = win.history;
    const originalPushState = history.pushState;
    const originalReplaceState = history.replaceState;
    const hadOwnPushState = Object.hasOwn(history, 'pushState');
    const hadOwnReplaceState = Object.hasOwn(history, 'replaceState');
    const now = options.now ?? (() => Date.now());
    const reportLimit = BRIDGE_LIMITS.maxNavChangesPerMinute - REPORT_HEADROOM;

    const readPath = (): string | null => hashToNavPath(win.location.hash);
    const initialPath = readPath();
    let lastPath = initialPath;
    let reporter: NavReporter | null = null;
    let queued: NavReport | null = null;
    let deferred: NavReport | null = null;
    let deferTimer: ReturnType<typeof setTimeout> | null = null;
    let warned = false;
    const sentAt: number[] = [];

    function pushState(data: unknown, unused: string, url?: string | URL | null): void {
        (options.convertPush ? originalReplaceState : originalPushState).call(history, data, unused, url);
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
            '[epicstaff] The app moved to a URL EpicStaff cannot show (a "." or ".." segment, or over 1024 characters); ' +
                "EpicStaff's address bar keeps the previous path."
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
        const oldURL = win.location.href;
        originalReplaceState.call(history, null, '', '#' + target);
        const view = win as Window & typeof globalThis;
        const popState =
            typeof view.PopStateEvent === 'function'
                ? new view.PopStateEvent('popstate', { state: null })
                : new Event('popstate');
        win.dispatchEvent(popState);
        const hashChange =
            typeof view.HashChangeEvent === 'function'
                ? new view.HashChangeEvent('hashchange', { oldURL, newURL: win.location.href })
                : new Event('hashchange');
        win.dispatchEvent(hashChange);
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
                // EpicStaff's address changed after it opened the frame (or the frame URL had no path).
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
