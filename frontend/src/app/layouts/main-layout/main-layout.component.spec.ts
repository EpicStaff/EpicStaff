import { InteractivityChecker } from '@angular/cdk/a11y';
import { BreakpointObserver, BreakpointState } from '@angular/cdk/layout';
import { Component, input, output } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { provideRouter, Router, RouterLink } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { BehaviorSubject, map, Observable } from 'rxjs';

import { AppNavigationDrawerService, HIDE_SIDENAV_ON_PHONE } from '../../core/services/app-navigation-drawer.service';
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
        TestBed.configureTestingModule({
            providers: [
                provideRouter([
                    {
                        path: '',
                        component: MainLayoutComponent,
                        children: [
                            { path: 'agents', component: PageStubComponent },
                            {
                                // The flag counts anywhere in the active route tree: here on the parent.
                                path: 'chat-bindings',
                                data: { [HIDE_SIDENAV_ON_PHONE]: true },
                                children: [{ path: ':bindingId', component: PageStubComponent }],
                            },
                        ],
                    },
                ]),
                {
                    provide: BreakpointObserver,
                    useValue: {
                        observe: (): Observable<BreakpointState> =>
                            isPhone.pipe(map((matches) => ({ matches, breakpoints: {} }))),
                    },
                },
                { provide: InteractivityChecker, useClass: LaidOutInteractivityChecker },
            ],
        });
        TestBed.overrideComponent(MainLayoutComponent, {
            remove: { imports: [LeftSidebarComponent] },
            add: { imports: [SidebarStubComponent] },
        });
        drawer = TestBed.inject(AppNavigationDrawerService);
        harness = await RouterTestingHarness.create('/chat-bindings/all');
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
});
