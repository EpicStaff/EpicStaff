import { InteractivityChecker } from '@angular/cdk/a11y';
import { BreakpointObserver, BreakpointState } from '@angular/cdk/layout';
import { Component, input, output } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { provideRouter, Router, RouterLink } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { BehaviorSubject, map, Observable } from 'rxjs';

import { GuidedTourService, provideGuidedTours, TOUR_PROGRESS_STORE } from '../../core/guided-tour';
import { TOUR_RENDERER_LOADER } from '../../core/guided-tour/renderer/tour-renderer';
import { FakeTourProgressStore, FakeTourRenderer } from '../../core/guided-tour/testing/guided-tour-testing';
import { AppNavigationDrawerService, HIDE_SIDENAV_ON_PHONE } from '../../core/services/app-navigation-drawer.service';
import { pluginPageMatcher } from '../../features/plugins/pages/plugin-host-page/plugin-page.matcher';
import { AppReturnUrlService } from '../../features/plugins/services/app-return-url.service';
import { MainLayoutComponent } from './main-layout.component';
import { LeftSidebarComponent } from './sidenav/sidenav.component';

// The real sidenav pulls in the org and user menus, and the inbox stream.
@Component({
    selector: 'app-left-sidebar',
    imports: [RouterLink],
    template: `<nav>
        <a
            routerLink="/chat-bindings/b-1"
            class="sidebar-link"
            >Chat</a
        >
        <button
            type="button"
            class="sidebar-button"
        >
            Account
        </button>
    </nav>`,
})
class SidebarStubComponent {
    readonly width = input<number>();
    readonly inDrawer = input(false);
    readonly expandedToggle = output<void>();
}

@Component({ template: '<button type="button" class="page-button">App menu</button>' })
class PageStubComponent {}

/** Everything counts as on screen: jsdom lays nothing out, so the focus trap would find nothing to focus. */
class LaidOutInteractivityChecker extends InteractivityChecker {
    override isVisible(): boolean {
        return true;
    }
}

describe('MainLayoutComponent', () => {
    const isPhone = new BehaviorSubject(false);
    let harness: RouterTestingHarness;
    let drawer: AppNavigationDrawerService;
    let tourProgress: FakeTourProgressStore;
    let tourRenderers: FakeTourRenderer[];

    const host = (): HTMLElement => harness.fixture.nativeElement as HTMLElement;
    const wrapper = (): HTMLElement => host().querySelector('.sidebar-wrapper') as HTMLElement;
    const mainContent = (): HTMLElement => host().querySelector('.main-content') as HTMLElement;
    const backdrop = (): HTMLElement | null => host().querySelector('.sidebar-backdrop');
    const pageButton = (): HTMLButtonElement => host().querySelector('.page-button') as HTMLButtonElement;
    const sidebar = (): SidebarStubComponent =>
        harness.fixture.debugElement.query(By.directive(SidebarStubComponent)).componentInstance;

    async function settle(): Promise<void> {
        harness.detectChanges();
        await harness.fixture.whenStable();
        harness.detectChanges();
    }

    beforeEach(async () => {
        isPhone.next(false);
        tourProgress = new FakeTourProgressStore();
        tourRenderers = [];
        TestBed.configureTestingModule({
            providers: [
                provideRouter([
                    // Out of the app shell, like the sign-in page a sign-out leads to.
                    { path: 'login', component: PageStubComponent },
                    {
                        path: '',
                        component: MainLayoutComponent,
                        children: [
                            { path: 'agents', component: PageStubComponent },
                            { path: 'profile', component: PageStubComponent },
                            {
                                // The flag counts anywhere in the active route tree: here on the parent.
                                path: 'chat-bindings',
                                data: { [HIDE_SIDENAV_ON_PHONE]: true },
                                children: [{ path: ':bindingId', component: PageStubComponent }],
                            },
                            { matcher: pluginPageMatcher, component: PageStubComponent },
                        ],
                    },
                    // A page without this layout, as the plugin sign-in's organization chooser.
                    { path: 'plugin-choose-org', component: PageStubComponent },
                ]),
                {
                    provide: BreakpointObserver,
                    useValue: {
                        observe: (): Observable<BreakpointState> =>
                            isPhone.pipe(map((matches) => ({ matches, breakpoints: {} }))),
                    },
                },
                { provide: InteractivityChecker, useClass: LaidOutInteractivityChecker },
                provideGuidedTours(() => ({
                    key: 'intro',
                    label: 'Intro',
                    icon: 'help',
                    autoStart: 'until-completed',
                    isAvailable: () => true,
                    steps: [{ id: 'welcome', content: { title: 'Welcome', body: [] } }],
                })),
                { provide: TOUR_PROGRESS_STORE, useValue: tourProgress },
                {
                    provide: TOUR_RENDERER_LOADER,
                    useValue: async () => {
                        const renderer = new FakeTourRenderer();
                        tourRenderers.push(renderer);
                        return renderer;
                    },
                },
            ],
        });
        TestBed.overrideComponent(MainLayoutComponent, {
            remove: { imports: [LeftSidebarComponent] },
            add: { imports: [SidebarStubComponent] },
        });
        drawer = TestBed.inject(AppNavigationDrawerService);
        harness = await RouterTestingHarness.create('/chat-bindings/all');
    });

    afterEach(() => sessionStorage.clear());

    it('tells the sidenav whether it is the phone drawer', () => {
        expect(sidebar().inDrawer()).toBe(false);

        isPhone.next(true);
        harness.detectChanges();

        expect(sidebar().inDrawer()).toBe(true);
    });

    it('records the EpicStaff pages it shows for "Back to EpicStaff", not the apps or the pages outside it', async () => {
        const returnUrl = TestBed.inject(AppReturnUrlService);
        // The page the layout opened with.
        expect(returnUrl.url()).toBe('/chat-bindings/all');

        await harness.navigateByUrl('/agents?tab=1');
        expect(returnUrl.url()).toBe('/agents?tab=1');

        await harness.navigateByUrl('/plugins/asg/projects');
        expect(returnUrl.url()).toBe('/agents?tab=1');

        await harness.navigateByUrl('/plugin-choose-org?continue=%2Fauthorize');
        expect(returnUrl.url()).toBe('/agents?tab=1');
    });

    it('does not record a page shown without changing the address, as the reload an organization switch makes', async () => {
        const router = TestBed.inject(Router);
        const returnUrl = TestBed.inject(AppReturnUrlService);
        await harness.navigateByUrl('/agents');
        await harness.navigateByUrl('/plugins/asg/projects');

        // An organization switch in an app: a hidden visit to My Profile reloads the page, then the app opens again.
        await router.navigateByUrl('/profile', { skipLocationChange: true });
        await router.navigateByUrl('/plugins/asg');
        harness.detectChanges();

        expect(returnUrl.url()).toBe('/agents');
    });

    it('does not record the page it opens with when that page is shown without changing the address', async () => {
        const returnUrl = TestBed.inject(AppReturnUrlService);
        await harness.navigateByUrl('/plugin-choose-org');

        // A refused request's reload from a page out of this layout: the layout opens on the hidden visit.
        await TestBed.inject(Router).navigateByUrl('/profile', { skipLocationChange: true });
        harness.detectChanges();

        expect(returnUrl.url()).toBe('/chat-bindings/all');
    });

    it('keeps the sidenav in the layout on wider screens, and on phones for pages that do not opt in', async () => {
        expect(wrapper().classList).not.toContain('sidebar-wrapper--drawer');
        expect(wrapper().hasAttribute('inert')).toBe(false);

        isPhone.next(true);
        await harness.navigateByUrl('/agents');
        expect(wrapper().classList).not.toContain('sidebar-wrapper--drawer');
        expect(wrapper().hasAttribute('inert')).toBe(false);
    });

    it('takes the sidenav out of the layout on a phone in a page that opts in, alive but inert until opened', () => {
        const before = sidebar();
        isPhone.next(true);
        harness.detectChanges();

        expect(wrapper().classList).toContain('sidebar-wrapper--drawer');
        expect(wrapper().classList).not.toContain('sidebar-wrapper--open');
        expect(wrapper().hasAttribute('inert')).toBe(true);
        expect(wrapper().getAttribute('role')).toBeNull();
        // The same sidenav: it runs the chat inbox stream, which must not stop.
        expect(sidebar()).toBe(before);
    });

    it('opens over an inert page as a modal dialog with the focus inside; Escape closes it and returns the focus', async () => {
        isPhone.next(true);
        harness.detectChanges();
        pageButton().focus();

        drawer.open(pageButton());
        await settle();

        expect(wrapper().classList).toContain('sidebar-wrapper--open');
        expect(wrapper().getAttribute('role')).toBe('dialog');
        expect(wrapper().getAttribute('aria-modal')).toBe('true');
        expect(wrapper().getAttribute('aria-label')).toBe('App navigation');
        expect(wrapper().hasAttribute('inert')).toBe(false);
        expect(mainContent().hasAttribute('inert')).toBe(true);
        expect(backdrop()).not.toBeNull();
        expect(document.activeElement).toBe(host().querySelector('.sidebar-link'));

        wrapper().dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
        await settle();

        expect(drawer.isOpen()).toBe(false);
        expect(backdrop()).toBeNull();
        expect(mainContent().hasAttribute('inert')).toBe(false);
        expect(document.activeElement).toBe(pageButton());
    });

    it('closes on a backdrop tap, on a move to another page, not on a query change, and off phones', async () => {
        isPhone.next(true);
        harness.detectChanges();

        drawer.open(null);
        harness.detectChanges();
        backdrop()!.click();
        harness.detectChanges();
        expect(drawer.isOpen()).toBe(false);

        drawer.open(null);
        await harness.navigateByUrl('/chat-bindings/b-1');
        expect(drawer.isOpen()).toBe(false);

        // A page's own navigation that changes only its query is no new page.
        drawer.open(null);
        await harness.navigateByUrl('/chat-bindings/b-1?conversation=c-1');
        expect(drawer.isOpen()).toBe(true);
        drawer.close();

        drawer.open(null);
        isPhone.next(false);
        harness.detectChanges();
        expect(drawer.isOpen()).toBe(false);
        expect(wrapper().classList).not.toContain('sidebar-wrapper--drawer');
    });

    it("closes on a link followed in it, even one that changes only the query (Chat from a conversation's URL) or nothing", async () => {
        isPhone.next(true);
        await harness.navigateByUrl('/chat-bindings/b-1?conversation=c-1');
        drawer.open(null);
        harness.detectChanges();

        // Not a link: it stays open, through the page's own query navigation too.
        (host().querySelector('.sidebar-button') as HTMLButtonElement).click();
        await harness.navigateByUrl('/chat-bindings/b-1?conversation=c-2');
        expect(drawer.isOpen()).toBe(true);

        (host().querySelector('.sidebar-link') as HTMLAnchorElement).click();
        await settle();
        expect(TestBed.inject(Router).url).toBe('/chat-bindings/b-1');
        expect(drawer.isOpen()).toBe(false);

        // To the page already shown: the router skips it, the drawer closes all the same.
        drawer.open(null);
        harness.detectChanges();
        (host().querySelector('.sidebar-link') as HTMLAnchorElement).click();
        await settle();
        expect(drawer.isOpen()).toBe(false);
    });

    it('stays open when a link in it opens elsewhere (a new tab, a modifier key, the middle button)', async () => {
        isPhone.next(true);
        await harness.navigateByUrl('/chat-bindings/b-1?conversation=c-1');
        drawer.open(null);
        harness.detectChanges();
        // The browser would open the link in a new tab: jsdom must not try to navigate.
        const keepPage = (event: Event): void => event.preventDefault();
        document.addEventListener('click', keepPage);
        try {
            for (const init of [
                { ctrlKey: true },
                { metaKey: true },
                { shiftKey: true },
                { altKey: true },
                { button: 1 },
            ]) {
                const link = host().querySelector('.sidebar-link') as HTMLAnchorElement;
                link.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, ...init }));
                await settle();
            }
        } finally {
            document.removeEventListener('click', keepPage);
        }
        expect(drawer.isOpen()).toBe(true);
        expect(TestBed.inject(Router).url).toBe('/chat-bindings/b-1?conversation=c-1');
    });

    it('auto-starts tours while it is shown, and stops the running one, unsaved, once it is gone (sign-out)', async () => {
        const tours = TestBed.inject(GuidedTourService);

        tourProgress.signIn(1);
        await settle();

        expect(tours.activeTour()?.key).toBe('intro');
        expect(tourRenderers.at(-1)?.view?.content.title).toBe('Welcome');

        await harness.navigateByUrl('/login');

        expect(tours.activeTour()).toBeNull();
        expect(tourRenderers.at(-1)?.isDisposed).toBe(true);
        expect(tourProgress.savedTourKeys).toEqual([]);
    });
});
