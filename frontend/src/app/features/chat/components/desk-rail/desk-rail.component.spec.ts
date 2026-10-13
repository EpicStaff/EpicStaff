import { BreakpointObserver, BreakpointState } from '@angular/cdk/layout';
import { Component, computed, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { ActionCode, ResourceCode } from '@shared/models';
import { BehaviorSubject, map, Observable, of } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { CHAT_BINDING_DEFAULTS, ChatBinding } from '../../models/chat.model';
import { ChatBindingActionsService } from '../../services/chat-binding-actions.service';
import { ChatDesksStorageService } from '../../services/chat-desks-storage.service';
import { DeskRailComponent, DeskRailPresentation } from './desk-rail.component';

const STORAGE_KEY = 'chat:deskRailMode';

const desk = (overrides: Partial<ChatBinding>): ChatBinding => ({
    ...CHAT_BINDING_DEFAULTS,
    id: 'b-1',
    org_id: 1,
    graph_id: 5,
    name: 'Support',
    bot_display_name: 'Support',
    public_key: 'pk',
    is_active: true,
    token_budget_per_conversation: 1000,
    daily_token_budget: 1_000_000,
    broken_reason: null,
    contract_errors: [],
    created_at: '',
    updated_at: '',
    ...overrides,
});

const DESKS: ChatBinding[] = [
    desk({ id: 'b-2', name: 'Sales', is_active: false }),
    desk({ id: 'b-1', name: 'Support' }),
    desk({ id: 'b-3', name: 'Billing', broken_reason: 'flow deleted' }),
];

@Component({ template: '' })
class StubPageComponent {}

// The failed state's Retry button collapses its label on overflow, which jsdom cannot measure.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

/** The storage's state as the rail reads it: a loaded list by default. */
function createDesksStorage() {
    const desks = signal<ChatBinding[]>(DESKS);
    const landedRequest = signal(1);
    const loadFailed = signal(false);
    return {
        desks,
        landedRequest,
        loadFailed,
        isLoaded: computed(() => landedRequest() > 0),
        reload: vi.fn(() => 2),
    };
}

describe('DeskRailComponent', () => {
    let fixture: ComponentFixture<DeskRailComponent>;
    let isNarrowScreen: BehaviorSubject<boolean>;
    let navigate: ReturnType<typeof vi.spyOn>;
    let canCreate: boolean;
    let desksStorage: ReturnType<typeof createDesksStorage>;
    const bindingActions = { create: vi.fn<() => Observable<ChatBinding | null>>() };

    function render(
        waitingByDesk: Record<string, number> = {},
        presentation: DeskRailPresentation = 'rail'
    ): HTMLElement {
        fixture = TestBed.createComponent(DeskRailComponent);
        fixture.componentRef.setInput('waitingByDesk', waitingByDesk);
        fixture.componentRef.setInput('presentation', presentation);
        fixture.detectChanges();
        return fixture.nativeElement as HTMLElement;
    }

    const host = (): HTMLElement => fixture.nativeElement as HTMLElement;
    const links = (): HTMLAnchorElement[] =>
        Array.from(host().querySelectorAll<HTMLAnchorElement>('a.desk-rail__entry'));
    const linkNames = (): (string | null)[] =>
        links().map((link) => link.querySelector('app-desk-avatar')?.getAttribute('aria-label') ?? null);
    const toggle = (): HTMLButtonElement | null => host().querySelector('.desk-rail__toggle');
    const newDesk = (): HTMLButtonElement | null => host().querySelector('.desk-rail__new');
    const isCompact = (): boolean => host().classList.contains('desk-rail--compact');
    const statusRegion = (): HTMLElement | null => host().querySelector('[role="status"]');

    /** Lets the rail finish its first render, after which its status region starts speaking. */
    async function settle(): Promise<void> {
        await fixture.whenStable();
        fixture.detectChanges();
    }

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        localStorage.clear();
        vi.clearAllMocks();
        canCreate = true;
        isNarrowScreen = new BehaviorSubject(false);
        desksStorage = createDesksStorage();
        TestBed.configureTestingModule({
            imports: [DeskRailComponent],
            providers: [
                provideRouter([{ path: 'chat-bindings/:bindingId', component: StubPageComponent }]),
                { provide: ChatDesksStorageService, useValue: desksStorage },
                { provide: ChatBindingActionsService, useValue: bindingActions },
                {
                    provide: PermissionsService,
                    useValue: {
                        can: (resource: ResourceCode, action: ActionCode) =>
                            resource === ResourceCode.Chats && (action !== ActionCode.Create || canCreate),
                    },
                },
                {
                    provide: BreakpointObserver,
                    useValue: {
                        observe: (): Observable<BreakpointState> =>
                            isNarrowScreen.pipe(map((matches) => ({ matches, breakpoints: {} }))),
                    },
                },
            ],
        });
        navigate = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    });

    afterEach(() => {
        vi.restoreAllMocks();
        vi.unstubAllGlobals();
        localStorage.clear();
    });

    it('lists All desks first, then every desk by name, each linking to its page', () => {
        render();
        expect(links().map((link) => link.getAttribute('href'))).toEqual([
            '/chat-bindings/all',
            '/chat-bindings/b-3',
            '/chat-bindings/b-2',
            '/chat-bindings/b-1',
        ]);
        expect(Array.from(host().querySelectorAll('.desk-rail__name')).map((name) => name.textContent)).toEqual([
            'All desks',
            'Billing',
            'Sales',
            'Support',
            'New desk',
        ]);
    });

    it('names each entry in words through its avatar, with the status and the people waiting', () => {
        render({ 'b-1': 2, 'b-2': 1 });
        expect(linkNames()).toEqual([
            'All desks, 3 waiting for a person',
            'Billing desk, Broken',
            'Sales desk, Paused, 1 waiting for a person',
            'Support desk, Live, 2 waiting for a person',
        ]);
        // The listed name and badge repeat what the avatar says, so assistive technology skips them.
        host()
            .querySelectorAll('.desk-rail__name, .desk-rail__badge')
            .forEach((node) => expect(node.getAttribute('aria-hidden')).toBe('true'));
    });

    it('shows each count beside the name in the list, All desks the total, capped at 99+', () => {
        render({ 'b-1': 120, 'b-2': 4 });
        const badges = links().map((link) => link.querySelector('.desk-rail__badge')?.textContent ?? null);
        expect(badges).toEqual(['99+', null, '4', '99+']);
        // Not twice: the avatars draw no badge of their own in the list.
        expect(host().querySelector('.desk-avatar__badge')).toBeNull();
    });

    it('marks the entry of the current page', async () => {
        render();
        const router = TestBed.inject(Router);
        const selected = (): (string | null)[] =>
            links()
                .filter((link) => link.getAttribute('aria-current') === 'page')
                .map((link) => link.getAttribute('href'));

        await router.navigateByUrl('/chat-bindings/b-2');
        fixture.detectChanges();
        expect(selected()).toEqual(['/chat-bindings/b-2']);
        expect(host().querySelectorAll('.desk-rail__entry--selected').length).toBe(1);

        await router.navigateByUrl('/chat-bindings/all');
        fixture.detectChanges();
        expect(selected()).toEqual(['/chat-bindings/all']);
    });

    it('offers New desk only with the chats create permission', () => {
        render();
        expect(newDesk()?.getAttribute('aria-label')).toBe('New desk');

        canCreate = false;
        render();
        expect(newDesk()).toBeNull();
    });

    it('shows a loading state, and no New desk, until the first list lands', () => {
        desksStorage.desks.set([]);
        desksStorage.landedRequest.set(0);
        render();
        expect(links().length).toBe(1);
        expect(host().querySelector('.desk-rail__state')?.textContent).toContain('Loading desks…');
        expect(newDesk()).toBeNull();

        desksStorage.desks.set(DESKS);
        desksStorage.landedRequest.set(1);
        fixture.detectChanges();
        expect(host().querySelector('.desk-rail__state')).toBeNull();
        expect(links().length).toBe(4);
        expect(newDesk()).not.toBeNull();
    });

    it('says "Loading desks…" through one status region outside the list, by changing only its text', async () => {
        desksStorage.desks.set([]);
        desksStorage.landedRequest.set(0);
        render();
        const region = statusRegion();
        // Inserted empty: a live region announces a change of its text, not the text it arrived with.
        expect(region?.textContent?.trim()).toBe('');
        expect(region?.closest('ul')).toBeNull();
        expect(host().querySelectorAll('[role="status"]').length).toBe(1);
        // The visible spinner repeats it, so it is hidden from assistive technology.
        expect(host().querySelector('.desk-rail__state')?.getAttribute('aria-hidden')).toBe('true');

        await settle();
        expect(statusRegion()).toBe(region);
        expect(region?.textContent?.trim()).toBe('Loading desks…');

        desksStorage.desks.set(DESKS);
        desksStorage.landedRequest.set(1);
        fixture.detectChanges();
        expect(statusRegion()).toBe(region);
        expect(region?.textContent?.trim()).toBe('');
    });

    it('keeps the list a list: only plain items, whatever the state', async () => {
        const onlyPlainItems = (): boolean =>
            Array.from(host().querySelector('ul.desk-rail__entries')!.children).every(
                (child) => child.tagName === 'LI' && !child.hasAttribute('role')
            );
        desksStorage.desks.set([]);
        desksStorage.landedRequest.set(0);
        render();
        await settle();
        expect(onlyPlainItems()).toBe(true);

        desksStorage.loadFailed.set(true);
        fixture.detectChanges();
        expect(onlyPlainItems()).toBe(true);

        desksStorage.loadFailed.set(false);
        desksStorage.desks.set(DESKS);
        desksStorage.landedRequest.set(1);
        fixture.detectChanges();
        expect(onlyPlainItems()).toBe(true);
    });

    it('says the list failed, offers Retry instead of New desk, and retries', () => {
        desksStorage.desks.set([]);
        desksStorage.landedRequest.set(0);
        desksStorage.loadFailed.set(true);
        render();
        expect(host().querySelector('app-fetch-error-state')?.textContent).toContain("Couldn't load desks");
        expect(newDesk()).toBeNull();

        (host().querySelector('app-fetch-error-state button') as HTMLButtonElement).click();
        expect(desksStorage.reload).toHaveBeenCalledTimes(1);
    });

    it('keeps Retry in the compact rail as a named icon button, and says the list failed', async () => {
        localStorage.setItem(STORAGE_KEY, 'compact');
        desksStorage.desks.set([]);
        desksStorage.landedRequest.set(0);
        desksStorage.loadFailed.set(true);
        render();
        await settle();
        // Listed, the shared error state is an alert of its own; compact has only the button, so the region says it.
        expect(statusRegion()?.textContent?.trim()).toBe("Couldn't load desks.");
        const retry = host().querySelector<HTMLButtonElement>('.desk-rail__retry');
        expect(retry?.getAttribute('aria-label')).toBe("Couldn't load desks. Retry");
        retry!.click();
        expect(desksStorage.reload).toHaveBeenCalledTimes(1);
        expect(newDesk()).toBeNull();
    });

    it('reloads the desks and opens a created desk', () => {
        render();
        bindingActions.create.mockReturnValueOnce(of(desk({ id: 'b-9', name: 'New' })));
        newDesk()!.click();
        expect(bindingActions.create).toHaveBeenCalled();
        expect(desksStorage.reload).toHaveBeenCalledTimes(1);
        expect(navigate).toHaveBeenCalledWith(['/chat-bindings', 'b-9']);
    });

    it('still reloads but stays put when the create dialog closes without a desk', () => {
        render();
        bindingActions.create.mockReturnValueOnce(of(null));
        newDesk()!.click();
        expect(desksStorage.reload).toHaveBeenCalledTimes(1);
        expect(navigate).not.toHaveBeenCalled();
    });

    it('starts as a list, switches to compact with the toggle and remembers it', () => {
        render();
        expect(isCompact()).toBe(false);
        expect(toggle()?.getAttribute('aria-label')).toBe('Hide desk names');

        toggle()!.click();
        fixture.detectChanges();
        expect(isCompact()).toBe(true);
        expect(localStorage.getItem(STORAGE_KEY)).toBe('compact');
        expect(toggle()?.getAttribute('aria-label')).toBe('Show desk names');
        // Compact: avatars only, each with its own badge; names move to tooltips.
        expect(host().querySelector('.desk-rail__name')).toBeNull();
        expect(host().querySelector('.desk-rail__title')).toBeNull();

        toggle()!.click();
        fixture.detectChanges();
        expect(isCompact()).toBe(false);
        expect(localStorage.getItem(STORAGE_KEY)).toBe('list');
    });

    it('draws the badges on the avatars when compact', () => {
        localStorage.setItem(STORAGE_KEY, 'compact');
        render({ 'b-1': 2 });
        expect(isCompact()).toBe(true);
        expect(Array.from(host().querySelectorAll('.desk-avatar__badge')).map((badge) => badge.textContent)).toEqual([
            '2',
            '2',
        ]);
        expect(host().querySelector('.desk-rail__badge')).toBeNull();
    });

    it('reads the stored mode and falls back to a list on an unknown value', () => {
        localStorage.setItem(STORAGE_KEY, 'compact');
        render();
        expect(isCompact()).toBe(true);

        TestBed.resetTestingModule();
        localStorage.setItem(STORAGE_KEY, 'sideways');
        TestBed.configureTestingModule({
            imports: [DeskRailComponent],
            providers: [
                provideRouter([]),
                { provide: ChatDesksStorageService, useValue: createDesksStorage() },
                { provide: ChatBindingActionsService, useValue: bindingActions },
                { provide: PermissionsService, useValue: { can: () => true } },
            ],
        });
        render();
        expect(isCompact()).toBe(false);
    });

    it('works without storage: starts as a list and keeps a switch in memory', () => {
        vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
            throw new Error('denied');
        });
        vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
            throw new Error('denied');
        });
        render();
        expect(isCompact()).toBe(false);

        toggle()!.click();
        fixture.detectChanges();
        expect(isCompact()).toBe(true);
    });

    it('is compact on a narrow screen whatever was picked, and hides the toggle meanwhile', () => {
        localStorage.setItem(STORAGE_KEY, 'list');
        isNarrowScreen.next(true);
        render();
        expect(isCompact()).toBe(true);
        expect(toggle()).toBeNull();

        isNarrowScreen.next(false);
        fixture.detectChanges();
        expect(isCompact()).toBe(false);
        expect(toggle()).not.toBeNull();
        expect(localStorage.getItem(STORAGE_KEY)).toBe('list');
    });

    it('always lists names in the phone drawer, whatever was picked or the screen, without the toggle', () => {
        localStorage.setItem(STORAGE_KEY, 'compact');
        isNarrowScreen.next(true);
        render({ 'b-1': 2 }, 'drawer');

        expect(host().classList).toContain('desk-rail--drawer');
        expect(isCompact()).toBe(false);
        expect(toggle()).toBeNull();
        expect(host().querySelector('.desk-rail__title')?.textContent?.trim()).toBe('Desks');
        expect(Array.from(host().querySelectorAll('.desk-rail__name')).map((name) => name.textContent?.trim())).toEqual(
            ['All desks', 'Billing', 'Sales', 'Support', 'New desk']
        );
        // Listed, the counts sit beside the names, not on the avatars.
        expect(host().querySelector('.desk-avatar__badge')).toBeNull();
        // The column's choice is left as it was.
        expect(localStorage.getItem(STORAGE_KEY)).toBe('compact');
    });

    it('says an entry was picked on a plain click, not on one that opens it elsewhere (a new tab)', () => {
        render({}, 'drawer');
        const picks: number[] = [];
        fixture.componentInstance.picked.subscribe(() => picks.push(1));
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
                links()[1].dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, ...init }));
            }
            expect(picks).toEqual([]);

            links()[1].dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
            expect(picks).toEqual([1]);
        } finally {
            document.removeEventListener('click', keepPage);
        }
    });
});
