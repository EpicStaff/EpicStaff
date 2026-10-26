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
    let nextPages: Partial<Record<ChatInboxSection, Observable<ChatConversationPage>>> = {};
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
        getConversations: vi.fn((params: ConversationListParams): Observable<ChatConversationPage> => {
            const answer = nextPages[params.section];
            if (answer) {
                delete nextPages[params.section];
                return answer;
            }
            return page(params.section === 'bot' ? [row({ id: 'c-1' })] : []);
        }),
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
            (button) => button.querySelector('.conversation-section-header__label')?.textContent?.trim() === label
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
    const rememberedSection = (): ChatInboxSection | null =>
        TestBed.inject(ConversationListPreferencesService).expanded();
    const expandedSections = (): ChatInboxSection[] =>
        store()
            .view()
            .filter(({ isExpanded }) => isExpanded)
            .map(({ section }) => section.id);
    const listedSections = (): ChatInboxSection[] =>
        store()
            .view()
            .map(({ section }) => section.id);
    const headerStates = (): (string | null)[] =>
        Array.from(host().querySelectorAll('.conversation-section-header')).map((button) =>
            button.getAttribute('aria-expanded')
        );
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

    type SectionPages = Partial<Record<ChatInboxSection, Observable<ChatConversationPage>>>;

    /**
     * The next load answers the sections open now (only Waiting for a person at first): each with its page in `pages`,
     * else with nothing.
     */
    function answerNextLoad(pages: SectionPages, sections: ChatInboxSection[] = expandedSections()): void {
        nextPages = Object.fromEntries(sections.map((section) => [section, pages[section] ?? page([])]));
    }

    /** As `answerNextLoad`, for a search starting: it opens every section the column lists. */
    function answerNextSearch(pages: SectionPages): void {
        answerNextLoad(pages, listedSections());
    }

    function showEverySection(): void {
        fixture.componentInstance.showEverything();
        fixture.detectChanges();
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
        nextPages = {};
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

        it('lists Waiting for a person, In progress, Tests, Closed and Bot in that order, only Waiting open', () => {
            expect(text('.conversation-section-header__label')).toEqual([
                'Waiting for a person',
                'In progress',
                'Tests',
                'Closed',
                'Bot',
            ]);
            expect(headerStates()).toEqual(['true', 'false', 'false', 'false', 'false']);
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

        it('requests the open section only, and reloads it on every stream ready', () => {
            expect(requestedSections()).toEqual(['waiting']);
            readyEpoch.update((value) => value + 1);
            fixture.detectChanges();
            expect(requestedSections()).toEqual(['waiting', 'waiting']);
        });

        it('says what the open section is for when it is empty, and keeps the folded headers to open', () => {
            reloadWith({});
            expect(text('.conversation-list__section-empty .conversation-list__empty-title')).toEqual([
                'Nobody is waiting',
            ]);
            expect(sectionLabels()).toHaveLength(5);
        });

        it('says per open section what an empty one is for while another has rows', () => {
            showEverySection();
            expect(text('.conversation-list__section-empty .conversation-list__empty-title')).toEqual([
                'Nobody is waiting',
                'Nothing in progress',
                'No test conversations',
                'Nothing closed yet',
            ]);
        });
    });

    describe('one section open at a time', () => {
        it('opens a folded section from its header as the only open one, and remembers it per browser', () => {
            toggle('Bot');
            expect(headerStates()).toEqual(['false', 'false', 'false', 'false', 'true']);
            expect(text('.conversation-row__preview')).toEqual(['hello']);
            expect(rememberedSection()).toBe('bot');

            fixture = TestBed.createComponent(ConversationListComponent);
            fixture.detectChanges();
            expect(headerStates()).toEqual(['false', 'false', 'false', 'false', 'true']);

            toggle('In progress');
            expect(headerStates()).toEqual(['false', 'true', 'false', 'false', 'false']);
            expect(rememberedSection()).toBe('in_progress');
        });

        it('folds the open section from its header, leaving none open, and remembers that too', () => {
            toggle('Waiting for a person');
            expect(headerStates()).toEqual(['false', 'false', 'false', 'false', 'false']);
            expect(rememberedSection()).toBeNull();

            chatApi.getConversations.mockClear();
            fixture = TestBed.createComponent(ConversationListComponent);
            fixture.detectChanges();
            expect(headerStates()).toEqual(['false', 'false', 'false', 'false', 'false']);
            expect(chatApi.getConversations).not.toHaveBeenCalled();
        });

        it('never requests a folded section, and loads it when it is opened', () => {
            expect(requestedSections()).toEqual(['waiting']);

            chatApi.getConversations.mockReturnValueOnce(page([row({ id: 't-1', is_test: true })]));
            toggle('Tests');
            expect(chatApi.getConversations).toHaveBeenLastCalledWith(listParams('test'));
            expect(ids('test')).toEqual(['t-1']);

            chatApi.getConversations.mockClear();
            readyEpoch.update((value) => value + 1);
            fixture.detectChanges();
            expect(requestedSections()).toEqual(['test']);
        });

        it('does not request a section again when it is opened again for the same desk', () => {
            toggle('Tests');
            toggle('Tests');
            toggle('Tests');
            toggle('Waiting for a person');
            expect(requestedSections()).toEqual(['waiting', 'test']);
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

        describe('keeping the pressed header in view', () => {
            let scroller: HTMLElement;
            let botTop: number;

            /** The column is scrolled `scrollTop` down; the Bot section starts at `sectionTopOnScreen`. */
            function scrolledWithBotAt(sectionTopOnScreen: number, scrollTop = 500): void {
                scroller = host().querySelector<HTMLElement>('.conversation-list__scroller')!;
                const botSection = host().querySelector<HTMLElement>(
                    '.conversation-list__section[data-section="bot"]'
                )!;
                Object.defineProperty(scroller, 'scrollTop', { value: scrollTop, writable: true, configurable: true });
                scroller.getBoundingClientRect = () => ({ top: 100 }) as DOMRect;
                botTop = sectionTopOnScreen;
                botSection.getBoundingClientRect = () => ({ top: botTop }) as DOMRect;
            }

            async function openBot(): Promise<void> {
                toggle('Bot');
                await fixture.whenStable();
            }

            it('scrolls back to the section so the folded header stays where it was pressed', async () => {
                await openBot();
                // Deep inside Bot: its header is stuck and the section began 300px above the view.
                scrolledWithBotAt(-200);
                toggle('Bot');
                await fixture.whenStable();
                expect(headerButton('Bot').getAttribute('aria-expanded')).toBe('false');
                expect(scroller.scrollTop).toBe(200);
            });

            it('leaves the scroll alone when nothing above the pressed header moves', async () => {
                await openBot();
                scrolledWithBotAt(150);
                toggle('Bot');
                await fixture.whenStable();
                expect(scroller.scrollTop).toBe(500);
            });

            it('keeps an opened header where it was pressed while the open section above it folds', async () => {
                scrolledWithBotAt(400, 1000);
                headerButton('Bot').click();
                botTop = -500;
                fixture.detectChanges();
                await fixture.whenStable();

                expect(headerStates()).toEqual(['false', 'false', 'false', 'false', 'true']);
                expect(scroller.scrollTop).toBe(100);
            });
        });

        it('opens Tests for this visit and scrolls it to the top when a test conversation starts', async () => {
            const scrolled: Element[] = [];
            Element.prototype.scrollIntoView = vi.fn(function (this: Element) {
                scrolled.push(this);
            });
            try {
                fixture.componentInstance.reveal('test');
                fixture.detectChanges();
                await fixture.whenStable();

                expect(expandedSections()).toEqual(['waiting', 'test']);
                expect(rememberedSection()).toBe('waiting');
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
            showEverySection();
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

        it('pages Tests with the Tests cursor once Tests is open, and never while it is folded', () => {
            chatApi.getConversations.mockReturnValueOnce(page([row({ id: 't-1', is_test: true })], 'test-2'));
            toggle('Tests');
            expect(sentinels()).toEqual(['test']);

            toggle('Tests');
            expect(sentinels()).toEqual([]);
            const calls = chatApi.getConversations.mock.calls.length;
            store().loadMore('test');
            expect(chatApi.getConversations.mock.calls.length).toBe(calls);

            toggle('Tests');
            chatApi.getConversations.mockReturnValueOnce(page([]));
            scrollToEndOf('test');
            expect(chatApi.getConversations).toHaveBeenLastCalledWith(listParams('test', { cursor: 'test-2' }));
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
            toggle('Bot');
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
            toggle('Bot');
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
            showEverySection();
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
            showEverySection();
            reloadWith({
                waiting: page([handedOff('h-1', '2026-10-10T08:00:00Z')]),
                in_progress: page([answered('p-1', '2026-10-10T09:00:00Z')]),
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
            showEverySection();
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
            showEverySection();
            reloadWith({
                in_progress: page([answered('h-1', '2026-10-10T08:00:00Z')]),
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
            toggle('Bot');
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
            toggle('Bot');
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
            toggle('Bot');
            reloadWith({ bot: stale$ });
            expect(stale$.observed).toBe(true);

            scopeTo('b-2');

            expect(stale$.observed).toBe(false);
            stale$.next({ results: [row({ id: 'c-stale' })], next_cursor: null });
            expect(ids('bot')).toEqual(['c-1']);
        });

        it('reloads the open section when the desk changes, and forgets what a folded one had loaded', () => {
            toggle('Tests');
            chatApi.getConversations.mockClear();
            scopeTo('b-2');
            expect(sentParams()).toEqual([listParams('test', { binding: 'b-2' })]);

            toggle('Waiting for a person');
            chatApi.getConversations.mockClear();
            scopeTo('b-3');
            expect(sentParams()).toEqual([listParams('waiting', { binding: 'b-3' })]);
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
            expect(sentParams().at(-1)).toEqual(listParams('closed', { order: 'oldest' }));
            conversationUpdated$.next(closedRow('x-3', '2026-10-10T13:00:00Z'));
            expect(ids('closed')).toEqual(['x-3', 'x-2', 'x-1']);
        });

        it('takes a conversation a live close ends out of its section: into Closed when open, out of sight when not', () => {
            toggle('In progress');
            reloadWith({
                in_progress: page([answered('p-1', '2026-10-10T09:00:00Z'), answered('p-2', '2026-10-10T08:00:00Z')]),
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
            chatApi.getConversations.mockReturnValueOnce(page([]));
            toggle('Closed');
            conversationUpdated$.next(closedRow('t-1', '2026-10-10T12:00:00Z', { is_test: true }));
            fixture.detectChanges();
            expect(ids('test')).toEqual(['t-1']);
            expect(ids('closed')).toEqual([]);
        });

        it('is hidden under Mine, closed conversations of the user included', () => {
            click(toolbarButton('Mine'));
            expect(sectionLabels()).toEqual(['Waiting for a person', 'In progress']);
            expect(requestedSections()).not.toContain('closed');
            conversationUpdated$.next(closedRow('x-1', '2026-10-10T12:00:00Z', { assigned_operator_id: 3 }));
            expect(ids('closed')).toEqual([]);
        });

        describe('while searching', () => {
            beforeEach(() => vi.useFakeTimers());

            it('opens with every section for a search in this column only, stays open as it changes, and folds back once cleared', () => {
                answerNextSearch({ closed: page([closedRow('x-1', '2026-10-10T12:00:00Z')]) });
                typeSearch('12');
                settle();
                expect(expandedSections()).toEqual(['waiting', 'in_progress', 'test', 'closed', 'bot']);
                expect(sentParams()).toContainEqual(listParams('closed', { q: '12' }));
                expect(ids('closed')).toEqual(['x-1']);
                expect(rememberedSection()).toBe('waiting');

                answerNextSearch({});
                typeSearch('123');
                settle();
                expect(expandedSections()).toContain('closed');

                chatApi.getConversations.mockClear();
                typeSearch('');
                expect(expandedSections()).toEqual(['waiting']);
                expect(requestedSections()).toEqual(['waiting']);
            });

            it('folds and opens a section for the search only: typing on keeps it, clearing returns to the remembered one', () => {
                answerNextSearch({});
                typeSearch('12');
                settle();
                toggle('Closed');
                expect(expandedSections()).toEqual(['waiting', 'in_progress', 'test', 'bot']);

                answerNextLoad({});
                typeSearch('123');
                settle();
                expect(expandedSections()).not.toContain('closed');

                chatApi.getConversations.mockReturnValueOnce(page([]));
                toggle('Closed');
                expect(expandedSections()).toEqual(['waiting', 'in_progress', 'test', 'closed', 'bot']);

                toggle('Waiting for a person');
                expect(expandedSections()).not.toContain('waiting');
                expect(rememberedSection()).toBe('waiting');

                typeSearch('');
                expect(expandedSections()).toEqual(['waiting']);
                expect(rememberedSection()).toBe('waiting');
            });

            it('folds back to the section the user keeps open', () => {
                chatApi.getConversations.mockReturnValueOnce(page([]));
                toggle('Closed');
                answerNextSearch({});
                typeSearch('12');
                settle();
                typeSearch('');
                expect(expandedSections()).toEqual(['closed']);
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

        it('searches every section once typing settles, each from its start, the folded ones included', () => {
            chatApi.getConversations.mockClear();
            typeSearch('  Ada ');
            vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS - 1);
            fixture.detectChanges();
            expect(chatApi.getConversations).not.toHaveBeenCalled();

            vi.advanceTimersByTime(1);
            fixture.detectChanges();
            expect(sentParams()).toEqual([
                listParams('waiting', { q: 'Ada' }),
                listParams('in_progress', { q: 'Ada' }),
                listParams('test', { q: 'Ada' }),
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
            expect(sentParams().map(({ q }) => q)).toEqual(['']);
        });

        it('clears with Escape and with the clear button at once, keeping the focus in the field', async () => {
            typeSearch('ada');
            settle();
            chatApi.getConversations.mockClear();

            searchField().dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
            fixture.detectChanges();
            await Promise.resolve();
            expect(searchField().value).toBe('');
            expect(sentParams().map(({ q }) => q)).toEqual(['']);

            typeSearch('ada');
            settle();
            chatApi.getConversations.mockClear();
            click(host().querySelector<HTMLButtonElement>('.search__clear-btn')!);
            expect(sentParams().map(({ q }) => q)).toEqual(['']);
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
                in_progress: page([answered('p-1', '2026-10-10T09:00:00Z')]),
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
            toggle('Bot');
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

        it('says per section when nothing matches, whether or not another section has matches', () => {
            answerNextSearch({});
            typeSearch('zzz');
            settle();
            expect(text('.conversation-list__section-empty .conversation-list__empty-title')).toEqual([
                'No matches',
                'No matches',
                'No matches',
                'No matches',
                'No matches',
            ]);

            answerNextSearch({ bot: page([row({ id: 'c-1' })]) });
            typeSearch('ada');
            settle();
            expect(text('.conversation-list__section-empty .conversation-list__empty-title')).toEqual([
                'No matches',
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
            answerNextSearch({ waiting: refused, in_progress: refused, test: refused, closed: refused, bot: refused });
            typeSearch('x'.repeat(101));
            settle();

            const error = host().querySelector('.conversation-list-toolbar__error');
            expect(error?.textContent?.trim()).toBe('The search must be at most 100 characters.');
            expect(error?.getAttribute('role')).toBe('alert');
            expect(TestBed.inject(ToastService).error).not.toHaveBeenCalled();
            expect(host().querySelector('.conversation-list__section')).toBeNull();

            chatApi.getConversations.mockReturnValueOnce(page([handedOff('h-1', '2026-10-10T08:00:00Z')]));
            typeSearch('');
            expect(host().querySelector('.conversation-list-toolbar__error')).toBeNull();
            expect(sectionLabels()).toHaveLength(5);
            expect(ids('waiting')).toEqual(['h-1']);
        });

        it('lists only Waiting and In progress under Mine, held by the user, and remembers it', () => {
            expect(toolbarButton('Mine')?.getAttribute('aria-pressed')).toBe('false');
            chatApi.getConversations.mockClear();
            chatApi.getConversations.mockReturnValueOnce(
                page([handedOff('h-1', '2026-10-10T08:00:00Z', { mode: 'human', assigned_operator_id: 3 })])
            );

            click(toolbarButton('Mine'));

            expect(sentParams()).toEqual([listParams('waiting', { mine: true })]);
            expect(sectionLabels()).toEqual(['Waiting for a person', 'In progress']);
            expect(toolbarButton('Mine')?.getAttribute('aria-pressed')).toBe('true');
            expect(TestBed.inject(ConversationListPreferencesService).isMineOnly()).toBe(true);
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
            expect(sentParams()).toEqual([listParams('waiting')]);
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
            click(toolbarButton('Mine'));
            expect(text('.conversation-list__section-empty .conversation-list__empty-title')).toEqual([
                'Nobody is waiting for you',
            ]);

            toggle('In progress');
            expect(text('.conversation-list__section-empty .conversation-list__empty-title')).toEqual([
                'None of yours in progress',
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

        it('sorts newest first by default; Oldest first goes to the open section, orders live rows and is remembered', () => {
            expect(toolbarButton('Newest first')).toBeDefined();
            toggle('Bot');
            chatApi.getConversations.mockClear();
            answerNextLoad({
                bot: page([row({ id: 'c-2', last_message_at: '2026-10-10T09:00:00Z' }), row({ id: 'c-1' })]),
            });

            click(toolbarButton('Newest first'));

            expect(sentParams()).toEqual([listParams('bot', { order: 'oldest' })]);
            expect(toolbarButton('Oldest first')).toBeDefined();
            expect(TestBed.inject(ConversationListPreferencesService).order()).toBe('oldest');

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
            expect(sentParams().at(-1)).toEqual(listParams('waiting', { mine: true, order: 'oldest' }));
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
                expect(expandedSections()).toEqual(['waiting', 'test']);
                expect(sentParams().at(-1)).toEqual(listParams('test'));
                // Set aside for this column only: the remembered Mine stays for the next visit.
                expect(TestBed.inject(ConversationListPreferencesService).isMineOnly()).toBe(true);

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
            toggle('Bot');
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
            toggle('Bot');
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
            toggle('Bot');
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
            click(toolbarButton('Mine'));
            await render();
            scopeTo('b-2');
            await render();

            expect(animations).toEqual([]);
        });

        it('moves nothing when another section opens and the open one folds: neither fades nor slides', async () => {
            reloadWith({ waiting: page([handedOff('h-1', '2026-10-10T08:00:00Z')]) });
            await render();
            positions.set('h-1', 0);

            toggle('Bot');
            positions.set('c-1', 40);
            await render();

            expect(host().querySelector('[data-id="h-1"]')).toBeNull();
            expect(text('.conversation-row__preview')).toEqual(['hello']);
            expect(animations).toEqual([]);
        });

        it('moves nothing under reduced motion', async () => {
            reducedMotion = true;
            await moveSecondRowUp();
            expect(animations).toEqual([]);
        });

        it('gives the focus back to a focused row re-created in another section, then brings it into view', async () => {
            const focus = vi.spyOn(HTMLElement.prototype, 'focus');
            showEverySection();
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
            click(toolbarButton('Mine'));
            chatApi.getConversations.mockReturnValueOnce(
                page([
                    answered('p-1', '2026-10-10T10:00:00Z', { assigned_operator_id: 3 }),
                    answered('p-2', '2026-10-10T09:00:00Z', { assigned_operator_id: 3 }),
                ])
            );
            toggle('In progress');
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
            toggle('Bot');
            const opened: ChatConversation[] = [];
            fixture.componentInstance.selectedChange.subscribe((conversation) => opened.push(conversation));
            rowButtons()[0].click();
            expect(opened.map(({ id }) => id)).toEqual(['c-1']);
        });

        it('names the desk under each visitor on All desks only', () => {
            toggle('Bot');
            listDesks([desk]);
            fixture.detectChanges();
            expect(text('.conversation-row__desk')).toEqual(['Support']);

            scopeTo('b-1');
            expect(text('.conversation-row__preview')).toEqual(['hello']);
            expect(text('.conversation-row__desk')).toEqual([]);
        });

        it('makes one row the Tab stop: the open one when shown, else the first', () => {
            toggle('Bot');
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

        it('moves the focus and the selection with ↑, ↓, Home and End across open sections, skipping folded ones', () => {
            showEverySection();
            reloadWith({
                waiting: page([handedOff('h-1', '2026-10-10T08:00:00Z')]),
                bot: page([row({ id: 'c-1' }), row({ id: 'c-2', last_message_at: '2026-10-10T09:00:00Z' })]),
            });
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
            expect(opened).toEqual(['t-1']);

            // A user's press moves the focus to the header; jsdom's click does not.
            headerButton('Tests').focus();
            toggle('Tests');
            opened.length = 0;
            rowButtons()[0].focus();
            press('ArrowDown');
            expect(opened).toEqual(['c-1']);
            expect(document.activeElement).toBe(rowButtons()[1]);

            press('End');
            press('Home');
            press('ArrowUp');
            expect(opened).toEqual(['c-1', 'c-2', 'h-1']);
            expect(document.activeElement).toBe(rowButtons()[0]);
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
            TestBed.inject(ConversationListPreferencesService).setExpanded('bot');
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

    describe('compact', () => {
        const headerNames = (): (string | null)[] =>
            Array.from(host().querySelectorAll('.conversation-section-header')).map((button) =>
                button.getAttribute('aria-label')
            );
        const compactHeader = (label: string): HTMLButtonElement =>
            Array.from(host().querySelectorAll<HTMLButtonElement>('.conversation-section-header')).find((button) =>
                button.getAttribute('aria-label')?.startsWith(label)
            )!;

        function compact(): void {
            fixture.componentRef.setInput('canCollapse', true);
            fixture.componentRef.setInput('isCompact', true);
            fixture.detectChanges();
        }

        it('keeps only the toggle in the toolbar, which asks to expand the column it controls', () => {
            compact();
            const requests: number[] = [];
            fixture.componentInstance.compactToggle.subscribe(() => requests.push(1));
            const toolbarButtons = host().querySelectorAll<HTMLButtonElement>('app-conversation-list-toolbar button');

            expect(toolbarButtons).toHaveLength(1);
            expect(host().querySelector('app-conversation-list-toolbar input')).toBeNull();
            expect(toolbarButtons[0].getAttribute('aria-controls')).toBe(host().id);
            toolbarButtons[0].click();
            expect(requests).toEqual([1]);
        });

        it('names each section header by its label, the Waiting count included, instead of showing it', () => {
            waitingCount.set(3);
            compact();
            expect(headerNames()).toEqual(['Waiting for a person, 3', 'In progress', 'Tests', 'Closed', 'Bot']);
            expect(sectionLabels()).toEqual([]);
        });

        it('shows each conversation as its avatar, opened by a click and moved through with the keys', () => {
            compact();
            reloadWith({
                waiting: page([handedOff('h-1', '2026-10-10T08:00:00Z'), handedOff('h-2', '2026-10-10T09:00:00Z')]),
            });
            const opened: string[] = [];
            fixture.componentInstance.selectedChange.subscribe((conversation) => opened.push(conversation.id));

            expect(text('.conversation-row__preview')).toEqual([]);
            expect(rowButtons().map((button) => button.querySelectorAll('app-conversation-avatar').length)).toEqual([
                1, 1,
            ]);
            rowButtons()[0].click();
            rowButtons()[0].focus();
            rowButtons()[0].dispatchEvent(
                new KeyboardEvent('keydown', { key: 'ArrowDown', cancelable: true, bubbles: true })
            );
            expect(opened).toEqual(['h-1', 'h-2']);
        });

        it('opens a section from its header as the expanded column does', () => {
            compact();
            compactHeader('Bot').click();
            fixture.detectChanges();
            expect(expandedSections()).toEqual(['bot']);
            expect(rememberedSection()).toBe('bot');
        });

        it('leaves out the section notes and the empty-state texts', () => {
            compact();
            reloadWith({ waiting: page([handedOff('h-1', '2026-10-10T08:00:00Z')]) });
            expect(host().querySelector('.conversation-list__section-note')).toBeNull();

            compactHeader('In progress').click();
            fixture.detectChanges();
            expect(host().querySelector('.conversation-list__section-empty')).toBeNull();
        });
    });

    describe('for the page that opens conversations from the URL', () => {
        const lookUp = (id: string) => fixture.componentInstance.lookUp(id);

        it('says loading until what it shows has landed, then gives the row', () => {
            const waiting$ = new Subject<ChatConversationPage>();
            reloadWith({ waiting: waiting$ });
            expect(lookUp('c-5')).toBe('loading');

            waiting$.next({ results: [handedOff('c-5', '2026-10-10T08:00:00Z')], next_cursor: null });
            fixture.detectChanges();
            expect(lookUp('c-5')).toEqual(expect.objectContaining({ id: 'c-5' }));
        });

        it('keeps saying loading while a section failed: an id it lacks may just not have arrived', () => {
            reloadWith({ waiting: throwError(() => new HttpErrorResponse({ status: 500 })) });
            expect(lookUp('c-404')).toBe('loading');
        });

        it('says hidden while it hides some rows, and missing once everything it can list has loaded without it', () => {
            // Only Waiting starts open.
            expect(lookUp('c-404')).toBe('hidden');

            showEverySection();
            expect(expandedSections()).toEqual(['waiting', 'in_progress', 'test', 'closed', 'bot']);
            expect(lookUp('c-404')).toBe('missing');
        });

        it('says hidden, not loading, when every section is folded: there is nothing open to wait for', () => {
            toggle('Waiting for a person');
            expect(lookUp('c-404')).toBe('hidden');
        });

        it('shows everything for a conversation Mine hides: Mine set aside for this column only, every section open', () => {
            nextPages = { test: page([row({ id: 't-1', is_test: true })]) };
            click(toolbarButton('Mine'));
            expect(lookUp('t-1')).toBe('hidden');

            fixture.componentInstance.showEverything();
            fixture.detectChanges();

            expect(toolbarButton('Mine')?.getAttribute('aria-pressed')).toBe('false');
            expect(expandedSections()).toEqual(['waiting', 'in_progress', 'test', 'closed', 'bot']);
            expect(lookUp('t-1')).toEqual(expect.objectContaining({ id: 't-1' }));
        });

        it('shows everything in one pass while a search runs: the search clears and every section opens', () => {
            vi.useFakeTimers();
            typeSearch('ada');
            settle();

            fixture.componentInstance.showEverything();
            fixture.detectChanges();

            expect(store().isSearching()).toBe(false);
            expect(expandedSections()).toEqual(['waiting', 'in_progress', 'test', 'closed', 'bot']);
        });

        it('leaves the remembered choices as they were: the user asked for none of it', () => {
            toggle('Closed');
            click(toolbarButton('Mine'));
            showEverySection();

            expect(rememberedSection()).toBe('closed');
            expect(TestBed.inject(ConversationListPreferencesService).isMineOnly()).toBe(true);
        });

        it('ends the openings for the column at a press on a header: an open section folds alone, a folded one opens alone', () => {
            showEverySection();

            toggle('Tests');
            expect(expandedSections()).toEqual(['waiting', 'in_progress', 'closed', 'bot']);
            expect(rememberedSection()).toBe('waiting');

            toggle('Tests');
            expect(expandedSections()).toEqual(['test']);
            expect(rememberedSection()).toBe('test');
        });

        it("focuses a conversation's row, or the row Tab lands on once that one is gone", () => {
            toggle('Bot');
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
