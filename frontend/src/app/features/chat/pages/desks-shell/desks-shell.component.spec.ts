import { InteractivityChecker } from '@angular/cdk/a11y';
import { BreakpointObserver, BreakpointState } from '@angular/cdk/layout';
import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { ActivationEnd, ActivationStart, NavigationEnd, provideRouter, Route, Router } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { BehaviorSubject, map, Observable, of } from 'rxjs';

import { routes } from '../../../../app.routes';
import { BREAKPOINTS } from '../../../../core/constants/breakpoints';
import { AppNavigationDrawerService } from '../../../../core/services/app-navigation-drawer.service';
import { ActiveOrgService } from '../../../../services/auth/active-org.service';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { DeskRailComponent } from '../../components/desk-rail/desk-rail.component';
import { CHAT_BINDING_DEFAULTS, ChatBinding } from '../../models/chat.model';
import { ChatApiService } from '../../services/chat-api.service';
import { ChatBindingActionsService } from '../../services/chat-binding-actions.service';
import { ChatInboxStreamService } from '../../services/chat-inbox-stream.service';
import { DeskDrawerService } from '../../services/desk-drawer.service';
import { DesksShellComponent } from './desks-shell.component';

const desk = (id: string, name: string): ChatBinding => ({
    ...CHAT_BINDING_DEFAULTS,
    id,
    org_id: 1,
    graph_id: 5,
    name,
    bot_display_name: name,
    public_key: 'pk',
    is_active: true,
    token_budget_per_conversation: 1000,
    daily_token_budget: 1_000_000,
    broken_reason: null,
    contract_errors: [],
    created_at: '',
    updated_at: '',
});

const DESKS = [desk('b-1', 'Support'), desk('b-2', 'Sales')];

/** Everything counts as on screen: jsdom lays nothing out, so the focus trap would find nothing to focus. */
class LaidOutInteractivityChecker extends InteractivityChecker {
    override isVisible(): boolean {
        return true;
    }
}

@Component({ template: '<p class="stub-page">page</p>' })
class StubPageComponent {}

// The page header hides its subtitle when it does not fit, which jsdom cannot measure.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

const findRoute = (list: Route[], path: string): Route | undefined => {
    for (const route of list) {
        if (route.path === path) return route;
        const nested = findRoute(route.children ?? [], path);
        if (nested) return nested;
    }
    return undefined;
};

/** The app's own desks route, guards let through and the pages stubbed: All desks and a desk stay two routes. */
function desksRoute(): Route {
    const chat = findRoute(routes, 'chat-bindings')!;
    const children = (chat.children ?? []).map((child) =>
        child.loadComponent ? { path: child.path, component: StubPageComponent } : child
    );
    return { ...chat, canActivate: [], children };
}

describe('DesksShellComponent', () => {
    const readyEpoch = signal(0);
    const waitingByBinding = signal<Record<string, number>>({});
    // Wider than a phone unless a spec says otherwise.
    const isPhone = new BehaviorSubject(false);
    const chatApi = { getBindings: vi.fn(() => of(DESKS)), getMyAliases: vi.fn(() => of([])) };
    let harness: RouterTestingHarness;
    let router: Router;

    const host = (): HTMLElement => harness.fixture.nativeElement as HTMLElement;
    const rail = (): DeskRailComponent =>
        harness.fixture.debugElement.query(By.directive(DeskRailComponent)).componentInstance as DeskRailComponent;
    const links = (): HTMLAnchorElement[] =>
        Array.from(host().querySelectorAll<HTMLAnchorElement>('a.desk-rail__entry'));
    const link = (href: string): HTMLAnchorElement => links().find((item) => item.getAttribute('href') === href)!;

    async function follow(target: HTMLAnchorElement): Promise<void> {
        target.focus();
        target.click();
        await harness.fixture.whenStable();
        harness.detectChanges();
    }

    beforeEach(async () => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        vi.clearAllMocks();
        localStorage.clear();
        readyEpoch.set(0);
        waitingByBinding.set({});
        isPhone.next(false);
        TestBed.configureTestingModule({
            providers: [
                provideRouter([desksRoute()]),
                { provide: ChatApiService, useValue: chatApi },
                { provide: ChatInboxStreamService, useValue: { readyEpoch, waitingByBinding } },
                { provide: PermissionsService, useValue: { can: () => true } },
                { provide: ChatBindingActionsService, useValue: { create: vi.fn() } },
                { provide: ToastService, useValue: { error: vi.fn() } },
                {
                    provide: BreakpointObserver,
                    useValue: {
                        observe: (query: string): Observable<BreakpointState> =>
                            (query === BREAKPOINTS.phone ? isPhone : of(false)).pipe(
                                map((matches) => ({ matches, breakpoints: {} }))
                            ),
                    },
                },
                // jsdom lays nothing out, so the focus trap would find nothing visible to focus.
                { provide: InteractivityChecker, useClass: LaidOutInteractivityChecker },
            ],
        });
        TestBed.inject(ActiveOrgService).set(1);
        router = TestBed.inject(Router);
        harness = await RouterTestingHarness.create();
        await harness.navigateByUrl('/chat-bindings/all');
    });

    afterEach(() => {
        vi.unstubAllGlobals();
        localStorage.clear();
    });

    it('heads the whole screen with the one h1, "Chat", and its subtitle, above the rail and the page', () => {
        const headings = host().querySelectorAll('h1');
        expect(headings.length).toBe(1);
        expect(headings[0].childNodes[0].textContent?.trim()).toBe('Chat');
        expect(host().querySelector('h1 .subtitle-inline')?.textContent?.trim()).toBe(
            'Publish flows as website chats and step in when a visitor needs a person.'
        );
        const header = host().querySelector('header.header')!;
        const below = header.nextElementSibling!;
        expect(below.querySelector('app-desk-rail')).not.toBeNull();
        expect(below.querySelector('.stub-page')).not.toBeNull();
        // The page below brings the one main landmark; the shell adds none of its own.
        expect(host().querySelectorAll('main, [role="main"]').length).toBe(0);
    });

    it('has no button in the page header: New desk stays in the rail', () => {
        const header = host().querySelector('header.header')!;
        expect(header.querySelectorAll('button, app-button, a').length).toBe(0);
        expect(host().querySelector('app-desk-rail .desk-rail__new')?.getAttribute('aria-label')).toBe('New desk');
    });

    it('keeps the same rail, and the focus on the link followed, when moving between All desks and a desk', async () => {
        const firstRail = rail();
        const deskLink = link('/chat-bindings/b-1');

        await follow(deskLink);
        expect(router.url).toBe('/chat-bindings/b-1');
        expect(rail()).toBe(firstRail);
        expect(document.activeElement).toBe(deskLink);
        expect(deskLink.getAttribute('aria-current')).toBe('page');

        const allDesksLink = link('/chat-bindings/all');
        await follow(allDesksLink);
        expect(router.url).toBe('/chat-bindings/all');
        expect(rail()).toBe(firstRail);
        expect(document.activeElement).toBe(allDesksLink);
        expect(allDesksLink.getAttribute('aria-current')).toBe('page');
        // The pages changed; the desks were not loaded again.
        expect(chatApi.getBindings).toHaveBeenCalledTimes(1);
    });

    it('never shows an empty rail while the page beside it changes', async () => {
        const entriesSeen: number[] = [];
        router.events.subscribe((event) => {
            if (event instanceof ActivationStart || event instanceof ActivationEnd || event instanceof NavigationEnd) {
                entriesSeen.push(links().length);
            }
        });

        await follow(link('/chat-bindings/b-2'));
        await follow(link('/chat-bindings/all'));
        expect(entriesSeen.length).toBeGreaterThan(0);
        // All desks and both desks, at every step of both navigations.
        expect(new Set(entriesSeen)).toEqual(new Set([3]));
    });

    it('loads the desks and my names on them once on open, again on a stream ready and for a newly active org, not for a logout', () => {
        expect(chatApi.getBindings).toHaveBeenCalledTimes(1);
        expect(chatApi.getMyAliases).toHaveBeenCalledTimes(1);

        readyEpoch.update((value) => value + 1);
        harness.detectChanges();
        expect(chatApi.getBindings).toHaveBeenCalledTimes(2);
        expect(chatApi.getMyAliases).toHaveBeenCalledTimes(2);

        const activeOrg = TestBed.inject(ActiveOrgService);
        activeOrg.set(2);
        harness.detectChanges();
        expect(chatApi.getBindings).toHaveBeenCalledTimes(3);
        expect(chatApi.getMyAliases).toHaveBeenCalledTimes(3);

        activeOrg.set(null);
        harness.detectChanges();
        expect(chatApi.getBindings).toHaveBeenCalledTimes(3);
        expect(chatApi.getMyAliases).toHaveBeenCalledTimes(3);
    });

    it('gives the rail the live waiting counts', () => {
        waitingByBinding.set({ 'b-1': 3 });
        harness.detectChanges();
        expect(link('/chat-bindings/b-1').querySelector('.desk-rail__badge')?.textContent).toBe('3');
        expect(link('/chat-bindings/all').querySelector('.desk-rail__badge')?.textContent).toBe('3');
    });

    describe('on a phone', () => {
        const drawerService = (): DeskDrawerService =>
            harness.fixture.debugElement.query(By.directive(DesksShellComponent)).injector.get(DeskDrawerService);
        const drawer = (): HTMLElement | null => host().querySelector('.desk-drawer');
        const drawerLink = (href: string): HTMLAnchorElement =>
            Array.from(drawer()!.querySelectorAll<HTMLAnchorElement>('a.desk-rail__entry')).find(
                (item) => item.getAttribute('href') === href
            )!;
        let switcher: HTMLButtonElement;

        /** The page's desk switcher, as the chat page registers it. */
        function registerSwitcher(): void {
            switcher = document.createElement('button');
            document.body.appendChild(switcher);
            drawerService().registerSwitcher(switcher);
        }

        async function openDrawer(): Promise<void> {
            drawerService().open();
            harness.detectChanges();
            await harness.fixture.whenStable();
        }

        async function settle(): Promise<void> {
            harness.detectChanges();
            await harness.fixture.whenStable();
            harness.detectChanges();
        }

        beforeEach(() => {
            isPhone.next(true);
            harness.detectChanges();
            registerSwitcher();
        });

        afterEach(() => switcher.remove());

        it('keeps only the h1 "Chat", for screen readers, and no rail beside the page', () => {
            expect(host().querySelector('header.header')).toBeNull();
            const headings = host().querySelectorAll('h1');
            expect(headings.length).toBe(1);
            expect(headings[0].classList).toContain('visually-hidden');
            expect(headings[0].textContent?.trim()).toBe('Chat');
            expect(host().querySelector('app-desk-rail')).toBeNull();
            expect(host().querySelector('.stub-page')).not.toBeNull();
        });

        it('opens the desks as a modal dialog over an inert page: listed, with the App menu, the focus inside', async () => {
            await openDrawer();

            const dialog = drawer()!;
            expect(dialog.getAttribute('role')).toBe('dialog');
            expect(dialog.getAttribute('aria-modal')).toBe('true');
            expect(dialog.getAttribute('aria-label')).toBe('Desks');
            expect(dialog.querySelector('app-desk-rail')?.classList).toContain('desk-rail--drawer');
            expect(dialog.querySelectorAll('a.desk-rail__entry').length).toBe(3);
            expect(dialog.querySelector('.desk-drawer__app-menu')?.textContent?.trim()).toBe('App menu');
            expect(host().querySelector('.desks-shell__body')?.hasAttribute('inert')).toBe(true);
            expect(dialog.contains(document.activeElement)).toBe(true);
        });

        it('closes on Escape and on the backdrop, and gives the focus back to the desk switcher', async () => {
            await openDrawer();
            drawer()!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
            await settle();
            expect(drawer()).toBeNull();
            expect(host().querySelector('.desks-shell__body')?.hasAttribute('inert')).toBe(false);
            expect(document.activeElement).toBe(switcher);

            await openDrawer();
            (host().querySelector('.desk-drawer__backdrop') as HTMLElement).click();
            await settle();
            expect(drawer()).toBeNull();
            expect(document.activeElement).toBe(switcher);
        });

        it('closes once a desk is picked, the one already open included', async () => {
            await openDrawer();
            drawerLink('/chat-bindings/b-1').click();
            await settle();
            expect(router.url).toBe('/chat-bindings/b-1');
            expect(drawer()).toBeNull();

            await openDrawer();
            drawerLink('/chat-bindings/b-1').click();
            await settle();
            expect(drawer()).toBeNull();
        });

        it('closes on a pick that changes only the query: All desks picked while the URL names a conversation', async () => {
            await router.navigateByUrl('/chat-bindings/all?conversation=c-gone');
            await settle();
            await openDrawer();

            drawerLink('/chat-bindings/all').click();
            await settle();

            expect(router.url).toBe('/chat-bindings/all');
            expect(drawer()).toBeNull();
            expect(document.activeElement).toBe(switcher);
        });

        it("stays open through the page's own navigations, which change only the query (the open conversation)", async () => {
            await openDrawer();
            await router.navigateByUrl('/chat-bindings/all?conversation=c-1', { replaceUrl: true });
            await settle();
            expect(drawer()).not.toBeNull();
        });

        it('hands over to the app navigation from App menu, which gives the focus back to the desk switcher', async () => {
            const appNavigation = TestBed.inject(AppNavigationDrawerService);
            const open = vi.spyOn(appNavigation, 'open');
            await openDrawer();

            (drawer()!.querySelector('.desk-drawer__app-menu') as HTMLButtonElement).click();
            await settle();

            expect(drawer()).toBeNull();
            expect(open).toHaveBeenCalledWith(switcher);
            expect(appNavigation.isOpen()).toBe(true);
        });

        it('closes, unseen, when the screen grows past a phone, and shows the rail again', async () => {
            await openDrawer();
            isPhone.next(false);
            harness.detectChanges();
            expect(drawerService().isOpen()).toBe(false);
            expect(host().querySelector('header.header')).not.toBeNull();
            expect(host().querySelectorAll('app-desk-rail').length).toBe(1);
        });
    });
});
