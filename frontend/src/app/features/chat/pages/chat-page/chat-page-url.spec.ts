import { Location } from '@angular/common';
import { provideLocationMocks, SpyLocation } from '@angular/common/testing';
import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router, withComponentInputBinding } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { ActionCode, ResourceCode } from '@shared/models';
import { NEVER, Observable, of, Subject } from 'rxjs';

import { PhoneLayoutService } from '../../../../core/services/phone-layout.service';
import { ActiveOrgService } from '../../../../services/auth/active-org.service';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ProfileService } from '../../../../services/auth/profile.service';
import { ToastService } from '../../../../services/notifications';
import {
    CHAT_BINDING_DEFAULTS,
    ChatBinding,
    ChatConversation,
    ChatConversationPage,
    ChatInboxMessageEvent,
    ChatOperatorMessage,
} from '../../models/chat.model';
import { ChatApiService, ConversationListParams } from '../../services/chat-api.service';
import { ChatBindingActionsService } from '../../services/chat-binding-actions.service';
import { ChatDesksStorageService } from '../../services/chat-desks-storage.service';
import { ChatInboxStreamService } from '../../services/chat-inbox-stream.service';
import { ConversationListPreferencesService } from '../../services/conversation-list-preferences.service';
import { DeskDrawerService } from '../../services/desk-drawer.service';
import { URL_WRITE_DELAY_MS } from '../../services/open-conversation.service';
import { ChatPageComponent } from './chat-page.component';

class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

class IntersectionObserverStub {
    observe(): void {}
    disconnect(): void {}
}

@Component({ template: '' })
class OtherPageComponent {}

const row = (id: string, overrides: Partial<ChatConversation> = {}): ChatConversation => ({
    id,
    binding_id: 'b-1',
    mode: 'bot',
    state: 'idle',
    is_test: false,
    assigned_operator_id: null,
    tokens_used: 0,
    turns: 0,
    tokens_today: 0,
    turns_today: 0,
    last_message_at: '2026-10-10T10:00:00Z',
    last_message_preview: id,
    handoff_reason: '',
    handoff_at: null,
    visitor_number: Number(id.replace(/\D/g, '')) || 1,
    chat_user_id: null,
    assigned_operator_name: null,
    last_message_role: 'user',
    last_message_author_user_id: null,
    last_message_author_name: null,
    visitor_waiting_since: null,
    ...overrides,
});

const binding: ChatBinding = {
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
};

// Newest first in Bot: c-1 on top.
const BOT_ROWS = [1, 2, 3, 4].map((number) =>
    row(`c-${number}`, { last_message_at: `2026-10-10T1${9 - number}:00:00Z` })
);

const DESKS: ChatBinding[] = [binding, { ...binding, id: 'b-2', name: 'Sales' }];

const LIST = '/chat-bindings/all';
const PREFERENCES_KEY = 'chat:conversationList';

/** The chat page against the real router, list and history: what the URL and the browser's back and forward do. */
describe('ChatPageComponent and the URL', () => {
    const isPhone = signal(false);
    let respond: (params: ConversationListParams) => Observable<ChatConversationPage> = () => NEVER;
    const conversationUpdated$ = new Subject<ChatConversation>();
    const chatApi = {
        getBindings: vi.fn(() => of(DESKS)),
        getMyAliases: vi.fn(() => of([])),
        getConversations: vi.fn((params: ConversationListParams) => respond(params)),
        getMessages: vi.fn(() => of([] as ChatOperatorMessage[])),
        issueVisitorToken: vi.fn(() => NEVER),
        createTestConversation: vi.fn(),
    };
    const toast = { error: vi.fn(), success: vi.fn() };
    let harness: RouterTestingHarness;
    let location: SpyLocation;

    const host = (): HTMLElement => harness.fixture.nativeElement as HTMLElement;
    const page = (): ChatPageComponent => harness.routeDebugElement!.componentInstance as ChatPageComponent;
    const rows = (): HTMLButtonElement[] =>
        Array.from(host().querySelectorAll<HTMLButtonElement>('button.conversation-row'));
    const currentRow = (): string | null =>
        host().querySelector('button.conversation-row[aria-current="true"]')?.getAttribute('aria-label') ?? null;
    const inbox = (): HTMLElement => host().querySelector('.inbox') as HTMLElement;

    /**
     * Bot lists `botRows`, the other sections nothing, unless `bySection` says otherwise for a section of a desk (null
     * for every desk; an observable answers when it emits).
     */
    function listing(
        botRows: ChatConversation[],
        bySection?: (
            section: string,
            desk: string | null
        ) => ChatConversation[] | Observable<ChatConversationPage> | null | undefined
    ): void {
        respond = (params) => {
            const custom = bySection?.(params.section, params.binding ?? null);
            if (custom === null) return NEVER;
            if (custom instanceof Observable) return custom;
            const results = custom ?? (params.section === 'bot' ? botRows : []);
            return of({ results, next_cursor: null });
        };
    }

    async function settle(): Promise<void> {
        await harness.fixture.whenStable();
        harness.detectChanges();
        await harness.fixture.whenStable();
        harness.detectChanges();
    }

    /** Waits out the wider screens' write delay. */
    async function rest(): Promise<void> {
        await new Promise((resolve) => setTimeout(resolve, URL_WRITE_DELAY_MS));
        await settle();
    }

    /** The router takes a move through history up a macrotask later. */
    async function historyMove(move: () => void): Promise<void> {
        move();
        await new Promise((resolve) => setTimeout(resolve));
        await settle();
    }

    async function open(url: string): Promise<void> {
        await harness.navigateByUrl(url);
        await settle();
        location.urlChanges = [];
    }

    /** A key held down repeats about every 30ms. */
    async function holdDown(key: string, repeats: number): Promise<void> {
        for (let repeat = 0; repeat < repeats; repeat++) {
            (document.activeElement as HTMLElement).dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
            harness.detectChanges();
            await new Promise((resolve) => setTimeout(resolve, 30));
        }
    }

    beforeEach(async () => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        vi.stubGlobal('IntersectionObserver', IntersectionObserverStub);
        Element.prototype.scrollIntoView = vi.fn();
        vi.clearAllMocks();
        localStorage.clear();
        isPhone.set(false);
        listing(BOT_ROWS);
        TestBed.configureTestingModule({
            // Routed only, the page would compile outside TestBed, which then never resets what Angular cached about
            // its standalone imports: a later spec in the same worker overriding one of them (the composer's JSON
            // editor) would be ignored.
            imports: [ChatPageComponent],
            providers: [
                provideRouter(
                    [
                        {
                            path: 'chat-bindings',
                            // The desks shell provides it around the page.
                            providers: [DeskDrawerService],
                            children: [
                                { path: 'all', component: ChatPageComponent },
                                { path: ':bindingId', component: ChatPageComponent },
                            ],
                        },
                        { path: 'agents', component: OtherPageComponent },
                    ],
                    // As the app binds them: the desk id reaches the page's input.
                    withComponentInputBinding()
                ),
                provideLocationMocks(),
                { provide: ChatApiService, useValue: chatApi },
                {
                    provide: ChatInboxStreamService,
                    useValue: {
                        conversationUpdated$,
                        messageCreated$: new Subject<ChatInboxMessageEvent>(),
                        readyEpoch: signal(0),
                        status: signal('open'),
                        waitingCountFor: () => 0,
                    },
                },
                { provide: ChatBindingActionsService, useValue: {} },
                { provide: ProfileService, useValue: { currentUserSignal: signal({ id: 3 }) } },
                {
                    provide: PermissionsService,
                    useValue: { can: (resource: ResourceCode, action: ActionCode) => action !== ActionCode.Delete },
                },
                { provide: ToastService, useValue: toast },
                { provide: PhoneLayoutService, useValue: { isPhone } },
            ],
        });
        TestBed.inject(ActiveOrgService).set(1);
        TestBed.inject(ChatDesksStorageService).reload();
        location = TestBed.inject(Location) as SpyLocation;
        harness = await RouterTestingHarness.create();
        // As the app's initial navigation does: back and forward reach the router.
        TestBed.inject(Router).setUpLocationChangeListener();
    });

    afterEach(() => {
        vi.unstubAllGlobals();
        localStorage.clear();
        delete (Element.prototype as Partial<Element>).scrollIntoView;
    });

    it('follows ↓ held down with the open conversation at once, and writes the URL once, after the keys rest', async () => {
        await open(LIST);
        rows()[0].focus();
        rows()[0].click();
        harness.detectChanges();
        await holdDown('ArrowDown', 3);

        // While the key repeats, nothing is written: each repeat restarts the wait.
        expect(location.urlChanges).toEqual([]);
        expect(page().selectedId()).toBe('c-4');
        expect(page().selected()?.id).toBe('c-4');
        expect(currentRow()).toContain('Visitor 4');

        await rest();
        expect(location.urlChanges).toEqual([`replace: ${LIST}?conversation=c-4`]);
        expect(page().selected()?.id).toBe('c-4');
    });

    it("closes the previous org's conversation on an org switch on All desks, its id out of the URL before anything reads it", async () => {
        await open(`${LIST}?conversation=c-2`);
        expect(page().selected()?.id).toBe('c-2');

        TestBed.inject(ActiveOrgService).set(2);
        harness.detectChanges();
        expect(page().selected()).toBeNull();
        expect(host().querySelector('app-chat-thread-composer')).toBeNull();

        // The org switch reads the URL to return to only after its own requests: the id is gone by then.
        await settle();
        expect(TestBed.inject(Router).url).toBe(LIST);
        expect(location.urlChanges).toEqual([`replace: ${LIST}`]);
        expect(toast.error).not.toHaveBeenCalled();
    });

    it('reopens on a reload a test conversation that Mine hides: the column sets Mine aside and opens Tests', async () => {
        TestBed.inject(ConversationListPreferencesService).setMineOnly(true);
        listing([], (section) => (section === 'test' ? [row('t-7', { is_test: true })] : []));

        await open(`${LIST}?conversation=t-7`);

        expect(page().selected()?.id).toBe('t-7');
        expect(toast.error).not.toHaveBeenCalled();
        expect(location.path()).toBe(`${LIST}?conversation=t-7`);
        // For this column only: Mine and the collapsed Tests stay remembered.
        const preferences = TestBed.inject(ConversationListPreferencesService);
        expect(preferences.isMineOnly()).toBe(true);
        expect([...preferences.collapsed()]).toEqual(['test']);
    });

    it('reopens a conversation while every section is collapsed: the column opens them first', async () => {
        const preferences = TestBed.inject(ConversationListPreferencesService);
        for (const section of ['waiting', 'in_progress', 'test', 'bot'] as const)
            preferences.setCollapsed(section, true);

        const remembered = localStorage.getItem(PREFERENCES_KEY);

        await open(`${LIST}?conversation=c-3`);

        expect(page().selected()?.id).toBe('c-3');
        expect(toast.error).not.toHaveBeenCalled();
        expect(localStorage.getItem(PREFERENCES_KEY)).toBe(remembered);
    });

    it('leaves the remembered sections alone when a reload names an id nothing can list, then drops it', async () => {
        const remembered = localStorage.getItem(PREFERENCES_KEY);

        await open(`${LIST}?conversation=c-gone`);

        expect(toast.error).toHaveBeenCalledWith("Couldn't open that conversation.");
        expect(localStorage.getItem(PREFERENCES_KEY)).toBe(remembered);
        expect([...TestBed.inject(ConversationListPreferencesService).collapsed()]).toEqual(['test']);
    });

    it('drops, with a message, an id that nothing the column can list has', async () => {
        await open(LIST);
        await harness.navigateByUrl(`${LIST}?conversation=c-gone`);
        location.urlChanges = [];
        await settle();

        expect(toast.error).toHaveBeenCalledWith("Couldn't open that conversation.");
        expect(location.urlChanges).toEqual([`replace: ${LIST}`]);
        expect(page().selectedId()).toBeNull();
    });

    it("opens, after a move through history to another desk, that desk's own conversation from its URL, writing nothing", async () => {
        listing([], (section, desk) =>
            section === 'bot' ? [row(desk === 'b-2' ? 'c-2' : 'c-1', { binding_id: desk ?? 'b-1' })] : []
        );
        await open('/chat-bindings/b-2?conversation=c-2');
        await open('/chat-bindings/b-1?conversation=c-1');
        expect(page().selected()?.id).toBe('c-1');

        await historyMove(() => location.back());

        expect(location.path()).toBe('/chat-bindings/b-2?conversation=c-2');
        expect(page().selected()?.id).toBe('c-2');
        expect(toast.error).not.toHaveBeenCalled();
        expect(location.urlChanges).toEqual([]);
    });

    it('loads the messages of a conversation opened from its URL', async () => {
        await open(`${LIST}?conversation=c-2`);
        expect(chatApi.getMessages).toHaveBeenCalledWith('c-2');
    });

    it('writes nothing when the conversation already open is picked again', async () => {
        await open(LIST);
        rows()[0].click();
        await rest();
        expect(location.urlChanges).toEqual([`replace: ${LIST}?conversation=c-1`]);

        rows()[0].click();
        await rest();
        expect(location.urlChanges).toEqual([`replace: ${LIST}?conversation=c-1`]);
    });

    it("does not open another desk's conversation on a desk page, from a live update nor from the list", async () => {
        const botPage$ = new Subject<ChatConversationPage>();
        listing([], (section, desk) => (section === 'bot' && desk === 'b-2' ? botPage$ : undefined));
        // A hand-made link: c-1 is b-1's.
        await open('/chat-bindings/b-2?conversation=c-1');

        conversationUpdated$.next(row('c-1', { binding_id: 'b-1' }));
        harness.detectChanges();
        expect(page().selected()).toBeNull();

        botPage$.next({ results: [row('c-2', { binding_id: 'b-2' })], next_cursor: null });
        await settle();
        expect(page().selected()).toBeNull();
        expect(toast.error).toHaveBeenCalledWith("Couldn't open that conversation.");
        expect(location.path()).toBe('/chat-bindings/b-2');
    });

    describe('on a phone', () => {
        beforeEach(() => isPhone.set(true));

        it('pushes the thread on a row tap and closes it, without a slide, on the browser back', async () => {
            await open(LIST);
            rows()[1].click();
            await settle();

            expect(location.urlChanges).toEqual([`${LIST}?conversation=c-2`]);
            expect(inbox().classList).toContain('inbox--thread-open');
            expect(inbox().classList).toContain('inbox--animated');

            await historyMove(() => location.back());

            expect(location.path()).toBe(LIST);
            expect(page().selected()).toBeNull();
            expect(inbox().classList).not.toContain('inbox--thread-open');
            expect(inbox().classList).not.toContain('inbox--animated');
        });

        it('puts a started test conversation in the URL with an entry of its own', async () => {
            chatApi.createTestConversation.mockReturnValue(
                of({ conversation: row('t-1', { is_test: true }), visitor_token: 'vt-1' })
            );
            await open('/chat-bindings/b-1');

            (host().querySelector('.phone-bar [aria-label="Test"]') as HTMLButtonElement).click();
            await settle();

            expect(location.urlChanges).toEqual(['/chat-bindings/b-1?conversation=t-1']);
            expect((location.getState() as Record<string, unknown>)['chatThreadEntry']).toBe(true);
            expect(page().selected()?.id).toBe('t-1');
        });

        it("goes back to the list's own entry with the thread's Back", async () => {
            await open(LIST);
            rows()[0].click();
            await settle();

            (host().querySelector('.thread-header__back') as HTMLButtonElement).click();
            await historyMove(() => undefined);

            expect(location.path()).toBe(LIST);
            expect(page().selected()).toBeNull();
            expect(inbox().classList).toContain('inbox--animated');
        });

        it('still pushes after a reload names a conversation the list has not resolved, and back does not reopen it', async () => {
            // Bot never answers (a slow network): the reloaded id stays unresolved; Waiting has a row to tap.
            listing([], (section) => (section === 'bot' ? null : section === 'waiting' ? [row('c-9')] : []));
            await open(`${LIST}?conversation=c-1`);
            expect(page().selected()).toBeNull();

            rows()[0].click();
            await settle();

            expect(location.urlChanges).toEqual([`replace: ${LIST}`, `${LIST}?conversation=c-9`]);
            expect(inbox().classList).toContain('inbox--animated');

            await historyMove(() => location.back());
            expect(location.path()).toBe(LIST);
            expect(page().selectedId()).toBeNull();
            expect(inbox().classList).not.toContain('inbox--thread-open');
        });
    });
});
