import { CdkTrapFocus } from '@angular/cdk/a11y';
import {
    afterNextRender,
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    effect,
    HostListener,
    inject,
    Injector,
    OnInit,
    signal,
    untracked,
    viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRouteSnapshot, NavigationEnd, Router, RouterOutlet } from '@angular/router';
import { isPlainPrimaryClick, urlPath } from '@shared/utils';
import { filter } from 'rxjs/operators';

import { AppNavigationDrawerService, HIDE_SIDENAV_ON_PHONE } from '../../core/services/app-navigation-drawer.service';
import { PhoneLayoutService } from '../../core/services/phone-layout.service';
import { EpicChatService } from '../../features/epic-chat/epic-chat.service';
import { LastVisitedTabService } from '../../services/last-visited-tab.service';
import { LeftSidebarComponent } from './sidenav/sidenav.component';

const TABBED_ROUTES: Record<string, string[]> = {
    '/tools': ['/tools/custom', '/tools/mcp'],
    '/flows': ['/flows/my', '/flows/templates'],
    '/storage': ['/storage/knowledge-sources', '/storage/files', '/storage/key-value-tables'],
};

@Component({
    selector: 'app-main-layout',
    imports: [CdkTrapFocus, LeftSidebarComponent, RouterOutlet],
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

            .sidebar-wrapper {
                width: 3.7rem;
                flex-shrink: 0;
            }

            // Out of the layout, past the left edge, until opened over the page. Hidden, not removed: the sidenav
            // runs the chat inbox stream and the EpicChat widget.
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

            .chat-dock-spacer {
                position: relative;
                flex-shrink: 0;
                border-right: 1px solid var(--color-divider-subtle);
                background: var(--color-background-body);
            }

            .chat-dock-resizer {
                position: absolute;
                top: 0;
                right: -4px;
                width: 8px;
                height: 100%;
                cursor: col-resize;
                z-index: 10;
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
            class="sidebar-wrapper"
            [class.sidebar-wrapper--drawer]="isSidenavDrawer()"
            [class.sidebar-wrapper--open]="isSidenavDrawerOpen()"
            [attr.inert]="isSidenavDrawer() && !isSidenavDrawerOpen() ? '' : null"
            [attr.role]="isSidenavDrawerOpen() ? 'dialog' : null"
            [attr.aria-modal]="isSidenavDrawerOpen() ? 'true' : null"
            [attr.aria-label]="isSidenavDrawerOpen() ? 'App navigation' : null"
            [cdkTrapFocus]="isSidenavDrawerOpen()"
            (keydown.escape)="navigationDrawer.close()"
            (click)="onSidenavClick($event)"
        >
            <app-left-sidebar></app-left-sidebar>
        </div>

        @if (isSidenavDrawerOpen()) {
            <div
                class="sidebar-backdrop"
                animate.enter="sidebar-backdrop--entering"
                animate.leave="sidebar-backdrop--leaving"
                (click)="navigationDrawer.close()"
            ></div>
        }

        @if (showsDockSpacer()) {
            <div
                class="chat-dock-spacer"
                [style.width.px]="epicChatService.dockWidth()"
            >
                <div
                    class="chat-dock-resizer"
                    (mousedown)="onDockResizeStart($event)"
                ></div>
            </div>
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

    private readonly isPhone = inject(PhoneLayoutService).isPhone;
    // Read at once, as this layout is created during the navigation that shows it, then after every navigation.
    private readonly routeHidesSidenavOnPhone = signal(routeTreeHidesSidenav(inject(Router).routerState.snapshot.root));
    /** The sidenav is out of the layout and opens over the page on demand. */
    protected readonly isSidenavDrawer = computed(() => this.isPhone() && this.routeHidesSidenavOnPhone());
    protected readonly isSidenavDrawerOpen = computed(() => this.isSidenavDrawer() && this.navigationDrawer.isOpen());
    // A docked EpicChat would take the width the sidenav just gave up.
    protected readonly showsDockSpacer = computed(
        () => this.epicChatService.isDocked() && this.epicChatService.isChatOpen() && !this.isSidenavDrawer()
    );

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

    readonly epicChatService = inject(EpicChatService);
    protected readonly navigationDrawer = inject(AppNavigationDrawerService);

    private isDockResizing = false;
    private dockResizeStartX = 0;
    private dockResizeStartWidth = 0;

    private router = inject(Router);
    private destroyRef = inject(DestroyRef);
    private lastVisitedTabService = inject(LastVisitedTabService);
    private readonly injector = inject(Injector);
    // The page shown, without its query: a navigation that changes only the query (a page's own state) stays on it.
    private shownPath = urlPath(this.router.url);

    ngOnInit(): void {
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

    public onDockResizeStart(event: MouseEvent): void {
        if (!this.epicChatService.isDocked()) {
            return;
        }
        event.preventDefault();
        this.isDockResizing = true;
        this.dockResizeStartX = event.clientX;
        this.dockResizeStartWidth = this.epicChatService.dockWidth();
    }

    @HostListener('window:mousemove', ['$event'])
    public onDockResizeMove(event: MouseEvent): void {
        if (!this.isDockResizing) {
            return;
        }
        const delta = event.clientX - this.dockResizeStartX;
        this.epicChatService.setDockWidth(this.dockResizeStartWidth + delta);
    }

    @HostListener('window:mouseup')
    public onDockResizeEnd(): void {
        this.isDockResizing = false;
    }
}

/** Whether a route in the tree, any level and any outlet, asks for the sidenav to leave the layout on phones. */
function routeTreeHidesSidenav(route: ActivatedRouteSnapshot): boolean {
    return route.data[HIDE_SIDENAV_ON_PHONE] === true || route.children.some(routeTreeHidesSidenav);
}
