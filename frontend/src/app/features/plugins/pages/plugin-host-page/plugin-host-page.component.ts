import { DOCUMENT } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
    Component,
    computed,
    effect,
    ElementRef,
    inject,
    Renderer2,
    signal,
    untracked,
    viewChild,
} from '@angular/core';
import { takeUntilDestroyed, toObservable, toSignal } from '@angular/core/rxjs-interop';
import {
    ActivatedRoute,
    Event as RouterEvent,
    NavigationCancel,
    NavigationCancellationCode,
    NavigationEnd,
    NavigationError,
    NavigationSkipped,
    Router,
    UrlSegment,
} from '@angular/router';
import { ButtonComponent, FetchErrorStateComponent, LoadingSpinnerComponent } from '@shared/components';
import { catchError, map, Observable, of, switchMap, tap } from 'rxjs';

import { supportsHostEvents } from '../../bridge/bridge-protocol';
import { PluginBridgeHost, PluginBridgeStopReason } from '../../bridge/plugin-bridge-host.service';
import { navPathFromRoute, parseNavPath } from '../../bridge/plugin-nav-path.util';
import { PluginUiSession } from '../../models/plugin.model';
import { PluginsApiService } from '../../services/plugins-api.service';
import { PluginsStoreService } from '../../services/plugins-store.service';
import { toPluginErrorView } from '../../utils/plugin-error.util';
import { toPluginDevFrameUrl, toPluginFrameUrl, withPluginNavFragment } from '../../utils/plugin-frame-url.util';
import {
    PLUGIN_PAGE_ID_SEGMENT_INDEX,
    PLUGIN_PAGE_ROUTE_PREFIX_LENGTH,
    PLUGIN_PAGE_ROUTE_SEGMENT,
} from './plugin-page.matcher';

interface ReadyView {
    kind: 'ready';
    session: PluginUiSession;
    /** The route id the page was opened for, as written in the address. */
    routeId: string;
    /** Validated; for bridge v2 with the page's path as the fragment. Set on the iframe after `attach`. */
    frameUrl: string;
    /** The page's path when it opened (bridge v2). */
    initialPath: string;
    /** Dev mode: the author's dev server, shown in the banner; `null` in production. */
    devUrl: string | null;
}

/** Every state without a page: suspended / not ready / not found, errors, and a stopped page. */
interface MessageView {
    kind: 'message';
    title: string;
    message: string;
    retryLabel: string;
}

type PluginHostView = { kind: 'loading' } | ReadyView | MessageView;

/** The address of the plugin page, split the way the matcher consumed it. */
interface RouteTarget {
    id: string;
    path: string;
}

/** A path the page is known to show, and whether reaching it should replace the history entry. */
interface PageNavigation {
    path: string;
    replace: boolean;
}

/** A router navigation this host page started to follow the page, until it settles. */
interface PagePathRequest {
    path: string;
}

const STOPPED_MESSAGES: Record<PluginBridgeStopReason, string> = {
    navigated: 'The page tried to open another address, so EpicStaff closed it. Anything it was doing has stopped.',
    org_changed: 'You switched organization, so this plugin page was closed.',
};

/** 409 codes of `ui-session` that mean "the page can't be opened right now". */
const UNAVAILABLE_TITLES: ReadonlyMap<string, string> = new Map([
    ['plugin_suspended', 'This plugin is suspended'],
    ['plugin_not_ready', 'This plugin is not ready yet'],
    ['plugin_has_no_ui', 'This plugin has no page'],
]);

/**
 * Marks a router navigation made because the plugin page reported a new path (`nav.changed`), so
 * the address change it causes is not sent back to the page as `nav.navigate`.
 */
const FRAME_NAVIGATION_INFO = Object.freeze({ source: 'plugin-page' });

/**
 * `/plugins/:id/**`: opens a plugin's own page in a sandboxed iframe and serves it the bridge.
 *
 * The iframe gets no token and no same-origin access: `sandbox="allow-scripts"` only, its URL
 * must be a `/api/plugin-ui/` path (or, in dev mode, the author's `http://localhost` dev server),
 * and it reaches EpicStaff solely through the {@link PluginBridgeHost} provided here (one per page,
 * destroyed with it).
 *
 * Bridge v2 pages keep EpicStaff's address in step with their own path: everything after
 * `/plugins/<id>` is the page's path. It opens there (URL fragment and `init`); a `nav.changed`
 * from the page moves the address without reloading the iframe; an address change made in
 * EpicStaff (back/forward, a sidenav click) is sent to the page as `nav.navigate`.
 */
@Component({
    selector: 'app-plugin-host-page',
    imports: [ButtonComponent, FetchErrorStateComponent, LoadingSpinnerComponent],
    templateUrl: './plugin-host-page.component.html',
    styleUrl: './plugin-host-page.component.scss',
    providers: [PluginBridgeHost],
})
export class PluginHostPageComponent {
    private readonly frame = viewChild<ElementRef<HTMLIFrameElement>>('pluginFrame');

    /**
     * The plugin id as written in the address: the consumed segment, never the route params (which
     * the router may merge matrix params into).
     */
    private readonly routeId = toSignal(inject(ActivatedRoute).url.pipe(map(pluginIdOf)), { requireSync: true });
    private readonly attempt = signal(0);
    protected readonly view = signal<PluginHostView>({ kind: 'loading' });
    protected readonly readyView = computed(() => {
        const view = this.view();
        return view.kind === 'ready' ? view : null;
    });
    protected readonly messageView = computed(() => {
        const view = this.view();
        return view.kind === 'message' ? view : null;
    });

    // Attach, then give the iframe its address: the page can't post `ready` before the bridge listens.
    private readonly attachEffect = effect(() => {
        const frame = this.frame();
        const ready = this.readyView();
        if (frame && ready) untracked(() => this.openFrame(frame.nativeElement, ready));
    });

    private readonly stoppedEffect = effect(() => {
        const reason = this.bridgeHost.stopped();
        if (reason) {
            untracked(() =>
                this.view.set({
                    kind: 'message',
                    title: 'Plugin page stopped',
                    message: STOPPED_MESSAGES[reason],
                    retryLabel: 'Reload page',
                })
            );
        }
    });

    private readonly bridgeHost = inject(PluginBridgeHost);
    private readonly pluginsApiService = inject(PluginsApiService);
    private readonly pluginsStore = inject(PluginsStoreService);
    private readonly renderer = inject(Renderer2);
    private readonly router = inject(Router);
    private readonly route = inject(ActivatedRoute);
    private readonly document = inject(DOCUMENT);
    /**
     * What the page shows as far as EpicStaff knows: the path it opened at, its last `nav.changed`
     * (with that report's `replace`), or the last path sent to it as `nav.navigate`.
     */
    private pageNavigation: PageNavigation | null = null;
    /** The page navigation the address was last brought back to, so a failing one is retried once only. */
    private restoredNavigation: PageNavigation | null = null;
    private pagePathRequest: PagePathRequest | null = null;

    constructor() {
        const request = computed(() => ({ id: this.routeId(), attempt: this.attempt() }));
        toObservable(request)
            .pipe(
                tap(() => {
                    this.bridgeHost.detach();
                    this.view.set({ kind: 'loading' });
                }),
                switchMap(({ id }) => this.openPage(id)),
                takeUntilDestroyed()
            )
            .subscribe((view) => this.view.set(view));

        this.router.events.pipe(takeUntilDestroyed()).subscribe((event) => {
            if (event instanceof NavigationEnd) {
                this.onAddressChanged();
            } else if (isFailedNavigation(event)) {
                // After the router has finished with the failed navigation.
                queueMicrotask(() => this.restoreAddress());
            }
        });
    }

    protected reload(): void {
        this.attempt.update((attempt) => attempt + 1);
    }

    protected onFrameLoad(): void {
        this.bridgeHost.onFrameLoad();
    }

    private openFrame(frame: HTMLIFrameElement, ready: ReadyView): void {
        this.bridgeHost.attach(frame, ready.session, {
            initialPath: ready.initialPath,
            devMode: ready.devUrl !== null,
            onNavChanged: (path, replace) => this.onPageNavigated(ready.routeId, path, replace),
        });
        this.pageNavigation = { path: ready.initialPath, replace: true };
        // Not a template binding: Angular binds an iframe URL only once told to trust it. The URL was
        // validated instead (`toPluginFrameUrl` / `toPluginDevFrameUrl`), and is the only one set here.
        this.renderer.setAttribute(frame, 'src', ready.frameUrl);
    }

    private openPage(rawId: string): Observable<PluginHostView> {
        const id = Number(rawId);
        if (!Number.isSafeInteger(id) || id <= 0) {
            return of(messageView('Plugin not found', 'There is no plugin at this address.', 'Try again'));
        }
        return this.pluginsApiService.createUiSession(id).pipe(
            map((session) => this.toReadyView(session, rawId)),
            catchError((error: unknown) => of(this.toFailureView(error)))
        );
    }

    private toReadyView(session: PluginUiSession, routeId: string): PluginHostView {
        const devMode = session.dev_mode === true;
        const url = devMode
            ? toPluginDevFrameUrl(session.url)
            : toPluginFrameUrl(session.url, this.document.location.origin);
        if (url === null) {
            return messageView(
                "Couldn't open the plugin",
                'EpicStaff answered with an unexpected page address, so the page was not loaded.',
                'Retry'
            );
        }
        // Read now, not when the request started: the address may have moved while it was loading.
        const initialPath = this.routeTarget().path;
        const frameUrl = supportsHostEvents(session.bridge_version) ? withPluginNavFragment(url, initialPath) : url;
        return { kind: 'ready', session, routeId, frameUrl, initialPath, devUrl: devMode ? url : null };
    }

    private toFailureView(error: unknown): PluginHostView {
        if (!(error instanceof HttpErrorResponse)) {
            return messageView("Couldn't open the plugin", 'Something went wrong. Try again.', 'Retry');
        }
        const errorView = toPluginErrorView(error, 'Check your connection and try again.');
        if (error.status === 404 || error.status === 409) {
            // The navigation button may be stale (suspended, deleted, or no longer ready).
            this.pluginsStore.refreshNav();
        }
        if (error.status === 404) {
            return messageView(
                'Plugin not found',
                'It may have been deleted, or it belongs to another organization.',
                'Try again'
            );
        }
        const unavailableTitle = error.status === 409 ? UNAVAILABLE_TITLES.get(errorView.code ?? '') : undefined;
        if (unavailableTitle) {
            return messageView(unavailableTitle, errorView.message, 'Try again');
        }
        if (error.status === 403) {
            return messageView("You can't open this plugin", errorView.message, 'Try again');
        }
        return messageView("Couldn't open the plugin", errorView.message, 'Retry');
    }

    /**
     * EpicStaff's address changed while this page stays (same route). For the open plugin, unless the
     * page itself caused it, tell the page; the bridge drops it when the page already shows that path.
     * Another plugin's id reopens the page instead.
     */
    private onAddressChanged(): void {
        const ready = this.readyView();
        if (!ready) return;
        const target = this.routeTarget();
        if (target.id !== ready.routeId) return;
        if (this.router.lastSuccessfulNavigation()?.extras.info === FRAME_NAVIGATION_INFO) return;
        this.pageNavigation = { path: target.path, replace: true };
        this.bridgeHost.notifyNavigation(target.path);
    }

    /** The page reported a new path (canonical, validated): move EpicStaff's address, not the iframe. */
    private onPageNavigated(routeId: string, path: string, replace: boolean): void {
        this.pageNavigation = { path, replace };
        // A navigation the user started (sidenav, back/forward) wins: a page must not be able to
        // cancel it, and so keep the user on the page, by reporting paths while it is under way. If
        // that navigation fails, `restoreAddress` brings the address to the page's path afterwards.
        const pending = this.router.currentNavigation();
        if (pending && pending.extras.info !== FRAME_NAVIGATION_INFO) return;
        const address = this.routeTarget();
        // EpicStaff already moved on to another plugin.
        if (address.id !== routeId) return;
        // Compare with where the address is going, not only where it is: a quick `/a` then `/orig`
        // must end on `/orig`, not on `/a` because the address still showed `/orig` when `/orig` came.
        if ((this.pagePathRequest?.path ?? address.path) === path) return;
        this.navigateToPagePath(routeId, path, replace);
    }

    /**
     * A navigation failed (cancelled, rejected, skipped), so the address may no longer show what the
     * page shows — for example a `nav.changed` that came while the user's navigation was under way,
     * which then a guard cancelled. The page's own path wins: the address follows it (the page is
     * not moved, so it never changes under the user). Retried once per page path, so a failure of
     * this navigation itself can't loop.
     */
    private restoreAddress(): void {
        // A navigation that started meanwhile settles the address itself.
        if (this.router.currentNavigation()) return;
        const ready = this.readyView();
        const pageNavigation = this.pageNavigation;
        if (!ready || !pageNavigation || this.restoredNavigation === pageNavigation) return;
        const address = this.routeTarget();
        if (address.id !== ready.routeId || address.path === pageNavigation.path) return;
        this.restoredNavigation = pageNavigation;
        this.navigateToPagePath(ready.routeId, pageNavigation.path, pageNavigation.replace);
    }

    private navigateToPagePath(routeId: string, path: string, replace: boolean): void {
        const navTarget = parseNavPath(path);
        if (!navTarget) return;
        const request: PagePathRequest = { path };
        this.pagePathRequest = request;
        const settle = (): void => {
            if (this.pagePathRequest === request) this.pagePathRequest = null;
        };
        this.router
            .navigate([`/${PLUGIN_PAGE_ROUTE_SEGMENT}`, routeId, ...navTarget.segments], {
                queryParams: navTarget.queryParams,
                replaceUrl: replace,
                info: FRAME_NAVIGATION_INFO,
            })
            .then(settle, settle);
    }

    private routeTarget(): RouteTarget {
        const snapshot = this.route.snapshot;
        const pageSegments = snapshot.url.slice(PLUGIN_PAGE_ROUTE_PREFIX_LENGTH).map((segment) => segment.path);
        return {
            id: pluginIdOf(snapshot.url),
            path: navPathFromRoute(pageSegments, snapshot.queryParams),
        };
    }
}

function messageView(title: string, message: string, retryLabel: string): MessageView {
    return { kind: 'message', title, message, retryLabel };
}

/** The plugin id segment the matcher consumed; `""` when there is none. */
function pluginIdOf(segments: readonly UrlSegment[]): string {
    return segments[PLUGIN_PAGE_ID_SEGMENT_INDEX]?.path ?? '';
}

/**
 * A navigation that ended without moving the address: rejected, failed or skipped. A redirect or a
 * newer navigation is not an end — the navigation that follows it settles the address.
 */
function isFailedNavigation(event: RouterEvent): boolean {
    if (event instanceof NavigationError || event instanceof NavigationSkipped) return true;
    return (
        event instanceof NavigationCancel &&
        event.code !== NavigationCancellationCode.Redirect &&
        event.code !== NavigationCancellationCode.SupersededByNewNavigation
    );
}
