import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { ActivationEnd, ActivationStart, NavigationEnd, provideRouter, Route, Router } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { of } from 'rxjs';

import { routes } from '../../../../app.routes';
import { ActiveOrgService } from '../../../../services/auth/active-org.service';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { DeskRailComponent } from '../../components/desk-rail/desk-rail.component';
import { CHAT_BINDING_DEFAULTS, ChatBinding } from '../../models/chat.model';
import { ChatApiService } from '../../services/chat-api.service';
import { ChatBindingActionsService } from '../../services/chat-binding-actions.service';
import { ChatInboxStreamService } from '../../services/chat-inbox-stream.service';

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
    const awaitingByBinding = signal<Record<string, number>>({});
    const chatApi = { getBindings: vi.fn(() => of(DESKS)) };
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
        awaitingByBinding.set({});
        TestBed.configureTestingModule({
            providers: [
                provideRouter([desksRoute()]),
                { provide: ChatApiService, useValue: chatApi },
                { provide: ChatInboxStreamService, useValue: { readyEpoch, awaitingByBinding } },
                { provide: PermissionsService, useValue: { can: () => true } },
                { provide: ChatBindingActionsService, useValue: { create: vi.fn() } },
                { provide: ToastService, useValue: { error: vi.fn() } },
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

    it('loads the desks once on open, again on a stream ready and for a newly active org, not for a logout', () => {
        expect(chatApi.getBindings).toHaveBeenCalledTimes(1);

        readyEpoch.update((value) => value + 1);
        harness.detectChanges();
        expect(chatApi.getBindings).toHaveBeenCalledTimes(2);

        const activeOrg = TestBed.inject(ActiveOrgService);
        activeOrg.set(2);
        harness.detectChanges();
        expect(chatApi.getBindings).toHaveBeenCalledTimes(3);

        activeOrg.set(null);
        harness.detectChanges();
        expect(chatApi.getBindings).toHaveBeenCalledTimes(3);
    });

    it('gives the rail the live waiting counts', () => {
        awaitingByBinding.set({ 'b-1': 3 });
        harness.detectChanges();
        expect(link('/chat-bindings/b-1').querySelector('.desk-rail__badge')?.textContent).toBe('3');
        expect(link('/chat-bindings/all').querySelector('.desk-rail__badge')?.textContent).toBe('3');
    });
});
