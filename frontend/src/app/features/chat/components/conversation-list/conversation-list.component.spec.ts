import { HttpErrorResponse } from '@angular/common/http';
import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ConfirmationDialogService } from '@shared/components';
import { ActionCode, ResourceCode } from '@shared/models';
import { Observable, of, Subject, throwError } from 'rxjs';

import { ActiveOrgService } from '../../../../services/auth/active-org.service';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ProfileService } from '../../../../services/auth/profile.service';
import { ToastService } from '../../../../services/notifications';
import {
    CHAT_BINDING_DEFAULTS,
    ChatBinding,
    ChatConversation,
    ChatConversationPage,
    ChatInboxSection,
} from '../../models/chat.model';
import { ChatApiService, ConversationListParams } from '../../services/chat-api.service';
import { ChatDesksStorageService } from '../../services/chat-desks-storage.service';
import { ChatInboxStreamService } from '../../services/chat-inbox-stream.service';
import { ConversationListPreferencesService } from '../../services/conversation-list-preferences.service';
import { SEARCH_DEBOUNCE_MS } from '../conversation-list-toolbar/conversation-list-toolbar.component';
import { ConversationListComponent } from './conversation-list.component';
import { ConversationListStore } from './conversation-list.store';

const PREFERENCES_KEY = 'chat:conversationList';

// The rows' Take over button collapses its label on overflow, which jsdom cannot measure.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

/** Records every observer, so a spec can report a section's end scrolling into view. */
class IntersectionObserverStub {
    static instances: IntersectionObserverStub[] = [];
    readonly observed: Element[] = [];
    disconnected = false;

    constructor(
        private readonly callback: (entries: Partial<IntersectionObserverEntry>[]) => void,
        readonly options?: IntersectionObserverInit
    ) {
        IntersectionObserverStub.instances.push(this);
    }

    observe(target: Element): void {
        this.observed.push(target);
    }

    disconnect(): void {
        this.disconnected = true;
    }

    /** The live observers' sentinels of `section` enter the view. */
    static scrollIntoView(section: ChatInboxSection): void {
        for (const observer of IntersectionObserverStub.instances.filter((instance) => !instance.disconnected)) {
            const targets = observer.observed.filter(
                (target) => (target as HTMLElement).dataset['section'] === section
            );
            if (targets.length) observer.callback(targets.map((target) => ({ target, isIntersecting: true })));
        }
    }
}

const row = (overrides: Partial<ChatConversation>): ChatConversation => ({
    id: 'c-1',
    binding_id: 'b-1',
    visitor_number: 1,
    chat_user_id: null,
    mode: 'bot',
    state: 'idle',
    is_test: false,
    assigned_operator_id: null,
    assigned_operator_name: null,
    tokens_used: 0,
    turns: 0,
    tokens_today: 0,
    turns_today: 0,
    last_message_at: '2026-10-10T10:00:00Z',
    last_message_preview: 'hello',
    last_message_role: 'user',
    last_message_author_user_id: null,
    last_message_author_name: null,
    handoff_reason: '',
    handoff_at: null,
    visitor_waiting_since: null,
    status: 'open',
    close_reason: null,
    closed_at: null,
    closed_by_user_id: null,
    closed_by_name: null,
    ...overrides,
});

const handedOff = (id: string, handoffAt: string, overrides: Partial<ChatConversation> = {}): ChatConversation =>
    row({
        id,
        mode: 'awaiting_human',
        handoff_at: handoffAt,
        visitor_waiting_since: handoffAt,
        last_message_preview: id,
        ...overrides,
    });

/** Taken by an operator who answered last: In progress. */
const answered = (id: string, lastMessageAt: string, overrides: Partial<ChatConversation> = {}): ChatConversation =>
    row({
        id,
        mode: 'human',
        assigned_operator_id: 7,
        handoff_at: '2026-10-10T07:00:00Z',
        last_message_at: lastMessageAt,
        last_message_role: 'operator',
        last_message_preview: id,
        ...overrides,
    });

const page = (results: ChatConversation[], next_cursor: string | null = null): Observable<ChatConversationPage> =>
    of({ results, next_cursor });

/** Every parameter the column sends for a section, with what it sends when nothing is chosen. */
const listParams = (
    section: ChatInboxSection,
    overrides: Partial<ConversationListParams> = {}
): ConversationListParams => ({
    section,
    binding: null,
    cursor: null,
    mine: false,
    order: 'newest',
    q: '',
    ...overrides,
});

const desk: ChatBinding = {
    ...CHAT_BINDING_DEFAULTS,
    response_time_seconds: 600,
    on_response_timeout: 'handback',
    handback_message: 'Back to the bot.',
    close_after_seconds: 86_400,
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
};

describe('ConversationListComponent', () => {
    let fixture: ComponentFixture<ConversationListComponent>;
    let serverDesks: ChatBinding[] = [];
    const conversationUpdated$ = new Subject<ChatConversation>();
    const readyEpoch = signal(0);
    // What the stream's waiting set counts for whatever the column asks.
    const waitingCount = signal(0);
    const chatInboxStream = {
        conversationUpdated$,
        readyEpoch,
        waitingCountFor: vi.fn<(bindingId: string | null, holderId: number | null) => number>(() => waitingCount()),
    };
    const chatApi = {
        getBindings: vi.fn(() => of(serverDesks)),
        // By default Waiting, In progress and Tests are empty and Bot holds one conversation.
        getConversations: vi.fn(
            (params: ConversationListParams): Observable<ChatConversationPage> =>
                page(params.section === 'bot' ? [row({ id: 'c-1' })] : [])
        ),
        claim: vi.fn(),
        release: vi.fn(),
    };
    const permissions: { can: (resource: ResourceCode, action: ActionCode) => boolean } = {
        can: (resource, action) =>
            resource === ResourceCode.Chats && (action === ActionCode.Use || action === ActionCode.Create),
    };

    const host = (): HTMLElement => fixture.nativeElement as HTMLElement;
    const store = (): ConversationListStore => fixture.debugElement.injector.get(ConversationListStore);
    const ids = (section: ChatInboxSection): string[] =>
        store()
            .sections()
            [section].rows.map((item) => item.id);
    const rowButtons = (): HTMLButtonElement[] =>
        Array.from(host().querySelectorAll<HTMLButtonElement>('button.conversation-row'));
    const headerButton = (label: string): HTMLButtonElement =>
        Array.from(host().querySelectorAll<HTMLButtonElement>('.conversation-section-header')).find(
            (button) => button.textContent?.trim() === label
        )!;
    const requestedSections = (): ChatInboxSection[] =>
        chatApi.getConversations.mock.calls.map(([params]) => params.section);
    const sentinels = (): string[] =>
        Array.from(host().querySelectorAll<HTMLElement>('.conversation-list__sentinel')).map(
            (sentinel) => sentinel.dataset['section'] ?? ''
        );

    const searchField = (): HTMLInputElement =>
        host().querySelector<HTMLInputElement>('app-conversation-list-toolbar input')!;
    const toolbarButton = (label: string): HTMLButtonElement | undefined =>
        Array.from(host().querySelectorAll<HTMLButtonElement>('app-conversation-list-toolbar button')).find(
            (button) => button.textContent?.trim() === label
        );
    const sectionLabels = (): string[] => text('.conversation-section-header__label');
    // Remembered per browser, and as the column shows them.
    const collapsedSections = (): string[] => [...TestBed.inject(ConversationListPreferencesService).collapsed()];
    const expandedSections = (): string[] =>
        store()
            .view()
            .filter(({ isExpanded }) => isExpanded)
            .map(({ section }) => section.id);
    const sentParams = (): ConversationListParams[] => chatApi.getConversations.mock.calls.map(([params]) => params);

    /** Types into the search field as a user would; the column searches once typing settles. */
    function typeSearch(value: string): void {
        const field = searchField();
        field.value = value;
        field.dispatchEvent(new Event('input'));
        fixture.detectChanges();
    }

    /** Typing settles (fake timers): the search goes out. */
    function settle(): void {
        vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS);
        fixture.detectChanges();
    }

    function click(button: HTMLButtonElement | undefined): void {
        button!.click();
        fixture.detectChanges();
    }

    function text(selector: string): string[] {
        return Array.from(host().querySelectorAll(selector)).map(
            (node) => node.textContent?.replace(/\s+/g, ' ').trim() ?? ''
        );
    }

    interface SectionPages {
        waiting?: Observable<ChatConversationPage>;
        inProgress?: Observable<ChatConversationPage>;
        // Only for a load that lists Closed: a search opens it.
        closed?: Observable<ChatConversationPage>;
        bot?: Observable<ChatConversationPage>;
    }

    /**
     * The next load answers the open sections in column order: Waiting, In progress, Closed when given, Bot (Tests and
     * Closed start collapsed).
     */
    function answerNextLoad(pages: SectionPages): void {
        chatApi.getConversations
            .mockReturnValueOnce(pages.waiting ?? page([]))
            .mockReturnValueOnce(pages.inProgress ?? page([]));
        if (pages.closed) chatApi.getConversations.mockReturnValueOnce(pages.closed);
        chatApi.getConversations.mockReturnValueOnce(pages.bot ?? page([]));
    }

    /** As `answerNextLoad`, for a search: it opens Closed, which answers nothing unless given. */
    function answerNextSearch(pages: SectionPages): void {
        answerNextLoad({ closed: page([]), ...pages });
    }

    function reloadWith(pages: SectionPages): void {
        answerNextLoad(pages);
        readyEpoch.update((value) => value + 1);
        fixture.detectChanges();
    }

    /** The desk listed, as the page passes it; '' lists every desk. */
    function scopeTo(bindingId: string): void {
        fixture.componentRef.setInput('bindingId', bindingId || null);
        fixture.detectChanges();
    }

    function select(id: string | null): void {
        fixture.componentRef.setInput('selectedId', id);
        fixture.detectChanges();
    }

    function listDesks(desks: ChatBinding[]): void {
        serverDesks = desks;
        TestBed.inject(ChatDesksStorageService).reload();
    }

    function toggle(label: string): void {
        headerButton(label).click();
        fixture.detectChanges();
    }

    function scrollToEndOf(section: ChatInboxSection): void {
        IntersectionObserverStub.scrollIntoView(section);
        fixture.detectChanges();
    }

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        vi.stubGlobal('IntersectionObserver', IntersectionObserverStub);
        IntersectionObserverStub.instances = [];
        vi.clearAllMocks();
        localStorage.clear();
        serverDesks = [];
        waitingCount.set(0);
        TestBed.configureTestingModule({
            imports: [ConversationListComponent],
            providers: [
                { provide: ChatApiService, useValue: chatApi },
                { provide: ChatInboxStreamService, useValue: chatInboxStream },
                { provide: PermissionsService, useValue: permissions },
                { provide: ConfirmationDialogService, useValue: { confirm: vi.fn() } },
                { provide: ToastService, useValue: { error: vi.fn() } },
                { provide: ProfileService, useValue: { currentUserSignal: signal({ id: 3 }) } },
            ],
        });
        TestBed.inject(ActiveOrgService).set(1);
        fixture = TestBed.createComponent(ConversationListComponent);
        fixture.detectChanges();
    });

    afterEach(() => {
        vi.useRealTimers();
        vi.restoreAllMocks();
        vi.unstubAllGlobals();
        localStorage.clear();
    });

    describe('one scroll with sections', () => {
        it('scrolls as one: a single scroll container holds every section, none scrolls on its own', () => {
            const scrollers = host().querySelectorAll('.conversation-list__scroller');
            expect(scrollers.length).toBe(1);
            const sections = Array.from(host().querySelectorAll('.conversation-list__section'));
            expect(sections.every((section) => section.parentElement === scrollers[0])).toBe(true);
            const scrolling = Array.from(host().querySelectorAll('*')).filter((element) =>
                ['auto', 'scroll'].includes(getComputedStyle(element).overflowY)
            );
            expect(scrolling).toEqual([scrollers[0]]);
        });

        it('lists Waiting for a person, In progress, Tests, Closed and Bot in that order, Tests and Closed collapsed', () => {
            expect(text('.conversation-section-header__label')).toEqual([
                'Waiting for a person',
                'In progress',
                'Tests',
                'Closed',
                'Bot',
            ]);
            expect(
                Array.from(host().querySelectorAll('.conversation-section-header')).map((button) =>
                    button.getAttribute('aria-expanded')
                )
            ).toEqual(['true', 'true', 'false', 'false', 'true']);
        });

        it('gives each section a sticky header heading the section it collapses', () => {
            for (const section of Array.from(host().querySelectorAll<HTMLElement>('.conversation-list__section'))) {
                const header = section.firstElementChild as HTMLElement;
                expect(header.tagName.toLowerCase()).toBe('app-conversation-section-header');
                expect(getComputedStyle(header).position).toBe('sticky');
                expect(header.getAttribute('role')).toBe('heading');
                const button = header.querySelector('button')!;
                const body = document.getElementById(button.getAttribute('aria-controls')!);
                expect(body?.parentElement).toBe(section);
                expect(body?.hidden).toBe(button.getAttribute('aria-expanded') === 'false');
            }
        });

        it('counts Waiting only, from the stream, for the desk shown; the other sections have no count', () => {
            waitingCount.set(3);
            scopeTo('b-2');
            const counts = Array.from(host().querySelectorAll('.conversation-section-header')).map(
                (button) => button.querySelector('.conversation-section-header__count')?.textContent?.trim() ?? null
            );
            expect(counts).toEqual(['3', null, null, null, null]);
            expect(chatInboxStream.waitingCountFor).toHaveBeenLastCalledWith('b-2', null);

            waitingCount.set(4);
            fixture.detectChanges();
            expect(text('.conversation-section-header__count')).toEqual(['4']);
        });

        it('requests the open sections only, and reloads them on every stream ready', () => {
            expect(requestedSections()).toEqual(['waiting', 'in_progress', 'bot']);
            readyEpoch.update((value) => value + 1);
            fixture.detectChanges();
            expect(requestedSections()).toEqual(['waiting', 'in_progress', 'bot', 'waiting', 'in_progress', 'bot']);
        });

        it('says once that everything is empty, instead of once per section', () => {
            reloadWith({});
            expect(text('.conversation-list__everything-empty .conversation-list__empty-title')).toEqual([
                'No conversations yet',
            ]);
            expect(host().querySelector('.conversation-list__section-empty')).toBeNull();
            // The collapsed Tests header stays, so it can still be opened.
            expect(headerButton('Tests')).toBeDefined();
        });

        it('says per section what an empty one is for while another has rows', () => {
            expect(text('.conversation-list__section-empty .conversation-list__empty-title')).toEqual([
                'Nobody is waiting',
                'Nothing in progress',
            ]);
            expect(host().querySelector('.conversation-list__everything-empty')).toBeNull();
        });
    });

    describe('collapsing', () => {
        it('collapses and expands a section from its header, and remembers it per browser', () => {
            toggle('Bot');
            expect(headerButton('Bot').getAttribute('aria-expanded')).toBe('false');
            expect(rowButtons()).toEqual([]);
            expect(JSON.parse(localStorage.getItem(PREFERENCES_KEY)!)).toMatchObject({
                collapsed: ['test', 'closed', 'bot'],
            });

            fixture = TestBed.createComponent(ConversationListComponent);
            fixture.detectChanges();
            expect(headerButton('Bot').getAttribute('aria-expanded')).toBe('false');

            toggle('Bot');
            expect(headerButton('Bot').getAttribute('aria-expanded')).toBe('true');
            expect(JSON.parse(localStorage.getItem(PREFERENCES_KEY)!)).toMatchObject({ collapsed: ['test', 'closed'] });
        });

        it('never requests a collapsed section, and loads it when it is opened', () => {
            expect(requestedSections()).not.toContain('test');

            toggle('Bot');
            readyEpoch.update((value) => value + 1);
            fixture.detectChanges();
            expect(requestedSections()).toEqual(['waiting', 'in_progress', 'bot', 'waiting', 'in_progress']);

            chatApi.getConversations.mockReturnValueOnce(page([row({ id: 't-1', is_test: true })]));
            toggle('Tests');
            expect(chatApi.getConversations).toHaveBeenLastCalledWith(listParams('test'));
            expect(ids('test')).toEqual(['t-1']);
        });

        it('does not request a collapsed section again when it is opened twice for the same desk', () => {
            toggle('Tests');
            toggle('Tests');
            toggle('Tests');
            expect(requestedSections().filter((section) => section === 'test')).toHaveLength(1);
        });

        it('keeps working when the browser refuses storage', () => {
            // Refused for the column's own key only: the rest of the app has its own storage handling.
            const { getItem, setItem } = Storage.prototype;
            vi.spyOn(Storage.prototype, 'getItem').mockImplementation(function (this: Storage, key: string) {
                if (key === PREFERENCES_KEY) throw new Error('denied');
                return getItem.call(this, key);
            });
            vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function (
                this: Storage,
                key: string,
                value: string
            ) {
                if (key === PREFERENCES_KEY) throw new Error('denied');
                setItem.call(this, key, value);
            });
            TestBed.resetTestingModule();
            TestBed.configureTestingModule({
                imports: [ConversationListComponent],
                providers: [
                    { provide: ChatApiService, useValue: chatApi },
                    { provide: ChatInboxStreamService, useValue: chatInboxStream },
                    { provide: PermissionsService, useValue: permissions },
                    { provide: ConfirmationDialogService, useValue: { confirm: vi.fn() } },
                    { provide: ToastService, useValue: { error: vi.fn() } },
                    { provide: ProfileService, useValue: { currentUserSignal: signal({ id: 3 }) } },
                ],
            });
            TestBed.inject(ActiveOrgService).set(1);
            fixture = TestBed.createComponent(ConversationListComponent);
            fixture.detectChanges();
            expect(headerButton('Tests').getAttribute('aria-expanded')).toBe('false');

            toggle('Tests');
            expect(headerButton('Tests').getAttribute('aria-expanded')).toBe('true');
        });

        describe('collapsing from a stuck header', () => {
            let scroller: HTMLElement;
            let botSection: HTMLElement;

            /** The column is scrolled 500px down; the Bot section starts at `sectionTopOnScreen` (the scroller's top is 100). */
            function scrolledWithBotAt(sectionTopOnScreen: number): void {
                scroller = host().querySelector<HTMLElement>('.conversation-list__scroller')!;
                botSection = host().querySelector<HTMLElement>('.conversation-list__section[data-section="bot"]')!;
                Object.defineProperty(scroller, 'scrollTop', { value: 500, writable: true, configurable: true });
                scroller.getBoundingClientRect = () => ({ top: 100 }) as DOMRect;
                botSection.getBoundingClientRect = () => ({ top: sectionTopOnScreen }) as DOMRect;
            }

            it('scrolls back to the section so the collapsed header stays where it was pressed', async () => {
                // Deep inside Bot: its header is stuck and the section began 300px above the view.
                scrolledWithBotAt(-200);
                toggle('Bot');
                await fixture.whenStable();
                expect(headerButton('Bot').getAttribute('aria-expanded')).toBe('false');
                expect(scroller.scrollTop).toBe(200);
            });

            it('leaves the scroll alone when the section starts in view, and when a section opens', async () => {
                scrolledWithBotAt(150);
                toggle('Bot');
                await fixture.whenStable();
                expect(scroller.scrollTop).toBe(500);

                scrolledWithBotAt(-200);
                toggle('Bot');
                await fixture.whenStable();
                expect(headerButton('Bot').getAttribute('aria-expanded')).toBe('true');
                expect(scroller.scrollTop).toBe(500);
            });
        });

        it('opens Tests and scrolls it to the top when a test conversation starts', async () => {
            const scrolled: Element[] = [];
            Element.prototype.scrollIntoView = vi.fn(function (this: Element) {
                scrolled.push(this);
            });
            try {
                fixture.componentInstance.reveal('test');
                fixture.detectChanges();
                await fixture.whenStable();

                expect(headerButton('Tests').getAttribute('aria-expanded')).toBe('true');
                expect(chatApi.getConversations).toHaveBeenLastCalledWith(listParams('test'));
                expect(scrolled.map((element) => (element as HTMLElement).dataset['section'])).toEqual(['test']);
                expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith({ block: 'start' });
            } finally {
                delete (Element.prototype as Partial<Element>).scrollIntoView;
            }
        });
    });

    describe('paging as the column scrolls', () => {
        it("loads a section's next page when its end scrolls into view, one request at a time", () => {
            reloadWith({
                waiting: page([handedOff('h-1', '2026-10-10T08:00:00Z')], 'waiting-2'),
                bot: page([row({ id: 'c-1' })], 'bot-2'),
            });
            expect(sentinels()).toEqual(['waiting', 'bot']);
            expect(IntersectionObserverStub.instances.at(-1)?.options?.root).toBe(
                host().querySelector('.conversation-list__scroller')
            );

            const more$ = new Subject<ChatConversationPage>();
            chatApi.getConversations.mockReturnValueOnce(more$);
            scrollToEndOf('bot');
            expect(chatApi.getConversations).toHaveBeenLastCalledWith(listParams('bot', { cursor: 'bot-2' }));
            // While it loads, its end is not watched: scrolling there again sends nothing.
            expect(sentinels()).toEqual(['waiting']);
            const calls = chatApi.getConversations.mock.calls.length;
            scrollToEndOf('bot');
            expect(chatApi.getConversations.mock.calls.length).toBe(calls);

            more$.next({
                results: [row({ id: 'c-2', last_message_at: '2026-10-10T09:00:00Z' })],
                next_cursor: 'bot-3',
            });
            fixture.detectChanges();
            expect(ids('bot')).toEqual(['c-1', 'c-2']);
            expect(sentinels()).toEqual(['waiting', 'bot']);

            chatApi.getConversations.mockReturnValueOnce(page([]));
            scrollToEndOf('bot');
            expect(chatApi.getConversations).toHaveBeenLastCalledWith(listParams('bot', { cursor: 'bot-3' }));
            expect(sentinels()).toEqual(['waiting']);
        });

        it('pages Tests with the Tests cursor once Tests is open, and never a collapsed section', () => {
            chatApi.getConversations.mockReturnValueOnce(page([row({ id: 't-1', is_test: true })], 'test-2'));
            toggle('Tests');
            expect(sentinels()).toEqual(['test']);

            chatApi.getConversations.mockReturnValueOnce(page([]));
            scrollToEndOf('test');
            expect(chatApi.getConversations).toHaveBeenLastCalledWith(listParams('test', { cursor: 'test-2' }));

            toggle('Tests');
            reloadWith({ bot: page([row({ id: 'c-1' })], 'bot-2') });
            toggle('Bot');
            expect(sentinels()).not.toContain('bot');
            const calls = chatApi.getConversations.mock.calls.length;
            store().loadMore('bot');
            expect(chatApi.getConversations.mock.calls.length).toBe(calls);
        });

        it('drops a live wait past the Waiting boundary and lists it when the next page reaches it', () => {
            reloadWith({ waiting: page([handedOff('h-1', '2026-10-10T08:00:00Z')], 'waiting-2') });

            conversationUpdated$.next(handedOff('c-5', '2026-10-10T11:00:00Z'));
            expect(ids('waiting')).toEqual(['h-1']);

            chatApi.getConversations.mockReturnValueOnce(
                page([handedOff('h-2', '2026-10-10T09:00:00Z'), handedOff('c-5', '2026-10-10T11:00:00Z')])
            );
            scrollToEndOf('waiting');
            expect(ids('waiting')).toEqual(['h-1', 'h-2', 'c-5']);
        });

        it('keeps a wait that starts while the next page is in flight', () => {
            reloadWith({ waiting: page([handedOff('h-1', '2026-10-10T08:00:00Z')], 'waiting-2') });
            const more$ = new Subject<ChatConversationPage>();
            chatApi.getConversations.mockReturnValueOnce(more$);
            store().loadMore('waiting');

            conversationUpdated$.next(handedOff('c-5', '2026-10-10T11:00:00Z'));
            more$.next({ results: [handedOff('h-2', '2026-10-10T09:00:00Z')], next_cursor: null });

            expect(ids('waiting')).toEqual(['h-1', 'h-2', 'c-5']);
        });

        it('lists a row returned by two pages once, the later page winning', () => {
            reloadWith({
                bot: page(
                    [
                        row({ id: 'c-1', last_message_preview: 'first copy' }),
                        row({ id: 'c-2', last_message_at: '2026-10-10T09:00:00Z', last_message_preview: 'older' }),
                    ],
                    'cursor-2'
                ),
            });

            chatApi.getConversations.mockReturnValueOnce(
                page([
                    row({ id: 'c-1', last_message_preview: 'later copy' }),
                    row({ id: 'c-3', last_message_at: '2026-10-10T08:00:00Z', last_message_preview: 'oldest' }),
                ])
            );
            scrollToEndOf('bot');

            expect(chatApi.getConversations).toHaveBeenLastCalledWith(listParams('bot', { cursor: 'cursor-2' }));
            expect(text('.conversation-row__preview')).toEqual(['later copy', 'older', 'oldest']);
            expect(store().sections().bot.nextCursor).toBeNull();
            expect(sentinels()).toEqual([]);
        });

        it('keeps a row streamed after the reload when the next page brings an older copy', () => {
            reloadWith({ bot: page([row({ id: 'c-1', last_message_preview: 'hello' })], 'cursor-2') });

            conversationUpdated$.next(
                row({ id: 'c-2', last_message_at: '2026-10-10T12:00:00Z', last_message_preview: 'live' })
            );
            chatApi.getConversations.mockReturnValueOnce(
                page([row({ id: 'c-2', last_message_at: '2026-10-10T08:00:00Z', last_message_preview: 'stale' })])
            );
            store().loadMore('bot');
            fixture.detectChanges();

            expect(text('.conversation-row__preview')).toEqual(['live', 'hello']);
        });
    });

    describe('live rows', () => {
        it('moves a bot conversation that is handed off to the end of the Waiting queue', () => {
            reloadWith({
                waiting: page([handedOff('h-1', '2026-10-10T08:00:00Z'), handedOff('h-2', '2026-10-10T09:00:00Z')]),
                bot: page([row({ id: 'c-1' })]),
            });

            conversationUpdated$.next(handedOff('c-1', '2026-10-10T11:00:00Z'));

            expect(ids('bot')).toEqual([]);
            expect(ids('waiting')).toEqual(['h-1', 'h-2', 'c-1']);
        });

        it('keeps a waiting conversation in its place in the queue when the visitor writes again', () => {
            reloadWith({
                waiting: page([handedOff('h-1', '2026-10-10T08:00:00Z'), handedOff('h-2', '2026-10-10T09:00:00Z')]),
            });

            conversationUpdated$.next(
                handedOff('h-1', '2026-10-10T08:00:00Z', { mode: 'human', last_message_at: '2026-10-10T12:00:00Z' })
            );

            expect(ids('waiting')).toEqual(['h-1', 'h-2']);
        });

        it('moves a conversation to In progress when an operator answers, and back to Waiting when the visitor writes', () => {
            reloadWith({
                waiting: page([handedOff('h-1', '2026-10-10T08:00:00Z')]),
                inProgress: page([answered('p-1', '2026-10-10T09:00:00Z')]),
            });

            conversationUpdated$.next(answered('h-1', '2026-10-10T12:00:00Z'));
            expect(ids('waiting')).toEqual([]);
            expect(ids('in_progress')).toEqual(['h-1', 'p-1']);

            conversationUpdated$.next(
                answered('h-1', '2026-10-10T12:05:00Z', { visitor_waiting_since: '2026-10-10T12:05:00Z' })
            );
            expect(ids('waiting')).toEqual(['h-1']);
            expect(ids('in_progress')).toEqual(['p-1']);
        });

        it('keeps a live test conversation in Tests whatever its mode or wait', () => {
            for (const mode of ['bot', 'awaiting_human', 'human'] as const) {
                const waitingSince = mode === 'bot' ? null : '2026-10-10T10:00:00Z';
                conversationUpdated$.next(
                    row({
                        id: 't-1',
                        is_test: true,
                        mode,
                        handoff_at: waitingSince,
                        visitor_waiting_since: waitingSince,
                    })
                );
                expect(ids('test')).toEqual(['t-1']);
                expect(ids('waiting')).toEqual([]);
                expect(ids('bot')).toEqual(['c-1']);
            }
        });

        it('moves a released conversation from In progress to Bot', () => {
            reloadWith({
                inProgress: page([answered('h-1', '2026-10-10T08:00:00Z')]),
                bot: page([row({ id: 'c-1' })]),
            });

            conversationUpdated$.next(row({ id: 'h-1', last_message_at: '2026-10-10T12:00:00Z' }));

            expect(ids('in_progress')).toEqual([]);
            expect(ids('bot')).toEqual(['h-1', 'c-1']);
        });

        it('keeps the open conversation marked when it moves to another section', () => {
            select('c-1');

            conversationUpdated$.next(handedOff('c-1', '2026-10-10T11:00:00Z'));
            fixture.detectChanges();

            expect(ids('waiting')).toEqual(['c-1']);
            const marked = rowButtons().filter((button) => button.getAttribute('aria-current') === 'true');
            expect(marked.length).toBe(1);
            expect(
                marked[0].closest('.conversation-list__section')?.querySelector('.conversation-section-header__label')
                    ?.textContent
            ).toContain('Waiting for a person');
        });

        it('lists only conversations of the desk shown', () => {
            scopeTo('b-2');
            conversationUpdated$.next(row({ id: 'c-9', binding_id: 'b-1' }));
            expect(ids('bot')).not.toContain('c-9');
        });

        it('does not list a streamed conversation without messages until its first message', () => {
            toggle('Tests');
            const created = row({ id: 'c-9', is_test: true, last_message_at: null, last_message_preview: '' });
            conversationUpdated$.next({ ...created, state: 'processing' });
            fixture.detectChanges();
            expect(ids('test')).toEqual([]);

            conversationUpdated$.next(
                row({
                    id: 'c-9',
                    is_test: true,
                    last_message_at: '2026-10-10T11:00:00Z',
                    last_message_preview: 'first',
                })
            );
            fixture.detectChanges();
            expect(ids('test')).toEqual(['c-9']);
        });

        it('keeps the rows shown while a reconnect reload is in flight, then merges streamed and fetched rows', () => {
            const page$ = new Subject<ChatConversationPage>();
            reloadWith({ bot: page$ });
            expect(text('.conversation-row__preview')).toEqual(['hello']);

            conversationUpdated$.next(
                row({ id: 'c-7', last_message_at: '2026-10-10T11:00:00Z', last_message_preview: 'live' })
            );
            page$.next({
                next_cursor: null,
                results: [
                    row({ id: 'c-5', last_message_preview: 'fresh' }),
                    row({ id: 'c-7', last_message_at: '2026-10-10T09:00:00Z', last_message_preview: 'stale' }),
                ],
            });
            fixture.detectChanges();
            expect(text('.conversation-row__preview')).toEqual(['live', 'fresh']);
        });

        it('keeps every row of a page whose timestamps differ only in microseconds', () => {
            // Newest first by microsecond; millisecond precision would tie them and reorder by id.
            reloadWith({
                bot: page(
                    [
                        row({ id: 'c-a', last_message_at: '2026-10-10T10:00:00.123456Z' }),
                        row({ id: 'c-b', last_message_at: '2026-10-10T10:00:00.123400Z' }),
                    ],
                    'bot-2'
                ),
            });
            expect(ids('bot')).toEqual(['c-a', 'c-b']);
        });

        it('cancels a page still in flight when the desk changes', () => {
            const stale$ = new Subject<ChatConversationPage>();
            reloadWith({ bot: stale$ });
            expect(stale$.observed).toBe(true);

            scopeTo('b-2');

            expect(stale$.observed).toBe(false);
            stale$.next({ results: [row({ id: 'c-stale' })], next_cursor: null });
            expect(ids('bot')).toEqual(['c-1']);
        });

        it('reloads every open section when the desk changes, and forgets what a collapsed one had loaded', () => {
            toggle('Tests');
            chatApi.getConversations.mockClear();
            scopeTo('b-2');
            expect(chatApi.getConversations.mock.calls.map(([params]) => params)).toEqual([
                listParams('waiting', { binding: 'b-2' }),
                listParams('in_progress', { binding: 'b-2' }),
                listParams('test', { binding: 'b-2' }),
                listParams('bot', { binding: 'b-2' }),
            ]);

            toggle('Tests');
            chatApi.getConversations.mockClear();
            scopeTo('b-3');
            expect(requestedSections()).toEqual(['waiting', 'in_progress', 'bot']);
            toggle('Tests');
            expect(chatApi.getConversations).toHaveBeenLastCalledWith(listParams('test', { binding: 'b-3' }));
        });
    });

    describe('Closed', () => {
        const closedRow = (id: string, closedAt: string, overrides: Partial<ChatConversation> = {}): ChatConversation =>
            row({
                id,
                status: 'closed',
                close_reason: 'resolved',
                closed_at: closedAt,
                closed_by_user_id: 7,
                last_message_preview: id,
                ...overrides,
            });
        const closedSection = (selector: string): Element | null =>
            host().querySelector(`.conversation-list__section[data-section="closed"] ${selector}`);

        it('loads Closed once opened, most recently closed first whatever the sort, without a count', () => {
            expect(requestedSections()).not.toContain('closed');
            chatApi.getConversations.mockReturnValueOnce(
                page([closedRow('x-2', '2026-10-10T12:00:00Z'), closedRow('x-1', '2026-10-10T11:00:00Z')])
            );
            toggle('Closed');
            expect(chatApi.getConversations).toHaveBeenLastCalledWith(listParams('closed'));
            expect(ids('closed')).toEqual(['x-2', 'x-1']);
            expect(closedSection('.conversation-list__section-note')?.textContent?.trim()).toBe(
                'Most recently closed first'
            );
            expect(closedSection('.conversation-section-header__count')).toBeNull();

            answerNextLoad({
                closed: page([closedRow('x-2', '2026-10-10T12:00:00Z'), closedRow('x-1', '2026-10-10T11:00:00Z')]),
            });
            click(toolbarButton('Newest first'));
            expect(sentParams().at(-2)).toEqual(listParams('closed', { order: 'oldest' }));
            conversationUpdated$.next(closedRow('x-3', '2026-10-10T13:00:00Z'));
            expect(ids('closed')).toEqual(['x-3', 'x-2', 'x-1']);
        });

        it('takes a conversation a live close ends out of its section: into Closed when open, out of sight when not', () => {
            reloadWith({
                inProgress: page([answered('p-1', '2026-10-10T09:00:00Z'), answered('p-2', '2026-10-10T08:00:00Z')]),
            });
            conversationUpdated$.next(
                closedRow('p-1', '2026-10-10T12:00:00Z', { mode: 'human', assigned_operator_id: 7 })
            );
            fixture.detectChanges();
            expect(ids('in_progress')).toEqual(['p-2']);
            expect(host().querySelector('[data-id="p-1"]')).toBeNull();

            // Opened later, Closed lists it even before the server's page has it.
            chatApi.getConversations.mockReturnValueOnce(page([]));
            toggle('Closed');
            expect(ids('closed')).toEqual(['p-1']);

            conversationUpdated$.next(
                closedRow('p-2', '2026-10-10T13:00:00Z', { mode: 'human', assigned_operator_id: 7 })
            );
            fixture.detectChanges();
            expect(ids('in_progress')).toEqual([]);
            expect(closedSection('[data-id="p-2"]')).not.toBeNull();
            expect(ids('closed')).toEqual(['p-2', 'p-1']);
        });

        it('keeps closed tests in Tests, never in Closed', () => {
            toggle('Tests');
            chatApi.getConversations.mockReturnValueOnce(page([]));
            toggle('Closed');
            conversationUpdated$.next(closedRow('t-1', '2026-10-10T12:00:00Z', { is_test: true }));
            fixture.detectChanges();
            expect(ids('test')).toEqual(['t-1']);
            expect(ids('closed')).toEqual([]);
        });

        it('is hidden under Mine, closed conversations of the user included', () => {
            chatApi.getConversations.mockReturnValueOnce(page([])).mockReturnValueOnce(page([]));
            click(toolbarButton('Mine'));
            expect(sectionLabels()).toEqual(['Waiting for a person', 'In progress']);
            expect(requestedSections()).not.toContain('closed');
            conversationUpdated$.next(closedRow('x-1', '2026-10-10T12:00:00Z', { assigned_operator_id: 3 }));
            expect(ids('closed')).toEqual([]);
        });

        describe('while searching', () => {
            beforeEach(() => vi.useFakeTimers());

            it('opens for a search in this column only, stays open as the search changes, and folds back once cleared', () => {
                const remembered = localStorage.getItem(PREFERENCES_KEY);
                answerNextSearch({ closed: page([closedRow('x-1', '2026-10-10T12:00:00Z')]) });
                typeSearch('12');
                settle();
                expect(expandedSections()).toContain('closed');
                expect(sentParams()).toContainEqual(listParams('closed', { q: '12' }));
                expect(ids('closed')).toEqual(['x-1']);
                expect(collapsedSections()).toEqual(['test', 'closed']);
                expect(localStorage.getItem(PREFERENCES_KEY)).toBe(remembered);

                answerNextSearch({});
                typeSearch('123');
                settle();
                expect(expandedSections()).toContain('closed');

                chatApi.getConversations.mockClear();
                typeSearch('');
                expect(expandedSections()).not.toContain('closed');
                expect(requestedSections()).toEqual(['waiting', 'in_progress', 'bot']);
                expect(localStorage.getItem(PREFERENCES_KEY)).toBe(remembered);
            });

            it("keeps the user's own toggle of Closed during a search once it is cleared", () => {
                answerNextSearch({});
                typeSearch('12');
                settle();
                toggle('Closed');
                expect(expandedSections()).not.toContain('closed');

                // Collapsed by the user: typing on does not open it again.
                answerNextLoad({});
                typeSearch('123');
                settle();
                expect(expandedSections()).not.toContain('closed');

                chatApi.getConversations.mockReturnValueOnce(page([]));
                toggle('Closed');
                typeSearch('');
                expect(expandedSections()).toContain('closed');
                expect(collapsedSections()).toEqual(['test']);
            });

            it('leaves a Closed the user keeps open as it is', () => {
                chatApi.getConversations.mockReturnValueOnce(page([]));
                toggle('Closed');
                answerNextSearch({});
                typeSearch('12');
                settle();
                typeSearch('');
                expect(expandedSections()).toContain('closed');
            });
        });
    });

    describe('overdue', () => {
        it("marks a wait overdue by its own desk's rule", () => {
            listDesks([
                { ...desk, on_response_timeout: 'overdue', response_time_seconds: 60 },
                { ...desk, id: 'b-2', name: 'Sales', on_response_timeout: 'handback', response_time_seconds: 60 },
            ]);
            reloadWith({
                waiting: page([
                    handedOff('h-1', '2026-10-10T08:00:00Z'),
                    handedOff('h-2', '2026-10-10T09:00:00Z', { binding_id: 'b-2' }),
                ]),
            });
            const overdue = Array.from(host().querySelectorAll('.conversation-row__waiting--overdue')).map((mark) =>
                mark.closest('[data-id]')?.getAttribute('data-id')
            );
            expect(overdue).toEqual(['h-1']);
        });
    });

    describe('search, Mine and sort', () => {
        beforeEach(() => vi.useFakeTimers());

        it('searches every loaded section once typing settles, each from its start', () => {
            chatApi.getConversations.mockClear();
            typeSearch('  Ada ');
            vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS - 1);
            fixture.detectChanges();
            expect(chatApi.getConversations).not.toHaveBeenCalled();

            vi.advanceTimersByTime(1);
            fixture.detectChanges();
            // Tests is collapsed: it is searched once opened. A search opens Closed.
            expect(sentParams()).toEqual([
                listParams('waiting', { q: 'Ada' }),
                listParams('in_progress', { q: 'Ada' }),
                listParams('closed', { q: 'Ada' }),
                listParams('bot', { q: 'Ada' }),
            ]);
        });

        it('does not search again for the same words, and lists without searching at once when cleared', () => {
            typeSearch('ada');
            settle();
            chatApi.getConversations.mockClear();

            typeSearch('ada ');
            settle();
            expect(chatApi.getConversations).not.toHaveBeenCalled();

            typeSearch('');
            expect(sentParams().map(({ q }) => q)).toEqual(['', '', '']);
        });

        it('clears with Escape and with the clear button at once, keeping the focus in the field', async () => {
            typeSearch('ada');
            settle();
            chatApi.getConversations.mockClear();

            searchField().dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
            fixture.detectChanges();
            await Promise.resolve();
            expect(searchField().value).toBe('');
            expect(sentParams().map(({ q }) => q)).toEqual(['', '', '']);

            typeSearch('ada');
            settle();
            chatApi.getConversations.mockClear();
            click(host().querySelector<HTMLButtonElement>('.search__clear-btn')!);
            expect(sentParams().map(({ q }) => q)).toEqual(['', '', '']);
            expect(document.activeElement).toBe(searchField());
        });

        it('names the field for screen readers', () => {
            expect(searchField().getAttribute('aria-label')).toBe('Search conversations');
        });

        it('hides the Waiting count while searching: the stream cannot tell what the search matches', () => {
            waitingCount.set(2);
            fixture.detectChanges();
            expect(text('.conversation-section-header__count')).toEqual(['2']);

            typeSearch('ada');
            settle();
            expect(text('.conversation-section-header__count')).toEqual([]);

            typeSearch('');
            expect(text('.conversation-section-header__count')).toEqual(['2']);
        });

        /** A search for "anna" found h-1 waiting, p-1 that Anna has in progress, and c-1 the bot runs. */
        function searchAnna(): void {
            answerNextSearch({
                waiting: page([handedOff('h-1', '2026-10-10T08:00:00Z')]),
                inProgress: page([answered('p-1', '2026-10-10T09:00:00Z')]),
                bot: page([row({ id: 'c-1' })]),
            });
            typeSearch('anna');
            settle();
            expect(ids('waiting')).toEqual(['h-1']);
            expect(ids('in_progress')).toEqual(['p-1']);
            expect(ids('bot')).toEqual(['c-1']);
        }

        it('updates a row the search found in place while it keeps its section and holder', () => {
            searchAnna();
            conversationUpdated$.next(row({ id: 'c-1', last_message_preview: 'updated' }));
            conversationUpdated$.next(answered('p-1', '2026-10-10T12:00:00Z', { last_message_preview: 'answered' }));
            expect(ids('bot')).toEqual(['c-1']);
            expect(ids('in_progress')).toEqual(['p-1']);
            expect(store().findRow('c-1')?.last_message_preview).toBe('updated');
            expect(store().findRow('p-1')?.last_message_preview).toBe('answered');
        });

        it('removes a row the search found once it changes section: the search may not match it there', () => {
            searchAnna();
            // Released to the bot: Anna's name matched it in In progress, it would not in Bot.
            conversationUpdated$.next(row({ id: 'p-1', last_message_at: '2026-10-10T12:00:00Z' }));
            // Handed off: no longer the bot's.
            conversationUpdated$.next(handedOff('c-1', '2026-10-10T11:00:00Z'));
            expect(ids('in_progress')).toEqual([]);
            expect(ids('bot')).toEqual([]);
            expect(ids('waiting')).toEqual(['h-1']);
        });

        it('removes a row the search found once another operator holds it, in the same section', () => {
            searchAnna();
            // Bob takes the waiting conversation over: it still waits, but no longer for whoever the search matched.
            conversationUpdated$.next(
                handedOff('h-1', '2026-10-10T08:00:00Z', { mode: 'human', assigned_operator_id: 9 })
            );
            conversationUpdated$.next(answered('p-1', '2026-10-10T12:00:00Z', { assigned_operator_id: 9 }));
            expect(ids('waiting')).toEqual([]);
            expect(ids('in_progress')).toEqual([]);
        });

        it('never adds a row live while searching; a removed row comes back with the next search load', () => {
            searchAnna();
            conversationUpdated$.next(row({ id: 'c-9', last_message_at: '2026-10-10T12:00:00Z' }));
            conversationUpdated$.next(handedOff('c-8', '2026-10-10T12:00:00Z'));
            conversationUpdated$.next(row({ id: 'p-1', last_message_at: '2026-10-10T12:00:00Z' }));
            expect(ids('bot')).toEqual(['c-1']);
            expect(ids('waiting')).toEqual(['h-1']);
            expect(ids('in_progress')).toEqual([]);

            // The server still matches the released conversation in Bot, so the next load lists it there.
            reloadWith({
                closed: page([]),
                waiting: page([handedOff('h-1', '2026-10-10T08:00:00Z')]),
                bot: page([row({ id: 'p-1', last_message_at: '2026-10-10T12:00:00Z' }), row({ id: 'c-1' })]),
            });
            expect(ids('bot')).toEqual(['p-1', 'c-1']);

            // Without a search, a live row joins its section again.
            typeSearch('');
            conversationUpdated$.next(row({ id: 'c-9', last_message_at: '2026-10-10T13:00:00Z' }));
            expect(ids('bot')).toEqual(['c-9', 'c-1']);
        });

        it('keeps a row streamed while the search loads only when the search found it', () => {
            const waiting$ = new Subject<ChatConversationPage>();
            answerNextSearch({ waiting: waiting$ });
            typeSearch('ada');
            settle();

            conversationUpdated$.next(handedOff('c-7', '2026-10-10T11:00:00Z'));
            conversationUpdated$.next(handedOff('h-2', '2026-10-10T09:00:00Z', { last_message_preview: 'live' }));
            // Taken over by Bob before the page landed: the page's copy is the one the search matched.
            conversationUpdated$.next(
                handedOff('h-3', '2026-10-10T10:00:00Z', { mode: 'human', assigned_operator_id: 9 })
            );
            waiting$.next({
                results: [
                    handedOff('h-1', '2026-10-10T08:00:00Z'),
                    handedOff('h-2', '2026-10-10T09:00:00Z', { last_message_preview: 'stale' }),
                    handedOff('h-3', '2026-10-10T10:00:00Z'),
                ],
                next_cursor: null,
            });
            fixture.detectChanges();

            // c-7 was never matched; h-2 kept its place and holder, so its newer copy wins; h-3 changed holder.
            expect(ids('waiting')).toEqual(['h-1', 'h-2']);
            expect(store().findRow('h-2')?.last_message_preview).toBe('live');
        });

        it('says when nothing matches, once for the column or per section beside matches', () => {
            answerNextSearch({});
            typeSearch('zzz');
            settle();
            expect(text('.conversation-list__everything-empty .conversation-list__empty-title')).toEqual([
                'No conversations match',
            ]);

            answerNextSearch({ bot: page([row({ id: 'c-1' })]) });
            typeSearch('ada');
            settle();
            expect(host().querySelector('.conversation-list__everything-empty')).toBeNull();
            expect(text('.conversation-list__section-empty .conversation-list__empty-title')).toEqual([
                'No matches',
                'No matches',
                'No matches',
            ]);
        });

        it('shows a search the server refuses under the field, without a toast, and lists nothing until it changes', () => {
            const refused = throwError(
                () =>
                    new HttpErrorResponse({
                        status: 400,
                        error: { code: 'invalid_search', message: 'The search must be at most 100 characters.' },
                    })
            );
            chatApi.getConversations
                .mockReturnValueOnce(refused)
                .mockReturnValueOnce(refused)
                .mockReturnValueOnce(refused)
                .mockReturnValueOnce(refused);
            typeSearch('x'.repeat(101));
            settle();

            const error = host().querySelector('.conversation-list-toolbar__error');
            expect(error?.textContent?.trim()).toBe('The search must be at most 100 characters.');
            expect(error?.getAttribute('role')).toBe('alert');
            expect(TestBed.inject(ToastService).error).not.toHaveBeenCalled();
            expect(host().querySelector('.conversation-list__section')).toBeNull();
            expect(host().querySelector('.conversation-list__everything-empty')).toBeNull();

            typeSearch('');
            expect(host().querySelector('.conversation-list-toolbar__error')).toBeNull();
            expect(sectionLabels()).toHaveLength(5);
            expect(ids('bot')).toEqual(['c-1']);
        });

        it('lists only Waiting and In progress under Mine, held by the user, and remembers it', () => {
            expect(toolbarButton('Mine')?.getAttribute('aria-pressed')).toBe('false');
            chatApi.getConversations.mockClear();
            chatApi.getConversations
                .mockReturnValueOnce(
                    page([handedOff('h-1', '2026-10-10T08:00:00Z', { mode: 'human', assigned_operator_id: 3 })])
                )
                .mockReturnValueOnce(page([answered('p-1', '2026-10-10T09:00:00Z', { assigned_operator_id: 3 })]));

            click(toolbarButton('Mine'));

            expect(sentParams()).toEqual([
                listParams('waiting', { mine: true }),
                listParams('in_progress', { mine: true }),
            ]);
            expect(sectionLabels()).toEqual(['Waiting for a person', 'In progress']);
            expect(toolbarButton('Mine')?.getAttribute('aria-pressed')).toBe('true');
            expect(JSON.parse(localStorage.getItem(PREFERENCES_KEY)!)).toMatchObject({ isMineOnly: true });
            expect(chatInboxStream.waitingCountFor).toHaveBeenLastCalledWith(null, 3);

            // Taken by another operator: no longer the user's. Taken by the user: theirs.
            conversationUpdated$.next(answered('p-1', '2026-10-10T10:00:00Z', { assigned_operator_id: 7 }));
            conversationUpdated$.next(answered('p-2', '2026-10-10T11:00:00Z', { assigned_operator_id: 3 }));
            conversationUpdated$.next(row({ id: 'c-5', last_message_at: '2026-10-10T12:00:00Z' }));
            conversationUpdated$.next(row({ id: 't-1', is_test: true, assigned_operator_id: 3 }));
            expect(ids('in_progress')).toEqual(['p-2']);
            expect(ids('waiting')).toEqual(['h-1']);
            expect(ids('bot')).toEqual([]);
            expect(ids('test')).toEqual([]);

            chatApi.getConversations.mockClear();
            click(toolbarButton('Mine'));
            expect(sentParams()).toEqual([listParams('waiting'), listParams('in_progress'), listParams('bot')]);
            expect(sectionLabels()).toHaveLength(5);
        });

        it("removes a row a search found once it is no longer the user's under Mine", () => {
            click(toolbarButton('Mine'));
            chatApi.getConversations
                .mockReturnValueOnce(page([]))
                .mockReturnValueOnce(page([answered('p-1', '2026-10-10T09:00:00Z', { assigned_operator_id: 3 })]));
            typeSearch('visitor 1');
            settle();
            expect(ids('in_progress')).toEqual(['p-1']);

            conversationUpdated$.next(answered('p-1', '2026-10-10T10:00:00Z', { assigned_operator_id: 7 }));
            expect(ids('in_progress')).toEqual([]);
        });

        it('says what Mine has nothing of', () => {
            chatApi.getConversations.mockReturnValueOnce(page([])).mockReturnValueOnce(page([]));
            click(toolbarButton('Mine'));
            expect(text('.conversation-list__everything-empty .conversation-list__empty-title')).toEqual([
                'Nothing of yours right now',
            ]);

            chatApi.getConversations
                .mockReturnValueOnce(page([]))
                .mockReturnValueOnce(page([answered('p-1', '2026-10-10T09:00:00Z', { assigned_operator_id: 3 })]));
            readyEpoch.update((value) => value + 1);
            fixture.detectChanges();
            expect(text('.conversation-list__section-empty .conversation-list__empty-title')).toEqual([
                'Nobody is waiting for you',
            ]);
        });

        it('offers no Mine without chats use, and a remembered Mine then does not apply', () => {
            TestBed.inject(ConversationListPreferencesService).setMineOnly(true);
            permissions.can = () => false;
            try {
                chatApi.getConversations.mockClear();
                fixture = TestBed.createComponent(ConversationListComponent);
                fixture.detectChanges();
                expect(toolbarButton('Mine')).toBeUndefined();
                expect(sentParams().every(({ mine }) => mine === false)).toBe(true);
                // Nor Tests, which need chats create or update.
                expect(sectionLabels()).toHaveLength(4);
            } finally {
                permissions.can = (resource, action) =>
                    resource === ResourceCode.Chats && (action === ActionCode.Use || action === ActionCode.Create);
            }
        });

        it('sorts newest first by default; Oldest first goes to every section, orders live rows and is remembered', () => {
            expect(toolbarButton('Newest first')).toBeDefined();
            chatApi.getConversations.mockClear();
            answerNextLoad({
                bot: page([row({ id: 'c-2', last_message_at: '2026-10-10T09:00:00Z' }), row({ id: 'c-1' })]),
            });

            click(toolbarButton('Newest first'));

            expect(sentParams()).toEqual([
                listParams('waiting', { order: 'oldest' }),
                listParams('in_progress', { order: 'oldest' }),
                listParams('bot', { order: 'oldest' }),
            ]);
            expect(toolbarButton('Oldest first')).toBeDefined();
            expect(JSON.parse(localStorage.getItem(PREFERENCES_KEY)!)).toMatchObject({ order: 'oldest' });

            conversationUpdated$.next(row({ id: 'c-2', last_message_at: '2026-10-10T11:00:00Z' }));
            expect(ids('bot')).toEqual(['c-1', 'c-2']);
        });

        it('says above the Waiting rows that they are longest wait first, whatever the sort', () => {
            expect(host().querySelector('.conversation-list__section-note')).toBeNull();
            reloadWith({ waiting: page([handedOff('h-1', '2026-10-10T08:00:00Z')]) });
            expect(text('.conversation-list__section-note')).toEqual(['Longest wait first']);
            expect(
                host().querySelector('.conversation-list__section-note')?.closest('.conversation-list__section')
            ).toBe(host().querySelector('.conversation-list__section[data-section="waiting"]'));
        });

        it('keeps the sort and Mine for the next column, never the search', () => {
            click(toolbarButton('Newest first'));
            click(toolbarButton('Mine'));
            typeSearch('ada');
            settle();

            fixture = TestBed.createComponent(ConversationListComponent);
            fixture.detectChanges();
            expect(toolbarButton('Oldest first')).toBeDefined();
            expect(toolbarButton('Mine')?.getAttribute('aria-pressed')).toBe('true');
            expect(searchField().value).toBe('');
            expect(sentParams().at(-1)).toEqual(listParams('in_progress', { mine: true, order: 'oldest' }));
        });

        it('drops Mine and the search when they would keep a new test conversation out of the list', async () => {
            Element.prototype.scrollIntoView = vi.fn();
            try {
                click(toolbarButton('Mine'));
                typeSearch('ada');
                settle();
                chatApi.getConversations.mockClear();

                fixture.componentInstance.reveal('test');
                fixture.detectChanges();
                await Promise.resolve();

                expect(toolbarButton('Mine')?.getAttribute('aria-pressed')).toBe('false');
                expect(searchField().value).toBe('');
                expect(headerButton('Tests').getAttribute('aria-expanded')).toBe('true');
                expect(sentParams().at(-1)).toEqual(listParams('bot'));
                expect(sentParams()).toContainEqual(listParams('test'));
                // Set aside for this column only: the remembered Mine stays for the next visit.
                expect(TestBed.inject(ConversationListPreferencesService).isMineOnly()).toBe(true);
                expect(JSON.parse(localStorage.getItem(PREFERENCES_KEY)!)).toMatchObject({ isMineOnly: true });

                fixture = TestBed.createComponent(ConversationListComponent);
                fixture.detectChanges();
                expect(toolbarButton('Mine')?.getAttribute('aria-pressed')).toBe('true');
            } finally {
                delete (Element.prototype as Partial<Element>).scrollIntoView;
            }
        });
    });

    describe('motion', () => {
        // Where each row is on screen, by conversation id; jsdom has no layout.
        let positions: Map<string, number>;
        let animations: { element: Element; keyframes: Keyframe[]; finish: () => void; cancel: () => void }[];
        let reducedMotion: boolean;

        const slideOf = (id: string): string | undefined =>
            animations
                .filter(({ element }) => (element as HTMLElement).dataset['id'] === id)
                .map(({ keyframes }) => String(keyframes[0]['transform']))
                .at(-1);

        async function render(): Promise<void> {
            fixture.detectChanges();
            await fixture.whenStable();
        }

        beforeEach(() => {
            positions = new Map();
            animations = [];
            reducedMotion = false;
            vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function (this: Element) {
                return { top: positions.get((this as HTMLElement).dataset['id'] ?? '') ?? 0 } as DOMRect;
            });
            Element.prototype.scrollIntoView = vi.fn();
            Element.prototype.animate = vi.fn(function (this: Element, keyframes: Keyframe[]) {
                const animation = {
                    element: this,
                    keyframes,
                    // Never settles here: a spec finishes animations through `finish`.
                    finished: new Promise<void>(() => undefined),
                    onfinish: null as (() => void) | null,
                    oncancel: null as (() => void) | null,
                    finish: vi.fn(() => animation.onfinish?.()),
                    cancel: vi.fn(() => animation.oncancel?.()),
                };
                animations.push(animation);
                return animation as unknown as Animation;
            }) as unknown as typeof Element.prototype.animate;
            vi.stubGlobal(
                'matchMedia',
                vi.fn((query: string) => ({ matches: reducedMotion && query.includes('reduce'), media: query }))
            );
        });

        afterEach(() => {
            delete (Element.prototype as Partial<Element>).animate;
            delete (Element.prototype as Partial<Element>).scrollIntoView;
        });

        /** Bot lists c-1 above c-2; then c-2 gets a newer message and moves to the top. */
        async function moveSecondRowUp(): Promise<void> {
            reloadWith({
                bot: page([row({ id: 'c-1' }), row({ id: 'c-2', last_message_at: '2026-10-10T09:00:00Z' })]),
            });
            await render();
            positions.set('c-1', 0).set('c-2', 50);
            conversationUpdated$.next(row({ id: 'c-2', last_message_at: '2026-10-10T11:00:00Z' }));
            positions.set('c-2', 0).set('c-1', 50);
            await render();
        }

        it('slides the rows a live change moved, each from where it was', async () => {
            await moveSecondRowUp();
            expect(slideOf('c-2')).toBe('translateY(50px)');
            expect(slideOf('c-1')).toBe('translateY(-50px)');
        });

        it('moves nothing when the rows are loaded, paged or reloaded', async () => {
            reloadWith({
                bot: page([row({ id: 'c-1' }), row({ id: 'c-2', last_message_at: '2026-10-10T09:00:00Z' })]),
            });
            await render();
            positions.set('c-1', 0).set('c-2', 50);
            reloadWith({
                bot: page([row({ id: 'c-2' }), row({ id: 'c-1', last_message_at: '2026-10-10T09:00:00Z' })]),
            });
            positions.set('c-2', 0).set('c-1', 50);
            await render();
            expect(animations).toEqual([]);
        });

        it('moves nothing when the sort, Mine or the desk changes: each lists from the start', async () => {
            reloadWith({
                bot: page([row({ id: 'c-1' }), row({ id: 'c-2', last_message_at: '2026-10-10T09:00:00Z' })]),
            });
            await render();
            positions.set('c-1', 0).set('c-2', 50);

            answerNextLoad({
                bot: page([row({ id: 'c-2', last_message_at: '2026-10-10T09:00:00Z' }), row({ id: 'c-1' })]),
            });
            positions.set('c-2', 0).set('c-1', 50);
            click(toolbarButton('Newest first'));
            await render();
            chatApi.getConversations.mockReturnValueOnce(page([])).mockReturnValueOnce(page([]));
            click(toolbarButton('Mine'));
            await render();
            scopeTo('b-2');
            await render();

            expect(animations).toEqual([]);
        });

        it('moves nothing under reduced motion', async () => {
            reducedMotion = true;
            await moveSecondRowUp();
            expect(animations).toEqual([]);
        });

        it('gives the focus back to a focused row re-created in another section, then brings it into view', async () => {
            const focus = vi.spyOn(HTMLElement.prototype, 'focus');
            rowButtons()[0].focus();
            expect(rowButtons()[0].closest('[data-id]')?.getAttribute('data-id')).toBe('c-1');

            conversationUpdated$.next(handedOff('c-1', '2026-10-10T11:00:00Z'));
            await render();

            const moved = host().querySelector<HTMLElement>(
                '.conversation-list__section[data-section="waiting"] [data-id="c-1"]'
            );
            expect(moved).not.toBeNull();
            expect(document.activeElement).toBe(moved?.querySelector('button.conversation-row'));
            // Focused without a jump; it did not slide (jsdom has no layout), so it is scrolled into view at once.
            expect(focus).toHaveBeenLastCalledWith({ preventScroll: true });
            expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith({ block: 'nearest' });
        });

        it('hands the focus to the next row, else to the section header, when a focused row is no longer shown', async () => {
            chatApi.getConversations
                .mockReturnValueOnce(page([]))
                .mockReturnValueOnce(
                    page([
                        answered('p-1', '2026-10-10T10:00:00Z', { assigned_operator_id: 3 }),
                        answered('p-2', '2026-10-10T09:00:00Z', { assigned_operator_id: 3 }),
                    ])
                );
            click(toolbarButton('Mine'));
            await render();
            const focusedRow = (): string | null | undefined =>
                document.activeElement?.closest('[data-id]')?.getAttribute('data-id');

            // Another operator takes p-1 with force: under Mine it is no longer listed.
            rowButtons()[0].focus();
            conversationUpdated$.next(answered('p-1', '2026-10-10T11:00:00Z', { assigned_operator_id: 7 }));
            await render();
            expect(focusedRow()).toBe('p-2');

            conversationUpdated$.next(answered('p-2', '2026-10-10T11:00:00Z', { assigned_operator_id: 7 }));
            await render();
            expect(document.activeElement).toBe(headerButton('In progress'));
            expect(Element.prototype.scrollIntoView).toHaveBeenLastCalledWith({ block: 'nearest' });
        });

        it('finishes a slide still running when the column goes away', async () => {
            await moveSecondRowUp();
            const running = animations.map(({ finish, cancel }) => ({ finish, cancel }));
            expect(running.length).toBeGreaterThan(0);
            fixture.destroy();
            expect(running.every(({ finish }) => vi.mocked(finish).mock.calls.length > 0)).toBe(true);
        });
    });

    describe('rows', () => {
        it('opens a conversation when its row is clicked', () => {
            const opened: ChatConversation[] = [];
            fixture.componentInstance.selectedChange.subscribe((conversation) => opened.push(conversation));
            rowButtons()[0].click();
            expect(opened.map(({ id }) => id)).toEqual(['c-1']);
        });

        it('names the desk under each visitor on All desks only', () => {
            listDesks([desk]);
            fixture.detectChanges();
            expect(text('.conversation-row__desk')).toEqual(['Support']);

            scopeTo('b-1');
            expect(text('.conversation-row__preview')).toEqual(['hello']);
            expect(text('.conversation-row__desk')).toEqual([]);
        });

        it('makes one row the Tab stop: the open one when shown, else the first', () => {
            reloadWith({
                bot: page([
                    row({ id: 'c-1' }),
                    row({ id: 'c-2', last_message_at: '2026-10-10T09:00:00Z' }),
                    row({ id: 'c-3', last_message_at: '2026-10-10T08:00:00Z' }),
                ]),
            });
            const tabIndexes = () => rowButtons().map((button) => button.tabIndex);
            expect(tabIndexes()).toEqual([0, -1, -1]);

            select('c-2');
            expect(tabIndexes()).toEqual([-1, 0, -1]);
        });

        it('keeps the section headers in the Tab order', () => {
            const headers = Array.from(host().querySelectorAll<HTMLButtonElement>('.conversation-section-header'));
            expect(headers).toHaveLength(5);
            expect(headers.every((button) => button.tabIndex === 0)).toBe(true);
        });

        it('moves the focus and the selection with ↑, ↓, Home and End across sections, skipping collapsed ones', () => {
            reloadWith({
                waiting: page([handedOff('h-1', '2026-10-10T08:00:00Z')]),
                bot: page([row({ id: 'c-1' }), row({ id: 'c-2', last_message_at: '2026-10-10T09:00:00Z' })]),
            });
            // Tests is collapsed but has a live row: ↓ from the waiting row skips it.
            conversationUpdated$.next(row({ id: 't-1', is_test: true }));
            fixture.detectChanges();
            const opened: string[] = [];
            fixture.componentInstance.selectedChange.subscribe((conversation) => opened.push(conversation.id));
            const press = (key: string): void => {
                (document.activeElement as HTMLElement).dispatchEvent(
                    new KeyboardEvent('keydown', { key, cancelable: true, bubbles: true })
                );
                fixture.detectChanges();
            };

            rowButtons()[0].focus();
            press('ArrowDown');
            expect(opened).toEqual(['c-1']);
            expect(document.activeElement).toBe(rowButtons()[1]);

            press('End');
            press('Home');
            press('ArrowUp');
            expect(opened).toEqual(['c-1', 'c-2', 'h-1']);
            expect(document.activeElement).toBe(rowButtons()[0]);

            // Opened, Tests sits between them.
            chatApi.getConversations.mockReturnValueOnce(page([row({ id: 't-1', is_test: true })]));
            toggle('Tests');
            rowButtons()[0].focus();
            press('ArrowDown');
            expect(opened.at(-1)).toBe('t-1');
        });

        it('takes a waiting conversation over from its row and shows the result at once, without opening it', () => {
            const opened = vi.fn();
            fixture.componentInstance.selectedChange.subscribe(opened);
            reloadWith({ waiting: page([handedOff('h-1', '2026-10-10T08:00:00Z')]) });
            chatApi.claim.mockReturnValueOnce(
                of(handedOff('h-1', '2026-10-10T08:00:00Z', { mode: 'human', assigned_operator_id: 3 }))
            );

            (host().querySelector('.conversation-row__take-over button') as HTMLButtonElement).click();
            fixture.detectChanges();

            expect(chatApi.claim).toHaveBeenCalledWith('h-1');
            expect(opened).not.toHaveBeenCalled();
            expect(store().findRow('h-1')?.assigned_operator_id).toBe(3);
            expect(host().querySelector('.conversation-row__take-over')).toBeNull();
            // The button went away with the take-over; the focus stays on the row, not on the page.
            expect(document.activeElement).toBe(rowButtons()[0]);
        });

        it('keeps the focus on the row through a take-over from another operator that needs a confirm', () => {
            // Shown as waiting, but another operator took it a moment ago: the server answers 409 and asks to force.
            reloadWith({ waiting: page([handedOff('h-1', '2026-10-10T08:00:00Z')]) });
            chatApi.claim
                .mockReturnValueOnce(
                    throwError(
                        () =>
                            new HttpErrorResponse({ status: 409, error: { code: 'claimed_by_other', message: 'held' } })
                    )
                )
                .mockReturnValueOnce(
                    of(handedOff('h-1', '2026-10-10T08:00:00Z', { mode: 'human', assigned_operator_id: 3 }))
                );
            vi.mocked(TestBed.inject(ConfirmationDialogService).confirm).mockReturnValueOnce(of(true));

            (host().querySelector('.conversation-row__take-over button') as HTMLButtonElement).click();
            fixture.detectChanges();

            expect(chatApi.claim).toHaveBeenLastCalledWith('h-1', true);
            expect(store().findRow('h-1')?.assigned_operator_id).toBe(3);
            expect(document.activeElement).toBe(rowButtons()[0]);
        });

        it('lists no Tests and asks for none without chats create or update', () => {
            permissions.can = (resource, action) =>
                resource === ResourceCode.Chats && (action === ActionCode.Read || action === ActionCode.Use);
            try {
                chatApi.getConversations.mockClear();
                fixture = TestBed.createComponent(ConversationListComponent);
                fixture.detectChanges();
                expect(sectionLabels()).toEqual(['Waiting for a person', 'In progress', 'Closed', 'Bot']);
                expect(requestedSections()).not.toContain('test');
            } finally {
                permissions.can = (resource, action) =>
                    resource === ResourceCode.Chats && (action === ActionCode.Use || action === ActionCode.Create);
            }
        });

        it('offers no Take over without chats use', () => {
            permissions.can = () => false;
            try {
                fixture = TestBed.createComponent(ConversationListComponent);
                fixture.detectChanges();
                reloadWith({ waiting: page([handedOff('h-1', '2026-10-10T08:00:00Z')]) });
                expect(rowButtons().length).toBe(1);
                expect(host().querySelector('.conversation-row__take-over')).toBeNull();
                expect(toolbarButton('Mine')).toBeUndefined();
            } finally {
                permissions.can = (resource, action) =>
                    resource === ResourceCode.Chats && (action === ActionCode.Use || action === ActionCode.Create);
            }
        });

        it('says once, politely, that the bot started replying in the open conversation', () => {
            select('c-1');
            const region = host().querySelector('[role="status"]')!;
            expect(region.textContent?.trim()).toBe('');

            conversationUpdated$.next(row({ id: 'c-1', state: 'processing' }));
            fixture.detectChanges();
            expect(region.textContent?.trim()).toBe('Bot is replying to Visitor 1');
            expect(host().querySelectorAll('[role="status"], [aria-live]').length).toBe(1);

            conversationUpdated$.next(row({ id: 'c-1', state: 'idle', last_message_preview: 'answer' }));
            fixture.detectChanges();
            expect(region.textContent?.trim()).toBe('');
        });

        it('moves the relative times on every 30 seconds and stops when the list goes away', () => {
            vi.useFakeTimers();
            vi.setSystemTime(new Date('2026-10-10T10:05:00Z'));
            fixture = TestBed.createComponent(ConversationListComponent);
            fixture.detectChanges();
            expect(text('.conversation-row__time')).toEqual(['5m']);

            vi.advanceTimersByTime(4 * 60_000);
            fixture.detectChanges();
            expect(text('.conversation-row__time')).toEqual(['9m']);

            const timersBefore = vi.getTimerCount();
            fixture.destroy();
            expect(vi.getTimerCount()).toBeLessThan(timersBefore);
        });
    });

    describe('for the page that opens conversations from the URL', () => {
        const lookUp = (id: string) => fixture.componentInstance.lookUp(id);

        it('says loading until what it shows has landed, then gives the row', () => {
            const bot$ = new Subject<ChatConversationPage>();
            reloadWith({ bot: bot$ });
            expect(lookUp('c-5')).toBe('loading');

            bot$.next({ results: [row({ id: 'c-5' })], next_cursor: null });
            fixture.detectChanges();
            expect(lookUp('c-5')).toEqual(expect.objectContaining({ id: 'c-5' }));
        });

        it('keeps saying loading while a section failed: an id it lacks may just not have arrived', () => {
            reloadWith({ bot: throwError(() => new HttpErrorResponse({ status: 500 })) });
            expect(lookUp('c-404')).toBe('loading');
        });

        it('says hidden while it hides some rows, and missing once everything it can list has loaded without it', () => {
            // Tests and Closed start collapsed.
            expect(lookUp('c-404')).toBe('hidden');

            fixture.componentInstance.showEverything();
            fixture.detectChanges();
            expect(expandedSections()).toEqual(['waiting', 'in_progress', 'test', 'closed', 'bot']);
            expect(lookUp('c-404')).toBe('missing');
        });

        it('says hidden, not loading, when every section is collapsed: there is nothing open to wait for', () => {
            for (const section of ['waiting', 'in_progress', 'bot'] as const) store().setCollapsed(section, true);
            fixture.detectChanges();
            expect(lookUp('c-404')).toBe('hidden');
        });

        it('shows everything for a conversation Mine hides: Mine set aside for this column only, every section open', () => {
            chatApi.getConversations.mockImplementation((params: ConversationListParams) =>
                page(params.section === 'test' ? [row({ id: 't-1', is_test: true })] : [])
            );
            click(toolbarButton('Mine'));
            expect(lookUp('t-1')).toBe('hidden');

            fixture.componentInstance.showEverything();
            fixture.detectChanges();

            expect(toolbarButton('Mine')?.getAttribute('aria-pressed')).toBe('false');
            expect(expandedSections()).toEqual(['waiting', 'in_progress', 'test', 'closed', 'bot']);
            expect(lookUp('t-1')).toEqual(expect.objectContaining({ id: 't-1' }));
        });

        it('leaves the remembered choices as they were: the user asked for none of it', () => {
            store().setCollapsed('bot', true);
            click(toolbarButton('Mine'));
            const remembered = localStorage.getItem(PREFERENCES_KEY);

            fixture.componentInstance.showEverything();
            fixture.detectChanges();

            expect(localStorage.getItem(PREFERENCES_KEY)).toBe(remembered);
            expect(collapsedSections()).toEqual(['test', 'closed', 'bot']);
            expect(TestBed.inject(ConversationListPreferencesService).isMineOnly()).toBe(true);
        });

        it("hands a section opened for the column back to the user's own toggle, which is remembered", () => {
            fixture.componentInstance.showEverything();
            fixture.detectChanges();
            expect(expandedSections()).toContain('test');

            toggle('Tests');
            expect(expandedSections()).not.toContain('test');
            expect(collapsedSections()).toEqual(['test', 'closed']);

            toggle('Tests');
            expect(expandedSections()).toContain('test');
            expect(collapsedSections()).toEqual(['closed']);
        });

        it("focuses a conversation's row, or the row Tab lands on once that one is gone", () => {
            reloadWith({
                bot: page([row({ id: 'c-1' }), row({ id: 'c-2', last_message_at: '2026-10-10T09:00:00Z' })]),
            });
            fixture.componentInstance.focusRow('c-2');
            expect(document.activeElement).toBe(rowButtons()[1]);

            fixture.componentInstance.focusRow('c-404');
            expect(document.activeElement).toBe(rowButtons()[0]);
        });
    });
});
