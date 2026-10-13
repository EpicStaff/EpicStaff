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
import { ConversationListComponent } from './conversation-list.component';
import { ConversationListStore } from './conversation-list.store';

// The rows' Take over button collapses its label on overflow, which jsdom cannot measure.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

const row = (overrides: Partial<ChatConversation>): ChatConversation => ({
    id: 'c-1',
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
    last_message_preview: 'hello',
    handoff_reason: '',
    handoff_at: null,
    visitor_number: 1,
    chat_user_id: null,
    assigned_operator_name: null,
    last_message_role: 'user',
    last_message_author_user_id: null,
    last_message_author_name: null,
    visitor_waiting_since: null,
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

const page = (results: ChatConversation[], next_cursor: string | null = null): Observable<ChatConversationPage> =>
    of({ results, next_cursor });

const desk: ChatBinding = {
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

describe('ConversationListComponent', () => {
    let fixture: ComponentFixture<ConversationListComponent>;
    let serverDesks: ChatBinding[] = [];
    const conversationUpdated$ = new Subject<ChatConversation>();
    const readyEpoch = signal(0);
    const chatApi = {
        getBindings: vi.fn(() => of(serverDesks)),
        // By default the human section is empty and the bot section holds one conversation.
        getConversations: vi.fn(
            (params: ConversationListParams): Observable<ChatConversationPage> =>
                page(params.section === 'bot' ? [row({ id: 'c-1' })] : [])
        ),
        claim: vi.fn(),
        release: vi.fn(),
    };
    const permissions: { can: (resource: ResourceCode, action: ActionCode) => boolean } = {
        can: (resource, action) => resource === ResourceCode.Chats && action === ActionCode.Use,
    };

    const host = (): HTMLElement => fixture.nativeElement as HTMLElement;
    const store = (): ConversationListStore => fixture.debugElement.injector.get(ConversationListStore);
    const ids = (section: ChatInboxSection): string[] =>
        store()
            .sections()
            [section].rows.map((item) => item.id);
    const rowButtons = (): HTMLButtonElement[] =>
        Array.from(host().querySelectorAll<HTMLButtonElement>('button.conversation-row'));

    function text(selector: string): string[] {
        return Array.from(host().querySelectorAll(selector)).map(
            (node) => node.textContent?.replace(/\s+/g, ' ').trim() ?? ''
        );
    }

    /** A reload requests the human section first, then the bot section. */
    function reloadWith(human: Observable<ChatConversationPage>, bot: Observable<ChatConversationPage>): void {
        chatApi.getConversations.mockReturnValueOnce(human).mockReturnValueOnce(bot);
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

    function expandBot(): void {
        store().toggle('bot');
        fixture.detectChanges();
    }

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        vi.clearAllMocks();
        serverDesks = [];
        TestBed.configureTestingModule({
            imports: [ConversationListComponent],
            providers: [
                { provide: ChatApiService, useValue: chatApi },
                { provide: ChatInboxStreamService, useValue: { conversationUpdated$, readyEpoch } },
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
        vi.unstubAllGlobals();
        localStorage.clear();
    });

    describe('sections', () => {
        it('loads every section without waiting for the stream and reloads them all when the stream becomes ready', () => {
            const sections = () => chatApi.getConversations.mock.calls.map(([params]) => params.section);
            expect(sections()).toEqual(['human', 'bot', 'test']);
            readyEpoch.update((value) => value + 1);
            fixture.detectChanges();
            expect(sections()).toEqual(['human', 'bot', 'test', 'human', 'bot', 'test']);
        });

        it('shows Needs a human, Bot and Tests headers in that order with Bot and Tests collapsed until toggled', () => {
            const expandedStates = () =>
                Array.from(host().querySelectorAll('.header__toggle')).map((node) =>
                    node.getAttribute('aria-expanded')
                );
            expect(text('.header__label')).toEqual(['Needs a human', 'Bot', 'Tests']);
            expect(expandedStates()).toEqual(['true', 'false', 'false']);
            expect(text('.conversation-row__preview')).toEqual([]);

            (host().querySelectorAll('.header__toggle')[1] as HTMLButtonElement).click();
            fixture.detectChanges();

            expect(expandedStates()).toEqual(['true', 'true', 'false']);
            expect(text('.conversation-row__preview')).toEqual(['hello']);
        });

        it('fills with the lowest expanded section and rests a collapsed Bot at the bottom', () => {
            const layout = () =>
                Array.from(host().querySelectorAll('.conversation-list__section')).map((section) =>
                    ['fill', 'bottom-anchor'].filter((mod) =>
                        section.classList.contains(`conversation-list__section--${mod}`)
                    )
                );
            expect(layout()).toEqual([['fill'], ['bottom-anchor'], []]);

            store().toggle('human');
            fixture.detectChanges();
            expect(layout()).toEqual([[], ['bottom-anchor'], []]);

            expandBot();
            expect(layout()).toEqual([[], ['fill'], ['bottom-anchor']]);

            store().toggle('human');
            fixture.detectChanges();
            expect(layout()).toEqual([[], ['fill'], ['bottom-anchor']]);
        });

        it('hides Needs a human for a desk without handoff only while nothing waits there', () => {
            const desks = [desk, { ...desk, id: 'b-2', name: 'No handoff', handoff_enabled: false }];
            listDesks(desks);
            fixture.detectChanges();
            expect(text('.header__label')).toEqual(['Needs a human', 'Bot', 'Tests']);

            scopeTo('b-2');
            expect(text('.header__label')).toEqual(['Bot', 'Tests']);

            // Handed off before handoff was turned off: still reachable.
            reloadWith(page([handedOff('h-1', '2026-10-10T08:00:00Z', { binding_id: 'b-2' })]), page([]));
            expect(text('.header__label')).toEqual(['Needs a human', 'Bot', 'Tests']);

            scopeTo('b-1');
            expect(text('.header__label')).toEqual(['Needs a human', 'Bot', 'Tests']);

            scopeTo('');
            listDesks([{ ...desk, handoff_enabled: false }]);
            fixture.detectChanges();
            expect(text('.header__label')).toEqual(['Needs a human', 'Bot', 'Tests']);
        });

        it('rests a collapsed Bot at the bottom when Needs a human is hidden', () => {
            listDesks([{ ...desk, id: 'b-2', handoff_enabled: false }]);
            scopeTo('b-2');
            const sections = () => Array.from(host().querySelectorAll('.conversation-list__section'));
            expect(text('.header__label')).toEqual(['Bot', 'Tests']);
            expect(sections()[0].classList.contains('conversation-list__section--bottom-anchor')).toBe(true);

            expandBot();
            expect(sections()[0].classList.contains('conversation-list__section--bottom-anchor')).toBe(false);
            expect(sections()[0].classList.contains('conversation-list__section--fill')).toBe(true);
        });

        it('decides on Needs a human only once the human page of the new desk has landed', () => {
            // Rows of the previous scope are still listed while the new one loads.
            reloadWith(page([handedOff('h-1', '2026-10-10T08:00:00Z')]), page([]));
            listDesks([
                { ...desk, id: 'b-2', handoff_enabled: false },
                { ...desk, id: 'b-3', handoff_enabled: false },
            ]);
            const pendingB2 = new Subject<ChatConversationPage>();
            chatApi.getConversations.mockReturnValueOnce(pendingB2).mockReturnValueOnce(page([]));
            scopeTo('b-2');
            expect(text('.header__label')).toEqual(['Needs a human', 'Bot', 'Tests']);

            pendingB2.next({ results: [], next_cursor: null });
            fixture.detectChanges();
            expect(text('.header__label')).toEqual(['Bot', 'Tests']);

            const pendingB3 = new Subject<ChatConversationPage>();
            chatApi.getConversations.mockReturnValueOnce(pendingB3).mockReturnValueOnce(page([]));
            scopeTo('b-3');
            expect(text('.header__label')).toEqual(['Bot', 'Tests']);

            pendingB3.next({
                results: [handedOff('h-3', '2026-10-10T08:00:00Z', { binding_id: 'b-3' })],
                next_cursor: null,
            });
            fixture.detectChanges();
            expect(text('.header__label')).toEqual(['Needs a human', 'Bot', 'Tests']);
        });

        it('keeps Needs a human hidden for a desk without handoff when only its tests were handed off', () => {
            listDesks([{ ...desk, id: 'b-2', handoff_enabled: false }]);
            scopeTo('b-2');
            conversationUpdated$.next(
                row({
                    id: 't-1',
                    binding_id: 'b-2',
                    is_test: true,
                    mode: 'awaiting_human',
                    handoff_at: '2026-10-10T10:00:00Z',
                })
            );
            fixture.detectChanges();
            expect(text('.header__label')).toEqual(['Bot', 'Tests']);
        });

        it('expands a section on request, e.g. Tests when a test conversation starts', () => {
            expect(store().expanded().test).toBe(false);
            fixture.componentInstance.reveal('test');
            expect(store().expanded()).toEqual({ human: true, bot: false, test: true });
        });
    });

    describe('live rows', () => {
        it('moves a bot conversation that is handed off to the end of the human section', () => {
            reloadWith(
                page([handedOff('h-1', '2026-10-10T08:00:00Z'), handedOff('h-2', '2026-10-10T09:00:00Z')]),
                page([row({ id: 'c-1' })])
            );

            conversationUpdated$.next(row({ id: 'c-1', mode: 'awaiting_human', handoff_at: '2026-10-10T11:00:00Z' }));

            expect(ids('bot')).toEqual([]);
            expect(ids('human')).toEqual(['h-1', 'h-2', 'c-1']);
        });

        it('keeps a human conversation in place when a new message arrives on it', () => {
            reloadWith(
                page([handedOff('h-1', '2026-10-10T08:00:00Z'), handedOff('h-2', '2026-10-10T09:00:00Z')]),
                page([])
            );

            conversationUpdated$.next(
                handedOff('h-1', '2026-10-10T08:00:00Z', { mode: 'human', last_message_at: '2026-10-10T12:00:00Z' })
            );

            expect(ids('human')).toEqual(['h-1', 'h-2']);
        });

        it('keeps a live test conversation in Tests as it moves from bot to awaiting to human', () => {
            for (const mode of ['bot', 'awaiting_human', 'human'] as const) {
                conversationUpdated$.next(
                    row({ id: 't-1', is_test: true, mode, handoff_at: mode === 'bot' ? null : '2026-10-10T10:00:00Z' })
                );
                expect(ids('test')).toEqual(['t-1']);
                expect(ids('human')).toEqual([]);
                expect(ids('bot')).toEqual(['c-1']);
            }
        });

        it('moves a released conversation from the human section to the bot section', () => {
            reloadWith(page([handedOff('h-1', '2026-10-10T08:00:00Z', { mode: 'human' })]), page([row({ id: 'c-1' })]));

            conversationUpdated$.next(row({ id: 'h-1', last_message_at: '2026-10-10T12:00:00Z' }));

            expect(ids('human')).toEqual([]);
            expect(ids('bot')).toEqual(['h-1', 'c-1']);
        });

        it('keeps the open conversation marked when it moves to the other section', () => {
            expandBot();
            select('c-1');

            conversationUpdated$.next(row({ id: 'c-1', mode: 'awaiting_human', handoff_at: '2026-10-10T11:00:00Z' }));
            fixture.detectChanges();

            expect(ids('human')).toEqual(['c-1']);
            const marked = rowButtons().filter((button) => button.getAttribute('aria-current') === 'true');
            expect(marked.length).toBe(1);
            expect(
                marked[0].closest('.conversation-list__section')?.querySelector('.header__label')?.textContent
            ).toContain('Needs a human');
        });

        it('lists only conversations of the desk shown', () => {
            scopeTo('b-2');
            conversationUpdated$.next(row({ id: 'c-9', binding_id: 'b-1' }));
            expect(ids('bot')).not.toContain('c-9');
        });

        it('does not list a streamed conversation without messages until its first message', () => {
            expandBot();
            store().toggle('test');
            fixture.detectChanges();
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
            expandBot();
            const page$ = new Subject<ChatConversationPage>();
            reloadWith(page([]), page$);
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
            reloadWith(
                page([]),
                page(
                    [
                        row({ id: 'c-a', last_message_at: '2026-10-10T10:00:00.123456Z' }),
                        row({ id: 'c-b', last_message_at: '2026-10-10T10:00:00.123400Z' }),
                    ],
                    'bot-2'
                )
            );
            expect(ids('bot')).toEqual(['c-a', 'c-b']);
        });

        it('cancels a page still in flight when the desk changes', () => {
            const stale$ = new Subject<ChatConversationPage>();
            reloadWith(page([]), stale$);
            expect(stale$.observed).toBe(true);

            scopeTo('b-2');

            expect(stale$.observed).toBe(false);
            stale$.next({ results: [row({ id: 'c-stale' })], next_cursor: null });
            expect(ids('bot')).toEqual(['c-1']);
        });

        it('reloads every section when the desk changes', () => {
            chatApi.getConversations.mockClear();
            scopeTo('b-2');
            expect(chatApi.getConversations.mock.calls.map(([params]) => params)).toEqual([
                { section: 'human', binding: 'b-2', cursor: null },
                { section: 'bot', binding: 'b-2', cursor: null },
                { section: 'test', binding: 'b-2', cursor: null },
            ]);
        });
    });

    describe('Load more', () => {
        it("loads more of one section with that section's cursor, and only while it is expanded", () => {
            reloadWith(
                page([handedOff('h-1', '2026-10-10T08:00:00Z')], 'human-2'),
                page([row({ id: 'c-1' })], 'bot-2')
            );
            expect(text('.conversation-list__more')).toEqual(['Load more']);
            expandBot();
            expect(text('.conversation-list__more')).toEqual(['Load more', 'Load more']);

            chatApi.getConversations.mockReturnValueOnce(page([]));
            (host().querySelectorAll('.conversation-list__more button')[1] as HTMLButtonElement).click();

            expect(chatApi.getConversations).toHaveBeenLastCalledWith({
                section: 'bot',
                binding: null,
                cursor: 'bot-2',
            });
        });

        it('loads more Tests with the Tests cursor', () => {
            chatApi.getConversations
                .mockReturnValueOnce(page([]))
                .mockReturnValueOnce(page([]))
                .mockReturnValueOnce(page([row({ id: 't-1', is_test: true })], 'test-2'));
            readyEpoch.update((value) => value + 1);
            fixture.detectChanges();
            store().toggle('test');
            fixture.detectChanges();
            expect(text('.conversation-list__more')).toEqual(['Load more']);

            chatApi.getConversations.mockReturnValueOnce(page([]));
            store().loadMore('test');
            expect(chatApi.getConversations).toHaveBeenLastCalledWith({
                section: 'test',
                binding: null,
                cursor: 'test-2',
            });
        });

        it('drops a live handoff past the human boundary and lists it when Load more reaches it', () => {
            reloadWith(page([handedOff('h-1', '2026-10-10T08:00:00Z')], 'human-2'), page([]));

            conversationUpdated$.next(row({ id: 'c-5', mode: 'awaiting_human', handoff_at: '2026-10-10T11:00:00Z' }));
            expect(ids('human')).toEqual(['h-1']);

            chatApi.getConversations.mockReturnValueOnce(
                page([handedOff('h-2', '2026-10-10T09:00:00Z'), handedOff('c-5', '2026-10-10T11:00:00Z')])
            );
            store().loadMore('human');
            expect(ids('human')).toEqual(['h-1', 'h-2', 'c-5']);
        });

        it('keeps a handoff that arrives while a Load more request is in flight', () => {
            reloadWith(page([handedOff('h-1', '2026-10-10T08:00:00Z')], 'human-2'), page([]));
            const more$ = new Subject<ChatConversationPage>();
            chatApi.getConversations.mockReturnValueOnce(more$);
            store().loadMore('human');

            conversationUpdated$.next(row({ id: 'c-5', mode: 'awaiting_human', handoff_at: '2026-10-10T11:00:00Z' }));
            more$.next({ results: [handedOff('h-2', '2026-10-10T09:00:00Z')], next_cursor: null });

            expect(ids('human')).toEqual(['h-1', 'h-2', 'c-5']);
        });

        it('lists a row returned by two pages once, the later page winning', () => {
            reloadWith(
                page([]),
                page(
                    [
                        row({ id: 'c-1', last_message_preview: 'first copy' }),
                        row({ id: 'c-2', last_message_at: '2026-10-10T09:00:00Z', last_message_preview: 'older' }),
                    ],
                    'cursor-2'
                )
            );
            expandBot();
            expect(text('.conversation-list__more')).toEqual(['Load more']);

            chatApi.getConversations.mockReturnValueOnce(
                page([
                    row({ id: 'c-1', last_message_preview: 'later copy' }),
                    row({ id: 'c-3', last_message_at: '2026-10-10T08:00:00Z', last_message_preview: 'oldest' }),
                ])
            );
            store().loadMore('bot');
            fixture.detectChanges();

            expect(chatApi.getConversations).toHaveBeenLastCalledWith({
                section: 'bot',
                binding: null,
                cursor: 'cursor-2',
            });
            expect(text('.conversation-row__preview')).toEqual(['later copy', 'older', 'oldest']);
            expect(store().sections().bot.nextCursor).toBeNull();
            expect(text('.conversation-list__more')).toEqual([]);
        });

        it('keeps a row streamed after the reload when a Load more page brings an older copy', () => {
            reloadWith(page([]), page([row({ id: 'c-1', last_message_preview: 'hello' })], 'cursor-2'));
            expandBot();

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

    describe('rows', () => {
        function listBotRows(rows: ChatConversation[]): void {
            reloadWith(page([]), page(rows));
            expandBot();
        }

        it('opens a conversation when its row is clicked', () => {
            const opened: ChatConversation[] = [];
            fixture.componentInstance.selectedChange.subscribe((conversation) => opened.push(conversation));
            expandBot();
            rowButtons()[0].click();
            expect(opened.map(({ id }) => id)).toEqual(['c-1']);
        });

        it('names the desk under each visitor on All desks only', () => {
            listDesks([desk]);
            expandBot();
            expect(text('.conversation-row__desk')).toEqual(['Support']);

            scopeTo('b-1');
            expect(text('.conversation-row__preview')).toEqual(['hello']);
            expect(text('.conversation-row__desk')).toEqual([]);
        });

        it('makes one row the Tab stop: the open one when shown, else the first', () => {
            listBotRows([
                row({ id: 'c-1' }),
                row({ id: 'c-2', last_message_at: '2026-10-10T09:00:00Z' }),
                row({ id: 'c-3', last_message_at: '2026-10-10T08:00:00Z' }),
            ]);
            const tabIndexes = () => rowButtons().map((button) => button.tabIndex);
            expect(tabIndexes()).toEqual([0, -1, -1]);

            select('c-2');
            expect(tabIndexes()).toEqual([-1, 0, -1]);
        });

        it('moves the focus and the selection with ↑, ↓, Home and End across the rows shown', () => {
            reloadWith(
                page([handedOff('h-1', '2026-10-10T08:00:00Z')]),
                page([row({ id: 'c-1' }), row({ id: 'c-2', last_message_at: '2026-10-10T09:00:00Z' })])
            );
            expandBot();
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
        });

        it('takes a waiting conversation over from its row and shows the result at once, without opening it', () => {
            const opened = vi.fn();
            fixture.componentInstance.selectedChange.subscribe(opened);
            reloadWith(page([handedOff('h-1', '2026-10-10T08:00:00Z')]), page([]));
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
            reloadWith(page([handedOff('h-1', '2026-10-10T08:00:00Z')]), page([]));
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
            expect(host().querySelector('.conversation-row__take-over')).toBeNull();
            expect(document.activeElement).toBe(rowButtons()[0]);
        });

        it('offers no Take over without chats use', () => {
            permissions.can = () => false;
            try {
                fixture = TestBed.createComponent(ConversationListComponent);
                fixture.detectChanges();
                reloadWith(page([handedOff('h-1', '2026-10-10T08:00:00Z')]), page([]));
                expect(rowButtons().length).toBe(1);
                expect(host().querySelector('.conversation-row__take-over')).toBeNull();
            } finally {
                permissions.can = (resource, action) => resource === ResourceCode.Chats && action === ActionCode.Use;
            }
        });

        it('says once, politely, that the bot started replying in the open conversation', () => {
            expandBot();
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
            store().toggle('bot');
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
});
