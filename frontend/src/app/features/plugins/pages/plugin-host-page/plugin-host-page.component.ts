import { DOCUMENT } from '@angular/common';
import {
    Component,
    computed,
    DestroyRef,
    effect,
    ElementRef,
    inject,
    Renderer2,
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
import { FetchErrorStateComponent } from '@shared/components';
import { asyncScheduler, EMPTY, exhaustMap, filter, map, Subject, switchMap, throttleTime, timer } from 'rxjs';

import { ActiveOrgService } from '../../../../services/auth/active-org.service';
import { ProfileService } from '../../../../services/auth/profile.service';
import { PluginMaintenancePanelComponent } from '../../components/plugin-maintenance-panel/plugin-maintenance-panel.component';
import { AvailablePlugin } from '../../models/available-plugin.model';
import { PluginFrameOrg } from '../../models/plugin-frame-protocol.model';
import { AvailablePluginsStorageService } from '../../services/available-plugins-storage.service';
import { PluginFrameSyncService } from '../../services/plugin-frame-sync.service';
import { toPluginFrameUrl } from '../../utils/plugin-frame-url.util';
import { navPathFromRoute, parseNavPath } from '../../utils/plugin-nav-path.util';
import {
    PLUGIN_PAGE_IDENTIFIER_SEGMENT_INDEX,
    PLUGIN_PAGE_ROUTE_PREFIX_LENGTH,
    PLUGIN_PAGE_ROUTE_SEGMENT,
} from './plugin-page.matcher';

/** What the frame is opened for; the frame is rebuilt only when one of these changes. */
interface FrameTarget {
    identifier: string;
    plugin: AvailablePlugin | null;
    org: PluginFrameOrg | null;
}

interface ReadyView {
    kind: 'ready';
    /** Changes whenever a new frame is needed, so the template replaces the iframe instead of re-pointing it. */
    frameKey: string;
    identifier: string;
    name: string;
    frameOrigin: string;
    /** Validated; set on the iframe after the frame protocol listens. */
    frameUrl: string;
    /** The page's path when the frame opened. */
    initialPath: string;
    org: PluginFrameOrg;
}

/** The plugin is being updated: its page is not loaded until the server says it is ready again. */
interface MaintenanceView {
    kind: 'maintenance';
    name: string;
}

interface MessageView {
    kind: 'message';
    title: string;
    message: string;
}

type PluginHostView = ReadyView | MaintenanceView | MessageView;

/** The address of the plugin page, split the way the matcher consumed it. */
interface RouteTarget {
    identifier: string;
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

/**
 * Marks a router navigation made because the plugin page reported a new path (`nav.changed`), so the address change
 * it causes is not sent back to the page as `nav.navigate`.
 */
const FRAME_NAVIGATION_INFO = Object.freeze({ source: 'plugin-page' });

/** How often the page asks whether a plugin being updated is back. */
export const PLUGIN_MAINTENANCE_POLL_MS = 15_000;

/**
 * After a framed page says its API is down, the page asks EpicStaff's server again at most this often; a report inside
 * the window is answered once it ends.
 */
export const PLUGIN_AVAILABILITY_CHECK_MS = 10_000;

/**
 * `/plugins/<identifier>/**`: frames a plugin's own page, served from the plugin's own origin, and keeps EpicStaff's
 * address in step with it over frame protocol 1 ({@link PluginFrameSyncService}, one per page).
 *
 * Everything after `/plugins/<identifier>` is the page's path: the frame opens there (with the active organization as
 * `es_org`), a `nav.changed` from the page moves the address without reloading the frame, and an address change made
 * in EpicStaff (back/forward, a link) is sent to the page as `nav.navigate`. The frame gets no credentials, and its
 * sandbox has no `allow-top-navigation`, so a plugin cannot navigate EpicStaff away.
 *
 * While the plugin is being updated (`availability: 'maintenance'`), a panel says so instead of the frame; the page
 * asks the server every 15 seconds (not while the browser tab is hidden) and opens the frame once the plugin is
 * ready. A framed page that reports its API down (`availability.changed`) only makes the page ask the server again,
 * at most once per 10 seconds: the server's answer decides between the frame, the panel and "not available".
 */
@Component({
    selector: 'app-plugin-host-page',
    imports: [FetchErrorStateComponent, PluginMaintenancePanelComponent],
    templateUrl: './plugin-host-page.component.html',
    styleUrl: './plugin-host-page.component.scss',
    providers: [PluginFrameSyncService],
})
export class PluginHostPageComponent {
    private readonly frame = viewChild<ElementRef<HTMLIFrameElement>>('pluginFrame');

    /** The identifier as written in the address: the consumed segment, never the route params. */
    private readonly routeIdentifier = toSignal(inject(ActivatedRoute).url.pipe(map(identifierOf)), {
        requireSync: true,
    });
    private readonly frameTarget = computed<FrameTarget>(
        () => {
            const identifier = this.routeIdentifier();
            return {
                identifier,
                plugin: this.availablePlugins.plugins().find((plugin) => plugin.identifier === identifier) ?? null,
                org: this.activeOrg(),
            };
        },
        { equal: isSameFrameTarget }
    );
    protected readonly view = computed<PluginHostView>(() => {
        const target = this.frameTarget();
        return untracked(() => this.buildView(target));
    });
    protected readonly readyView = computed(() => {
        const view = this.view();
        return view.kind === 'ready' ? view : null;
    });
    /** The ready view as a list of at most one, so `@for … track frameKey` replaces the iframe for a new target. */
    protected readonly frameViews = computed(() => {
        const ready = this.readyView();
        return ready ? [ready] : [];
    });
    protected readonly maintenanceView = computed(() => {
        const view = this.view();
        return view.kind === 'maintenance' ? view : null;
    });
    protected readonly messageView = computed(() => {
        const view = this.view();
        return view.kind === 'message' ? view : null;
    });
    private readonly isInMaintenance = computed(() => this.view().kind === 'maintenance');

    // A new target closes the old frame's port at once; then attach, then give the iframe its address (the page can't
    // post `es:ready` before EpicStaff listens).
    private readonly frameEffect = effect(() => {
        const frame = this.frame()?.nativeElement;
        const ready = this.readyView();
        untracked(() => {
            if (ready?.frameKey !== this.attachedFrameKey) this.detachFrame();
            if (frame && ready) this.openFrame(frame, ready);
        });
    });

    private readonly frameSync = inject(PluginFrameSyncService);
    private readonly availablePlugins = inject(AvailablePluginsStorageService);
    private readonly activeOrgService = inject(ActiveOrgService);
    private readonly profileService = inject(ProfileService);
    private readonly renderer = inject(Renderer2);
    private readonly router = inject(Router);
    private readonly route = inject(ActivatedRoute);
    private readonly document = inject(DOCUMENT);
    private readonly destroyRef = inject(DestroyRef);
    /** A framed page reported its API down: ask the server again, within the rate of the checks. */
    private readonly availabilityChecks = new Subject<void>();
    /** Frames that already got their address; each iframe is opened once. */
    private readonly openedFrames = new WeakSet<HTMLIFrameElement>();
    /**
     * The `frameKey` of the frame the frame protocol is attached to. Until the frame of a new target is attached, the
     * view already describes the new plugin while the port still belongs to the old one: nothing may be sent then.
     */
    private attachedFrameKey: string | null = null;
    /**
     * What the page shows as far as EpicStaff knows: the path it opened at, its last `nav.changed` (with that
     * report's `replace`), or the last path sent to it as `nav.navigate`.
     */
    private pageNavigation: PageNavigation | null = null;
    /** The page navigation the address was last brought back to, so a failing one is retried once only. */
    private restoredNavigation: PageNavigation | null = null;
    private pagePathRequest: PagePathRequest | null = null;

    constructor() {
        toObservable(this.isInMaintenance)
            .pipe(
                switchMap((inMaintenance) =>
                    inMaintenance
                        ? timer(PLUGIN_MAINTENANCE_POLL_MS, PLUGIN_MAINTENANCE_POLL_MS).pipe(
                              filter(() => !this.document.hidden),
                              exhaustMap(() => this.availablePlugins.refresh())
                          )
                        : EMPTY
                ),
                takeUntilDestroyed()
            )
            .subscribe();
        this.availabilityChecks
            .pipe(
                throttleTime(PLUGIN_AVAILABILITY_CHECK_MS, asyncScheduler, { leading: true, trailing: true }),
                exhaustMap(() => this.availablePlugins.refresh()),
                takeUntilDestroyed()
            )
            .subscribe();
        this.router.events.pipe(takeUntilDestroyed()).subscribe((event) => {
            if (event instanceof NavigationEnd) {
                this.onAddressChanged();
            } else if (isFailedNavigation(event)) {
                // After the router has finished with the failed navigation.
                queueMicrotask(() => this.restoreAddress());
            }
        });
    }

    /** Loads the available plugins again; the page opens once its plugin is in the list. */
    protected reload(): void {
        this.availablePlugins.refresh().pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
    }

    /** The active organization with its name, from the signed-in user's memberships. */
    private activeOrg(): PluginFrameOrg | null {
        const orgId = this.activeOrgService.activeOrgId();
        const membership = this.profileService
            .currentUserSignal()
            ?.memberships.find((candidate) => candidate.organization.id === orgId);
        return membership ? { id: membership.organization.id, name: membership.organization.name } : null;
    }

    private buildView(target: FrameTarget): PluginHostView {
        if (!target.plugin) {
            return messageView('Plugin not available', 'This plugin is not available in your current organization.');
        }
        if (!target.org) {
            return messageView('Choose an organization', 'Plugins open inside an organization you belong to.');
        }
        if (target.plugin.availability === 'maintenance') return { kind: 'maintenance', name: target.plugin.name };
        // Read now, not when the target changed first: the address may have moved meanwhile.
        const initialPath = this.routeTarget().path;
        const frameUrl = toPluginFrameUrl({
            frameOrigin: target.plugin.frame_origin,
            identifier: target.identifier,
            navPath: initialPath,
            orgId: target.org.id,
            hostOrigin: this.document.location.origin,
        });
        if (frameUrl === null) {
            return messageView(
                "Couldn't open the plugin",
                'EpicStaff got an unexpected address for this plugin, so its page was not loaded.'
            );
        }
        return {
            kind: 'ready',
            frameKey: `${target.identifier}|${target.org.id}|${target.plugin.frame_origin}`,
            identifier: target.identifier,
            name: target.plugin.name,
            frameOrigin: target.plugin.frame_origin,
            frameUrl,
            initialPath,
            org: target.org,
        };
    }

    private openFrame(frame: HTMLIFrameElement, ready: ReadyView): void {
        // The query may still hold the iframe of the previous target until the template is refreshed.
        if (this.openedFrames.has(frame) || frame.dataset['frameKey'] !== ready.frameKey) return;
        this.openedFrames.add(frame);
        this.frameSync.attach(frame, {
            frameOrigin: ready.frameOrigin,
            initialPath: ready.initialPath,
            org: ready.org,
            onNavChanged: (path, replace) => this.onPageNavigated(ready, path, replace),
            onAvailabilityChanged: () => this.availabilityChecks.next(),
        });
        this.attachedFrameKey = ready.frameKey;
        this.pageNavigation = { path: ready.initialPath, replace: true };
        this.restoredNavigation = null;
        // Not a template binding: Angular binds an iframe URL only once told to trust it. The URL was validated
        // instead (`toPluginFrameUrl`), and is the only one set here.
        this.renderer.setAttribute(frame, 'src', ready.frameUrl);
    }

    /** Closes the attached frame's port and forgets what it showed. */
    private detachFrame(): void {
        this.frameSync.detach();
        this.attachedFrameKey = null;
        this.pageNavigation = null;
        this.restoredNavigation = null;
        this.pagePathRequest = null;
    }

    /** The ready view, only while its own frame is the one attached. */
    private attachedView(): ReadyView | null {
        const ready = this.readyView();
        return ready && ready.frameKey === this.attachedFrameKey ? ready : null;
    }

    /**
     * EpicStaff's address changed while this page stays (same route). For the open plugin, unless the page itself
     * caused it, tell the page; the frame protocol drops it when the page already shows that path. Another plugin's
     * address is never sent to this frame.
     */
    private onAddressChanged(): void {
        const ready = this.attachedView();
        if (!ready) return;
        const target = this.routeTarget();
        if (target.identifier !== ready.identifier) return;
        if (this.router.lastSuccessfulNavigation()?.extras.info === FRAME_NAVIGATION_INFO) return;
        this.pageNavigation = { path: target.path, replace: true };
        this.frameSync.notifyNavigation(target.path);
    }

    /** The page reported a new path (canonical, validated): move EpicStaff's address, not the frame. */
    private onPageNavigated(source: ReadyView, path: string, replace: boolean): void {
        if (source.frameKey !== this.attachedFrameKey) return;
        const identifier = source.identifier;
        this.pageNavigation = { path, replace };
        // A navigation the user started (a link, back/forward) wins: a page must not be able to cancel it, and so keep
        // the user on the page, by reporting paths while it is under way. If that navigation fails, `restoreAddress`
        // brings the address to the page's path afterwards.
        const pending = this.router.currentNavigation();
        if (pending && pending.extras.info !== FRAME_NAVIGATION_INFO) return;
        const address = this.routeTarget();
        // EpicStaff already moved on to another plugin.
        if (address.identifier !== identifier) return;
        // Compare with where the address is going, not only where it is: a quick `/a` then `/orig` must end on
        // `/orig`, not on `/a` because the address still showed `/orig` when `/orig` came.
        if ((this.pagePathRequest?.path ?? address.path) === path) return;
        this.navigateToPagePath(identifier, path, replace);
    }

    /**
     * A navigation failed (cancelled, rejected, skipped), so the address may no longer show what the page shows — for
     * example a `nav.changed` that came while the user's navigation was under way, which a guard then cancelled. The
     * page's own path wins: the address follows it (the page is not moved, so it never changes under the user).
     * Retried once per page path, so a failure of this navigation itself can't loop.
     */
    private restoreAddress(): void {
        // A navigation that started meanwhile settles the address itself.
        if (this.router.currentNavigation()) return;
        const ready = this.attachedView();
        const pageNavigation = this.pageNavigation;
        if (!ready || !pageNavigation || this.restoredNavigation === pageNavigation) return;
        const address = this.routeTarget();
        if (address.identifier !== ready.identifier || address.path === pageNavigation.path) return;
        this.restoredNavigation = pageNavigation;
        this.navigateToPagePath(ready.identifier, pageNavigation.path, pageNavigation.replace);
    }

    private navigateToPagePath(identifier: string, path: string, replace: boolean): void {
        const navTarget = parseNavPath(path);
        if (!navTarget) return;
        const request: PagePathRequest = { path };
        this.pagePathRequest = request;
        const settle = (): void => {
            if (this.pagePathRequest === request) this.pagePathRequest = null;
        };
        this.router
            .navigate([`/${PLUGIN_PAGE_ROUTE_SEGMENT}`, identifier, ...navTarget.segments], {
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
            identifier: identifierOf(snapshot.url),
            path: navPathFromRoute(pageSegments, snapshot.queryParams),
        };
    }
}

function messageView(title: string, message: string): MessageView {
    return { kind: 'message', title, message };
}

/** The identifier segment the matcher consumed; `""` when there is none. */
function identifierOf(segments: readonly UrlSegment[]): string {
    return segments[PLUGIN_PAGE_IDENTIFIER_SEGMENT_INDEX]?.path ?? '';
}

function isSameFrameTarget(first: FrameTarget, second: FrameTarget): boolean {
    return (
        first.identifier === second.identifier &&
        first.org?.id === second.org?.id &&
        first.org?.name === second.org?.name &&
        first.plugin?.frame_origin === second.plugin?.frame_origin &&
        first.plugin?.name === second.plugin?.name &&
        first.plugin?.availability === second.plugin?.availability
    );
}

/**
 * A navigation that ended without moving the address: rejected, failed or skipped. A redirect or a newer navigation
 * is not an end — the navigation that follows it settles the address.
 */
function isFailedNavigation(event: RouterEvent): boolean {
    if (event instanceof NavigationError || event instanceof NavigationSkipped) return true;
    return (
        event instanceof NavigationCancel &&
        event.code !== NavigationCancellationCode.Redirect &&
        event.code !== NavigationCancellationCode.SupersededByNewNavigation
    );
}
