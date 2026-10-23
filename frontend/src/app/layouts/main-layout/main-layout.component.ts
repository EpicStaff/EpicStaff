import { CdkTrapFocus } from '@angular/cdk/a11y';
import {
    afterNextRender,
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    effect,
    inject,
    Injector,
    OnInit,
    signal,
    untracked,
    viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRouteSnapshot, NavigationEnd, Router, RouterOutlet } from '@angular/router';
import { ResizableSidebarDirective } from '@shared/directives';
import { SidebarWidthService } from '@shared/services';
import { isPlainPrimaryClick, urlPath } from '@shared/utils';
import { filter } from 'rxjs/operators';

import { AppNavigationDrawerService, HIDE_SIDENAV_ON_PHONE } from '../../core/services/app-navigation-drawer.service';
import { PhoneLayoutService } from '../../core/services/phone-layout.service';
import { AppReturnUrlService } from '../../features/plugins/services/app-return-url.service';
import { QuickStartTourService } from '../../features/quick-start-tour/quick-start-tour.service';
import { ProfileService } from '../../services/auth/profile.service';
import { LastVisitedTabService } from '../../services/last-visited-tab.service';
import { MAIN_SIDENAV_WIDTH_KEY, MAIN_SIDENAV_WIDTH_OPTIONS } from './main-sidenav-width';
import { LeftSidebarComponent } from './sidenav/sidenav.component';

const TABBED_ROUTES: Record<string, string[]> = {
    '/tools': ['/tools/custom', '/tools/mcp'],
    '/flows': ['/flows/my', '/flows/templates'],
    '/storage': ['/storage/knowledge-sources', '/storage/files', '/storage/key-value-tables'],
};

@Component({
    selector: 'app-main-layout',
    imports: [CdkTrapFocus, LeftSidebarComponent, RouterOutlet, ResizableSidebarDirective],
    styles: [
        `
            @use '../../../styles/touch';

            :host {
                display: flex;
                flex: 1;
                width: 100%;
                min-height: 0;
                max-height: 100vh;
                // iOS Safari: 100vh is the height with its toolbars hidden, so the page's bottom (a composer) would
                // sit behind them while they show.
                max-height: 100dvh;
            }

            /* Width follows the pointer while dragging, so it is never animated. */
            .sidebar-wrapper {
                position: relative;
                flex-shrink: 0;
            }

            // Out of the layout, past the left edge, until opened over the page. Hidden, not removed: the sidenav
            // runs the chat inbox stream.
            .sidebar-wrapper--drawer {
                position: fixed;
                top: 0;
                bottom: 0;
                left: 0;
                // Above the page and its own drawers, below the CDK overlay container (1100), so a dialog or menu
                // opened from the sidenav shows above it.
                z-index: 1001;
                box-sizing: content-box;
                padding-left: env(safe-area-inset-left, 0px);
                background-color: var(--color-sidenav-background);
                transform: translateX(-100%);
                visibility: hidden;
            }

            .sidebar-wrapper--open {
                transform: none;
                visibility: visible;
                box-shadow: var(--shadow-panel-elevated);
            }

            .sidebar-backdrop {
                position: fixed;
                inset: 0;
                z-index: 1000;
                background-color: var(--color-backdrop);
            }

            @media (prefers-reduced-motion: no-preference) {
                // Hidden only once it has slid out.
                .sidebar-wrapper--drawer {
                    transition:
                        transform touch.$push-duration touch.$push-easing,
                        visibility 0s linear touch.$push-duration;
                }

                .sidebar-wrapper--open {
                    transition:
                        transform touch.$push-duration touch.$push-easing,
                        visibility 0s;
                }

                .sidebar-backdrop--entering {
                    animation: sidebar-backdrop-fade touch.$push-duration touch.$push-easing;
                }

                .sidebar-backdrop--leaving {
                    animation: sidebar-backdrop-fade touch.$push-duration touch.$push-easing reverse forwards;
                }
            }

            @keyframes sidebar-backdrop-fade {
                from {
                    opacity: 0;
                }
            }

            /* The main-content area flexes to fill all remaining horizontal space. */
            .main-content {
                flex: 1;
                min-width: 0;
                overflow-y: auto;
                overflow-x: hidden;
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.Eager,
    template: `
        <!-- A dialog only while it is open over the page; Escape closes it from anywhere inside. -->
        <div
            #sidebarWrapper
            class="sidebar-wrapper"
            [class.sidebar-wrapper--drawer]="isSidenavDrawer()"
            [class.sidebar-wrapper--open]="isSidenavDrawerOpen()"
            [style.width.px]="sidenavWidth()"
            [attr.inert]="isSidenavDrawer() && !isSidenavDrawerOpen() ? '' : null"
            [attr.role]="isSidenavDrawerOpen() ? 'dialog' : null"
            [attr.aria-modal]="isSidenavDrawerOpen() ? 'true' : null"
            [attr.aria-label]="isSidenavDrawerOpen() ? 'App navigation' : null"
            [cdkTrapFocus]="isSidenavDrawerOpen()"
            (keydown.escape)="navigationDrawer.close()"
            (click)="onSidenavClick($event)"
        >
            <app-left-sidebar
                [width]="sidenavWidth()"
                [inDrawer]="isSidenavDrawer()"
                (expandedToggle)="toggleSidenav()"
            ></app-left-sidebar>
            <div
                class="resizable-sidebar-handle"
                [appResizableSidebar]="sidenavWidthKey"
                [sidebarTarget]="sidebarWrapper"
                [sidebarMinWidth]="sidenavWidthOptions.minWidth"
                [sidebarMaxWidth]="sidenavWidthOptions.maxWidth"
                [sidebarCollapse]="sidenavWidthOptions.collapse"
                sidebarAriaLabel="Resize navigation sidebar"
            ></div>
        </div>

        @if (isSidenavDrawerOpen()) {
            <div
                class="sidebar-backdrop"
                animate.enter="sidebar-backdrop--entering"
                animate.leave="sidebar-backdrop--leaving"
                (click)="navigationDrawer.close()"
            ></div>
        }

        <div
            class="main-content"
            [attr.inert]="isSidenavDrawerOpen() ? '' : null"
        >
            <router-outlet></router-outlet>
        </div>
    `,
})
export class MainLayoutComponent implements OnInit {
    private readonly sidenavTrap = viewChild.required(CdkTrapFocus);

    // Declared ahead of the state because the sidenavWidth initializer below reads it.
    private readonly sidebarWidthService = inject(SidebarWidthService);

    /** Single source of truth for the sidebar state: collapsed and expanded are derived from it. */
    protected readonly sidenavWidth = this.sidebarWidthService.getWidth(
        MAIN_SIDENAV_WIDTH_KEY,
        MAIN_SIDENAV_WIDTH_OPTIONS
    );
    private readonly isPhone = inject(PhoneLayoutService).isPhone;
    // Read at once, as this layout is created during the navigation that shows it, then after every navigation.
    private readonly routeHidesSidenavOnPhone = signal(routeTreeHidesSidenav(inject(Router).routerState.snapshot.root));
    /** The sidenav is out of the layout and opens over the page on demand. */
    protected readonly isSidenavDrawer = computed(() => this.isPhone() && this.routeHidesSidenavOnPhone());
    protected readonly isSidenavDrawerOpen = computed(() => this.isSidenavDrawer() && this.navigationDrawer.isOpen());

    // Out of the drawer layout (a wider screen, another page) nothing stays open behind the scenes.
    private readonly closeDrawerOutsideItsLayout = effect(() => {
        if (!this.isSidenavDrawer()) untracked(() => this.navigationDrawer.close());
    });
    // Opening moves the focus into the navigation, which keeps it there until it closes. No scrolling to it: it is
    // still sliding in from past the edge.
    private readonly focusOpenedDrawer = effect(() => {
        if (!this.isSidenavDrawerOpen()) return;
        untracked(() =>
            afterNextRender(() => this.sidenavTrap().focusTrap.focusFirstTabbableElement({ preventScroll: true }), {
                injector: this.injector,
            })
        );
    });

    protected readonly sidenavWidthKey = MAIN_SIDENAV_WIDTH_KEY;
    protected readonly sidenavWidthOptions = MAIN_SIDENAV_WIDTH_OPTIONS;
    protected readonly navigationDrawer = inject(AppNavigationDrawerService);

    /**
     * The app shell (and with it the sidenav the tour points at) exists only here, so the auto-start lives here too.
     * Re-runs on user change and on permission change (org switch), so a newly permitted user still gets the tour.
     */
    private readonly quickStartTourAutoStart = effect(() => {
        const user = this.profileService.currentUserSignal();
        const isTourAvailable = this.quickStartTourService.isAvailable();
        if (user && isTourAvailable) {
            untracked(() => this.quickStartTourService.startIfNotCompleted());
        }
    });

    private router = inject(Router);
    private destroyRef = inject(DestroyRef);
    private lastVisitedTabService = inject(LastVisitedTabService);
    private readonly profileService = inject(ProfileService);
    private readonly quickStartTourService = inject(QuickStartTourService);
    private readonly appReturnUrl = inject(AppReturnUrlService);
    private readonly injector = inject(Injector);
    // The page shown, without its query: a navigation that changes only the query (a page's own state) stays on it.
    private shownPath = urlPath(this.router.url);

    ngOnInit(): void {
        this.destroyRef.onDestroy(() => this.quickStartTourService.stop());
        // The page this layout opened with: its navigation ended before the subscription below.
        this.appReturnUrl.record(this.router.url);

        this.router.events
            .pipe(
                filter((e): e is NavigationEnd => e instanceof NavigationEnd),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((e) => {
                // A move to another page made elsewhere closes the app navigation (a link in it closes it on the click);
                // a page's own navigation that changes only its query does not.
                const url = e.urlAfterRedirects;
                if (urlPath(url) !== this.shownPath) this.navigationDrawer.close();
                this.shownPath = urlPath(url);
                // Only pages in this layout get here (it is gone on the sign-in and organization chooser pages); the
                // service keeps EpicStaff's own, for "Back to EpicStaff" from an app.
                this.appReturnUrl.record(url);
                this.routeHidesSidenavOnPhone.set(routeTreeHidesSidenav(this.router.routerState.snapshot.root));
                for (const [parent, tabs] of Object.entries(TABBED_ROUTES)) {
                    if (tabs.includes(url)) {
                        this.lastVisitedTabService.set(parent, url);
                        break;
                    }
                }
            });
    }

    /**
     * A link followed in the open app navigation closes it, whatever its navigation changes: the Chat item from a
     * conversation's URL changes only the query, and the page already shown nothing at all (the router skips it). A
     * link opened elsewhere (a new tab) leaves this page, and the navigation open over it, as they are.
     */
    protected onSidenavClick(event: MouseEvent): void {
        const target = event.target;
        if (!this.isSidenavDrawerOpen() || !isPlainPrimaryClick(event)) return;
        if (target instanceof Element && target.closest('a[href]')) this.navigationDrawer.close();
    }

    /** The sidenav's open/close control: the layout owns the width, so it applies and persists the change. */
    protected toggleSidenav(): void {
        this.sidebarWidthService.toggleCollapsed(MAIN_SIDENAV_WIDTH_KEY, MAIN_SIDENAV_WIDTH_OPTIONS);
    }
}

/** Whether a route in the tree, any level and any outlet, asks for the sidenav to leave the layout on phones. */
function routeTreeHidesSidenav(route: ActivatedRouteSnapshot): boolean {
    return route.data[HIDE_SIDENAV_ON_PHONE] === true || route.children.some(routeTreeHidesSidenav);
}
