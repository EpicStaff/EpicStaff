import { Dialog } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatTooltip } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';
import { provideRouter, Router } from '@angular/router';
import { ConfirmationDialogService } from '@shared/components';
import { ActionCode, ResourceCode } from '@shared/models';
import { Observable, of, Subject, throwError } from 'rxjs';

import { ActiveOrgService } from '../../../../services/auth/active-org.service';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ProfileService } from '../../../../services/auth/profile.service';
import { ToastService } from '../../../../services/notifications';
import { ChatBindingsDialogComponent } from '../../components/chat-bindings-dialog/chat-bindings-dialog.component';
import {
    CHAT_BINDING_DEFAULTS,
    ChatBinding,
    ChatConversation,
    ChatConversationPage,
    ChatInboxMessageEvent,
    ChatInboxSection,
    ChatOperatorMessage,
} from '../../models/chat.model';
import { CHAT_MESSAGES_PAGE_SIZE, ChatApiService, ConversationListParams } from '../../services/chat-api.service';
import { ChatBindingActionsService } from '../../services/chat-binding-actions.service';
import { ChatInboxStreamService } from '../../services/chat-inbox-stream.service';
import { ChatPageComponent } from './chat-page.component';

class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

/** Records every observer so a spec can report the sentinel entering the thread viewport. */
class IntersectionObserverStub {
    static instances: IntersectionObserverStub[] = [];
    readonly observed: Element[] = [];
    disconnected = false;

    constructor(private readonly callback: (entries: Partial<IntersectionObserverEntry>[]) => void) {
        IntersectionObserverStub.instances.push(this);
    }

    observe(target: Element): void {
        this.observed.push(target);
    }

    disconnect(): void {
        this.disconnected = true;
    }

    intersect(): void {
        this.callback(this.observed.map((target) => ({ target, isIntersecting: true })));
    }

    /** The live observer of the current sentinel. */
    static current(): IntersectionObserverStub {
        return IntersectionObserverStub.instances.filter((instance) => !instance.disconnected).at(-1)!;
    }
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
    ...overrides,
});

const handedOff = (id: string, handoffAt: string, overrides: Partial<ChatConversation> = {}): ChatConversation =>
    row({ id, mode: 'awaiting_human', handoff_at: handoffAt, last_message_preview: id, ...overrides });

const page = (results: ChatConversation[], next_cursor: string | null = null): Observable<ChatConversationPage> =>
    of({ results, next_cursor });

const binding: ChatBinding = {
    ...CHAT_BINDING_DEFAULTS,
    id: 'b-1',
    org_id: 1,
    graph_id: 5,
    name: 'Support',
    bot_display_name: 'Support',
    public_key: 'pk',
    is_active: true,
    max_turns: 50,
    token_budget_per_conversation: 1000,
    daily_token_budget: 1_000_000,
    broken_reason: null,
    contract_errors: [],
    created_at: '',
    updated_at: '',
};

describe('ChatPageComponent', () => {
    // What the bindings endpoint returns; the page reloads it on every ready and on every route binding.
    let serverBindings: ChatBinding[] = [];
    let fixture: ComponentFixture<ChatPageComponent>;
    let navigate: ReturnType<typeof vi.spyOn>;
    const conversationUpdated$ = new Subject<ChatConversation>();
    const messageCreated$ = new Subject<ChatInboxMessageEvent>();
    const readyEpoch = signal(0);
    const chatApi = {
        getBindings: vi.fn(() => of(serverBindings)),
        // By default the human section is empty and the bot section holds one conversation.
        getConversations: vi.fn(
            (params: ConversationListParams): Observable<ChatConversationPage> =>
                page(params.section === 'bot' ? [row({ id: 'c-1' })] : [])
        ),
        getMessages: vi.fn(() => of([] as ChatOperatorMessage[])),
        createTestConversation: vi.fn(),
        issueVisitorToken: vi.fn(),
        sendAsVisitor: vi.fn(),
        claim: vi.fn(),
        release: vi.fn(),
        reply: vi.fn(),
    };
    const confirmation = { confirm: vi.fn() };
    const permissions: { can: (resource: ResourceCode, action: ActionCode) => boolean } = {
        can: (resource, action) => resource === ResourceCode.Chats && action === ActionCode.Use,
    };
    const dialog = { open: vi.fn() };
    const bindingActions = { pause: vi.fn(), resume: vi.fn(), copySnippet: vi.fn() };

    function text(selector: string): string[] {
        const host: HTMLElement = fixture.nativeElement;
        return Array.from(host.querySelectorAll(selector)).map(
            (node) => node.textContent?.replace(/\s+/g, ' ').trim() ?? ''
        );
    }

    const ids = (section: ChatInboxSection): string[] =>
        fixture.componentInstance.inbox()[section].rows.map((item) => item.id);

    /** A reload requests the human section first, then the bot section. */
    function reloadWith(human: Observable<ChatConversationPage>, bot: Observable<ChatConversationPage>): void {
        chatApi.getConversations.mockReturnValueOnce(human).mockReturnValueOnce(bot);
        readyEpoch.update((value) => value + 1);
        fixture.detectChanges();
    }

    const composerInput = (): HTMLInputElement =>
        (fixture.nativeElement as HTMLElement).querySelector('.composer input') as HTMLInputElement;

    function typeInComposer(value: string): void {
        const input = composerInput();
        input.value = value;
        input.dispatchEvent(new Event('input'));
        fixture.detectChanges();
    }

    const headerButton = (label: string): HTMLButtonElement | undefined =>
        Array.from(
            (fixture.nativeElement as HTMLElement).querySelectorAll<HTMLButtonElement>('.header-actions button')
        ).find((button) => button.textContent?.trim() === label);

    /** The route's binding id, as the router binds it; '' is the all-bindings inbox. */
    function scopeTo(bindingId: string): void {
        fixture.componentRef.setInput('bindingId', bindingId || undefined);
        fixture.detectChanges();
    }

    function listBindings(bindings: ChatBinding[]): void {
        serverBindings = bindings;
        fixture.componentInstance.bindings.set(bindings);
    }

    function expandBot(): void {
        fixture.componentInstance.toggleSection('bot');
        fixture.detectChanges();
    }

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        vi.stubGlobal('IntersectionObserver', IntersectionObserverStub);
        IntersectionObserverStub.instances = [];
        vi.clearAllMocks();
        serverBindings = [];
        TestBed.configureTestingModule({
            imports: [ChatPageComponent],
            providers: [
                provideRouter([]),
                { provide: ChatApiService, useValue: chatApi },
                { provide: ChatBindingActionsService, useValue: bindingActions },
                {
                    provide: ChatInboxStreamService,
                    useValue: { conversationUpdated$, messageCreated$, readyEpoch, status: signal('open') },
                },
                { provide: ProfileService, useValue: { currentUserSignal: signal({ id: 3 }) } },
                { provide: PermissionsService, useValue: permissions },
                { provide: ConfirmationDialogService, useValue: confirmation },
                { provide: ToastService, useValue: { error: vi.fn(), success: vi.fn() } },
                { provide: Dialog, useValue: dialog },
            ],
        });
        navigate = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
        fixture = TestBed.createComponent(ChatPageComponent);
        fixture.detectChanges();
    });

    afterEach(() => vi.unstubAllGlobals());

    it('loads every section without waiting for the stream and reloads them all when the stream becomes ready', () => {
        const sections = () => chatApi.getConversations.mock.calls.map(([params]) => params.section);
        expect(sections()).toEqual(['human', 'bot', 'test']);
        readyEpoch.update((value) => value + 1);
        fixture.detectChanges();
        expect(sections()).toEqual(['human', 'bot', 'test', 'human', 'bot', 'test']);
    });

    it('shows Needs a human, Bot and Tests headers in that order with Bot and Tests collapsed until toggled', () => {
        const host: HTMLElement = fixture.nativeElement;
        const expandedStates = () =>
            Array.from(host.querySelectorAll('.header__toggle')).map((node) => node.getAttribute('aria-expanded'));
        expect(text('.header__label')).toEqual(['Needs a human', 'Bot', 'Tests']);
        expect(expandedStates()).toEqual(['true', 'false', 'false']);
        expect(text('.conversation__preview')).toEqual([]);

        (host.querySelectorAll('.header__toggle')[1] as HTMLButtonElement).click();
        fixture.detectChanges();

        expect(expandedStates()).toEqual(['true', 'true', 'false']);
        expect(text('.conversation__preview')).toEqual(['hello']);
    });

    it('fills with the lowest expanded section and rests a collapsed Bot at the bottom', () => {
        const host: HTMLElement = fixture.nativeElement;
        const layout = () =>
            Array.from(host.querySelectorAll('.inbox__section')).map((section) =>
                ['fill', 'bottom-anchor'].filter((mod) => section.classList.contains(`inbox__section--${mod}`))
            );
        expect(layout()).toEqual([['fill'], ['bottom-anchor'], []]);

        fixture.componentInstance.toggleSection('human');
        fixture.detectChanges();
        expect(layout()).toEqual([[], ['bottom-anchor'], []]);

        expandBot();
        expect(layout()).toEqual([[], ['fill'], ['bottom-anchor']]);

        fixture.componentInstance.toggleSection('human');
        fixture.detectChanges();
        expect(layout()).toEqual([[], ['fill'], ['bottom-anchor']]);
    });

    it('hides Needs a human for a binding without handoff only while nothing waits there', () => {
        const component = fixture.componentInstance;
        const bindings = [binding, { ...binding, id: 'b-2', name: 'No handoff', handoff_enabled: false }];
        listBindings(bindings);
        fixture.detectChanges();
        expect(text('.header__label')).toEqual(['Needs a human', 'Bot', 'Tests']);

        scopeTo('b-2');
        fixture.detectChanges();
        expect(text('.header__label')).toEqual(['Bot', 'Tests']);

        // Handed off before handoff was turned off: still reachable. A stream ready also reloads the bindings.
        chatApi.getBindings.mockReturnValueOnce(of(bindings));
        reloadWith(page([handedOff('h-1', '2026-10-10T08:00:00Z', { binding_id: 'b-2' })]), page([]));
        expect(component.bindingFilter()).toBe('b-2');
        expect(text('.header__label')).toEqual(['Needs a human', 'Bot', 'Tests']);

        scopeTo('b-1');
        fixture.detectChanges();
        expect(text('.header__label')).toEqual(['Needs a human', 'Bot', 'Tests']);

        scopeTo('');
        listBindings([{ ...binding, handoff_enabled: false }]);
        fixture.detectChanges();
        expect(text('.header__label')).toEqual(['Needs a human', 'Bot', 'Tests']);
    });

    it('rests a collapsed Bot at the bottom when Needs a human is hidden', () => {
        const host: HTMLElement = fixture.nativeElement;
        listBindings([{ ...binding, id: 'b-2', handoff_enabled: false }]);
        scopeTo('b-2');
        fixture.detectChanges();
        const sections = () => Array.from(host.querySelectorAll('.inbox__section'));
        expect(text('.header__label')).toEqual(['Bot', 'Tests']);
        expect(sections()[0].classList.contains('inbox__section--bottom-anchor')).toBe(true);

        expandBot();
        expect(sections()[0].classList.contains('inbox__section--bottom-anchor')).toBe(false);
        expect(sections()[0].classList.contains('inbox__section--fill')).toBe(true);
    });

    it('decides on Needs a human only once the human page of the new filter has landed', () => {
        // Rows of the previous filter are still listed while the new one loads.
        reloadWith(page([handedOff('h-1', '2026-10-10T08:00:00Z')]), page([]));
        // After the reload: a stream ready also reloads the bindings, which the stub returns empty.
        listBindings([
            { ...binding, id: 'b-2', handoff_enabled: false },
            { ...binding, id: 'b-3', handoff_enabled: false },
        ]);
        const pendingB2 = new Subject<ChatConversationPage>();
        chatApi.getConversations.mockReturnValueOnce(pendingB2).mockReturnValueOnce(page([]));
        scopeTo('b-2');
        fixture.detectChanges();
        expect(text('.header__label')).toEqual(['Needs a human', 'Bot', 'Tests']);

        pendingB2.next({ results: [], next_cursor: null });
        fixture.detectChanges();
        expect(text('.header__label')).toEqual(['Bot', 'Tests']);

        const pendingB3 = new Subject<ChatConversationPage>();
        chatApi.getConversations.mockReturnValueOnce(pendingB3).mockReturnValueOnce(page([]));
        scopeTo('b-3');
        fixture.detectChanges();
        expect(text('.header__label')).toEqual(['Bot', 'Tests']);

        pendingB3.next({
            results: [handedOff('h-3', '2026-10-10T08:00:00Z', { binding_id: 'b-3' })],
            next_cursor: null,
        });
        fixture.detectChanges();
        expect(text('.header__label')).toEqual(['Needs a human', 'Bot', 'Tests']);
    });

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

    it("loads more of one section with that section's cursor, and only while it is expanded", () => {
        reloadWith(page([handedOff('h-1', '2026-10-10T08:00:00Z')], 'human-2'), page([row({ id: 'c-1' })], 'bot-2'));
        expect(text('.inbox__more')).toEqual(['Load more']);
        expandBot();
        expect(text('.inbox__more')).toEqual(['Load more', 'Load more']);

        chatApi.getConversations.mockReturnValueOnce(page([]));
        fixture.componentInstance.loadMoreConversations('bot');

        expect(chatApi.getConversations).toHaveBeenLastCalledWith({ section: 'bot', binding: null, cursor: 'bot-2' });
    });

    it('loads more Tests with the Tests cursor', () => {
        chatApi.getConversations
            .mockReturnValueOnce(page([]))
            .mockReturnValueOnce(page([]))
            .mockReturnValueOnce(page([row({ id: 't-1', is_test: true })], 'test-2'));
        readyEpoch.update((value) => value + 1);
        fixture.detectChanges();
        fixture.componentInstance.toggleSection('test');
        fixture.detectChanges();
        expect(text('.inbox__more')).toEqual(['Load more']);

        chatApi.getConversations.mockReturnValueOnce(page([]));
        fixture.componentInstance.loadMoreConversations('test');
        expect(chatApi.getConversations).toHaveBeenLastCalledWith({ section: 'test', binding: null, cursor: 'test-2' });
    });

    it('keeps a live test conversation in Tests as it moves from bot to awaiting to human', () => {
        const ids = (section: ChatInboxSection) =>
            fixture.componentInstance.inbox()[section].rows.map((item) => item.id);
        for (const mode of ['bot', 'awaiting_human', 'human'] as const) {
            conversationUpdated$.next(
                row({ id: 't-1', is_test: true, mode, handoff_at: mode === 'bot' ? null : '2026-10-10T10:00:00Z' })
            );
            expect(ids('test')).toEqual(['t-1']);
            expect(ids('human')).toEqual([]);
            expect(ids('bot')).toEqual(['c-1']);
        }
    });

    it('keeps Needs a human hidden for a binding without handoff when only its tests were handed off', () => {
        listBindings([{ ...binding, id: 'b-2', handoff_enabled: false }]);
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

    it('drops a live handoff past the human boundary and lists it when Load more reaches it', () => {
        reloadWith(page([handedOff('h-1', '2026-10-10T08:00:00Z')], 'human-2'), page([]));

        conversationUpdated$.next(row({ id: 'c-5', mode: 'awaiting_human', handoff_at: '2026-10-10T11:00:00Z' }));
        expect(ids('human')).toEqual(['h-1']);

        chatApi.getConversations.mockReturnValueOnce(
            page([handedOff('h-2', '2026-10-10T09:00:00Z'), handedOff('c-5', '2026-10-10T11:00:00Z')])
        );
        fixture.componentInstance.loadMoreConversations('human');
        expect(ids('human')).toEqual(['h-1', 'h-2', 'c-5']);
    });

    it('keeps a handoff that arrives while a Load more request is in flight', () => {
        reloadWith(page([handedOff('h-1', '2026-10-10T08:00:00Z')], 'human-2'), page([]));
        const more$ = new Subject<ChatConversationPage>();
        chatApi.getConversations.mockReturnValueOnce(more$);
        fixture.componentInstance.loadMoreConversations('human');

        conversationUpdated$.next(row({ id: 'c-5', mode: 'awaiting_human', handoff_at: '2026-10-10T11:00:00Z' }));
        more$.next({ results: [handedOff('h-2', '2026-10-10T09:00:00Z')], next_cursor: null });

        expect(ids('human')).toEqual(['h-1', 'h-2', 'c-5']);
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

    it('moves a released conversation from the human section to the bot section', () => {
        reloadWith(page([handedOff('h-1', '2026-10-10T08:00:00Z', { mode: 'human' })]), page([row({ id: 'c-1' })]));

        conversationUpdated$.next(row({ id: 'h-1', last_message_at: '2026-10-10T12:00:00Z' }));

        expect(ids('human')).toEqual([]);
        expect(ids('bot')).toEqual(['h-1', 'c-1']);
    });

    it('keeps the selection when the selected conversation moves to the other section', () => {
        const component = fixture.componentInstance;
        component.selectConversation('c-1');

        conversationUpdated$.next(row({ id: 'c-1', mode: 'awaiting_human', handoff_at: '2026-10-10T11:00:00Z' }));

        expect(component.selectedId()).toBe('c-1');
        expect(component.selected()?.mode).toBe('awaiting_human');
        expect(ids('human')).toEqual(['c-1']);
    });

    it('cancels a page still in flight when the binding filter changes', () => {
        const stale$ = new Subject<ChatConversationPage>();
        reloadWith(page([]), stale$);
        expect(stale$.observed).toBe(true);

        scopeTo('b-2');
        fixture.detectChanges();

        expect(stale$.observed).toBe(false);
        stale$.next({ results: [row({ id: 'c-stale' })], next_cursor: null });
        expect(ids('bot')).toEqual(['c-1']);
    });

    it('reloads every section when the route binding changes', () => {
        chatApi.getConversations.mockClear();
        scopeTo('b-2');
        fixture.detectChanges();
        expect(chatApi.getConversations.mock.calls.map(([params]) => params)).toEqual([
            { section: 'human', binding: 'b-2', cursor: null },
            { section: 'bot', binding: 'b-2', cursor: null },
            { section: 'test', binding: 'b-2', cursor: null },
        ]);
    });

    it('expands Tests, not Bot, when a test conversation starts', () => {
        const component = fixture.componentInstance;
        expect(component.expanded().test).toBe(false);
        component.onTestConversationStarted(row({ id: 'c-9', is_test: true, last_message_at: null }));
        expect(component.expanded()).toEqual({ human: true, bot: false, test: true });
    });

    it('tests the route binding from the header, expands Tests, selects it and writes as the visitor', () => {
        const component = fixture.componentInstance;
        const created = row({
            id: 'c-9',
            binding_id: 'b-2',
            is_test: true,
            last_message_at: null,
            last_message_preview: '',
        });
        chatApi.createTestConversation.mockReturnValue(of({ visitor_token: 'vt-9', conversation: created }));
        chatApi.sendAsVisitor.mockReturnValue(of({ message_id: 'm-1', state: 'processing' }));
        listBindings([binding, { ...binding, id: 'b-2', name: 'Sales' }]);
        scopeTo('b-2');
        const host: HTMLElement = fixture.nativeElement;
        // The separator is aria-hidden and spaced by CSS.
        expect(text('.title')).toEqual(['Chat/ Sales']);
        expect(text('.header-titles app-chat-binding-status')).toEqual(['Live']);
        expect(fixture.nativeElement.querySelector('h1 app-chat-binding-status')).toBeNull();
        expect(host.querySelector('.inbox__toolbar, app-select')).toBeNull();

        headerButton('Test')!.click();
        fixture.detectChanges();

        expect(chatApi.createTestConversation).toHaveBeenCalledWith('b-2');
        expect(component.expanded().test).toBe(true);
        expect(component.selectedId()).toBe('c-9');
        expect(text('.thread-header .test-chip')).toEqual(['Test']);
        expect(host.querySelector('app-tab-button button[aria-pressed="true"]')?.textContent?.trim()).toBe('Visitor');

        typeInComposer('hi');
        host.querySelector('.composer app-custom-input')?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
        expect(chatApi.sendAsVisitor).toHaveBeenCalledWith('c-9', 'vt-9', 'hi', {});
        expect(chatApi.reply).not.toHaveBeenCalled();
    });

    it('lists only the route binding conversations', () => {
        chatApi.getConversations.mockClear();
        scopeTo('b-2');
        expect(chatApi.getConversations.mock.calls.map(([params]) => params.binding)).toEqual(['b-2', 'b-2', 'b-2']);
    });

    it('shows the all-bindings inbox unscoped, without Settings, Get snippet, Pause or Test', () => {
        listBindings([binding]);
        fixture.detectChanges();
        expect(text('.title')).toEqual(['Chat/ Inbox · all bindings']);
        expect(chatApi.getConversations.mock.calls.map(([params]) => params.binding)).toEqual([null, null, null]);
        expect(fixture.nativeElement.querySelector('.header-actions')).toBeNull();
    });

    it('pauses or resumes the route binding and opens its settings, then reloads it', () => {
        permissions.can = () => true;
        try {
            listBindings([binding]);
            scopeTo('b-1');
            bindingActions.pause.mockReturnValue(of(true));
            headerButton('Pause')!.click();
            expect(bindingActions.pause).toHaveBeenCalledWith(binding);

            const paused = { ...binding, is_active: false };
            serverBindings = [paused];
            listBindings([paused]);
            fixture.detectChanges();
            bindingActions.resume.mockReturnValue(of(true));
            const callsBefore = chatApi.getBindings.mock.calls.length;
            headerButton('Resume')!.click();
            expect(bindingActions.resume).toHaveBeenCalled();
            expect(chatApi.getBindings).toHaveBeenCalledTimes(callsBefore + 1);

            dialog.open.mockReturnValue({ closed: of(undefined) });
            headerButton('Settings')!.click();
            expect(dialog.open).toHaveBeenCalledWith(
                ChatBindingsDialogComponent,
                expect.objectContaining({ data: { binding: { ...binding, is_active: false } } })
            );
            expect(chatApi.getBindings).toHaveBeenCalledTimes(callsBefore + 2);
        } finally {
            permissions.can = (resource, action) => resource === ResourceCode.Chats && action === ActionCode.Use;
        }
    });

    it('draws its header actions as the flow editor header buttons, each named even when collapsed to its icon', () => {
        permissions.can = () => true;
        try {
            listBindings([binding]);
            scopeTo('b-1');
            const buttons = Array.from(
                (fixture.nativeElement as HTMLElement).querySelectorAll<HTMLButtonElement>('.header-actions button')
            );
            expect(
                buttons.map((button) => [
                    button.className.split(' ').slice(0, 2).join(' '),
                    button.getAttribute('aria-label'),
                ])
            ).toEqual([
                ['header-action header-action--ghost', 'Settings'],
                ['header-action header-action--outline', 'Get snippet'],
                ['header-action header-action--outline', 'Pause'],
                ['header-action header-action--primary', 'Test'],
            ]);
        } finally {
            permissions.can = (resource, action) => resource === ResourceCode.Chats && action === ActionCode.Use;
        }
    });

    it('copies the binding snippet from Get snippet through the shared binding actions, for any reader', () => {
        listBindings([binding]);
        scopeTo('b-1');
        headerButton('Get snippet')!.click();
        expect(bindingActions.copySnippet).toHaveBeenCalledWith(binding);
    });

    it('hides Pause and Settings without chats:update and Test without chats:use', () => {
        listBindings([binding]);
        scopeTo('b-1');
        expect(headerButton('Test')).toBeDefined();
        expect(headerButton('Pause')).toBeUndefined();
        expect(headerButton('Settings')).toBeUndefined();

        const can = permissions.can;
        permissions.can = () => false;
        try {
            fixture = TestBed.createComponent(ChatPageComponent);
            listBindings([binding]);
            scopeTo('b-1');
            expect(headerButton('Test')).toBeUndefined();
        } finally {
            permissions.can = can;
        }
    });

    it('sends a binding the route moves to and the server does not list back to the bindings list', () => {
        serverBindings = [binding];
        scopeTo('b-1');
        expect(navigate).not.toHaveBeenCalled();
        expect(text('.title')).toEqual(['Chat/ Support']);

        scopeTo('gone');
        expect(navigate).toHaveBeenCalledWith(['/chat-bindings']);
        expect(TestBed.inject(ToastService).error).toHaveBeenCalledWith('This chat binding does not exist anymore.');
    });

    it('follows the route to another binding: its title, status and actions', () => {
        serverBindings = [binding, { ...binding, id: 'b-2', name: 'Sales', is_active: false }];
        scopeTo('b-1');
        expect(text('.title')).toEqual(['Chat/ Support']);
        scopeTo('b-2');
        expect(text('.title')).toEqual(['Chat/ Sales']);
        expect(text('.header-titles app-chat-binding-status')).toEqual(['Paused']);
        expect(navigate).not.toHaveBeenCalled();
    });

    it('lets only the latest bindings list land when two loads answer out of order', () => {
        const first$ = new Subject<ChatBinding[]>();
        const second$ = new Subject<ChatBinding[]>();
        chatApi.getBindings.mockReturnValueOnce(first$).mockReturnValueOnce(second$);
        scopeTo('b-1');
        scopeTo('b-2');
        second$.next([binding, { ...binding, id: 'b-2', name: 'Sales' }]);
        first$.next([binding]);
        fixture.detectChanges();
        expect(text('.title')).toEqual(['Chat/ Sales']);
        expect(text('.header-titles app-chat-binding-status')).toEqual(['Live']);
        expect(fixture.nativeElement.querySelector('h1 app-chat-binding-status')).toBeNull();
        expect(navigate).not.toHaveBeenCalled();
    });

    it('stays on a binding page when the org is cleared by a logout', () => {
        const activeOrg = TestBed.inject(ActiveOrgService);
        const previousOrg = activeOrg.activeOrgId() ?? 1;
        activeOrg.set(previousOrg);
        serverBindings = [binding];
        fixture = TestBed.createComponent(ChatPageComponent);
        scopeTo('b-1');
        try {
            activeOrg.set(null);
            fixture.detectChanges();
            expect(navigate).not.toHaveBeenCalled();
        } finally {
            activeOrg.set(previousOrg);
        }
    });

    it('hides the breadcrumb separator until the binding name is known', () => {
        scopeTo('b-1');
        expect(text('.title')).toEqual(['Chat']);
        expect(fixture.nativeElement.querySelector('.title__separator')).toBeNull();
    });

    it('goes back to the bindings list without a message when the org changes on a binding page', () => {
        const activeOrg = TestBed.inject(ActiveOrgService);
        const previousOrg = activeOrg.activeOrgId();
        serverBindings = [binding];
        scopeTo('b-1');
        try {
            activeOrg.set((previousOrg ?? 0) + 1);
            // The new org's list does not have the binding.
            serverBindings = [];
            readyEpoch.update((value) => value + 1);
            fixture.detectChanges();
            expect(navigate).toHaveBeenCalledWith(['/chat-bindings']);
            expect(TestBed.inject(ToastService).error).not.toHaveBeenCalled();
        } finally {
            activeOrg.set(previousOrg);
        }
    });

    it('closes the open conversation when the route moves to another binding, not before', () => {
        const component = fixture.componentInstance;
        component.selectConversation('c-1');
        fixture.detectChanges();
        expect(component.selectedId()).toBe('c-1');

        scopeTo('b-2');
        expect(component.selectedId()).toBeNull();
        expect(component.messages()).toEqual([]);
    });

    it('keeps the operator-only composer without a Visitor / Operator switch on a real conversation', () => {
        fixture.componentInstance.selectConversation('c-1');
        fixture.detectChanges();
        const host: HTMLElement = fixture.nativeElement;
        expect(host.querySelector('app-chat-thread-composer')).not.toBeNull();
        expect(host.querySelector('.composer__roles')).toBeNull();
        expect(composerInput().placeholder).toBe('Claim the conversation to reply');
    });

    it('adds an operator reply only to the thread it was sent on', () => {
        const component = fixture.componentInstance;
        component.selectConversation('c-1');
        fixture.detectChanges();
        const message = { id: 'm-a', role: 'operator', content: 'for A' } as ChatOperatorMessage;
        component.onOperatorMessageSent({ conversationId: 'c-a', message });
        expect(component.messages()).toEqual([]);
        component.onOperatorMessageSent({ conversationId: 'c-1', message });
        expect(component.messages()).toEqual([message]);
    });

    it('appends a streamed message to the open thread once', () => {
        fixture.componentInstance.selectConversation('c-1');
        fixture.detectChanges();
        const event: ChatInboxMessageEvent = {
            conversation_id: 'c-1',
            id: 'm-1',
            role: 'assistant',
            content: 'reply',
            actions: null,
            action: null,
            created_at: '2026-10-10T10:01:00Z',
        };
        messageCreated$.next(event);
        messageCreated$.next(event);
        messageCreated$.next({ ...event, id: 'm-2', conversation_id: 'other' });
        fixture.detectChanges();
        expect(text('.message__content')).toEqual(['reply']);
    });

    it('shows a visitor action reply as text, alone when the message has no text, and keeps it through the stream', () => {
        fixture.componentInstance.selectConversation('c-1');
        fixture.detectChanges();
        const event: ChatInboxMessageEvent = {
            conversation_id: 'c-1',
            id: 'm-1',
            role: 'user',
            content: '',
            actions: null,
            action: { type: 'button', label: '<b>Yes</b>' },
            created_at: '2026-10-10T10:01:00Z',
        };
        messageCreated$.next(event);
        messageCreated$.next({
            ...event,
            id: 'm-2',
            content: '<i>why</i>',
            action: { id: 'more' },
            created_at: '2026-10-10T10:02:00Z',
        });
        fixture.detectChanges();

        expect(fixture.componentInstance.messages()[0].action).toEqual({ type: 'button', label: '<b>Yes</b>' });
        expect(text('.message__content')).toEqual(['<i>why</i>']);
        expect(text('.message__action')).toEqual(['Action: <b>Yes</b>', 'Action: {"id":"more"}']);
        expect(fixture.nativeElement.querySelector('.message b, .message i')).toBeNull();
    });

    describe('older messages', () => {
        const thread = (count: number, prefix = 'm'): ChatOperatorMessage[] =>
            Array.from({ length: count }, (_, index) => ({
                id: `${prefix}-${index}`,
                role: 'user' as const,
                content: `${prefix} ${index}`,
                actions: null,
                action: null,
                session_id: null,
                // Older pages come an hour earlier.
                created_at: `2026-10-10T${{ older: '08', old: '09' }[prefix] ?? '10'}:${String(index).padStart(2, '0')}:00Z`,
                author_user_id: null,
            }));
        const scroller = (): HTMLElement => fixture.nativeElement.querySelector('.thread');

        function openFullThread(id = 'c-1'): void {
            chatApi.getMessages.mockReturnValueOnce(of(thread(CHAT_MESSAGES_PAGE_SIZE)));
            fixture.componentInstance.selectConversation(id);
            fixture.detectChanges();
        }

        // Scrolled up from the bottom of the column-reverse thread.
        function userScrolls(): void {
            scroller().scrollTop = -40;
            scroller().dispatchEvent(new Event('scroll'));
        }

        it('does not page by itself on the first render, only once the user scrolled the thread', () => {
            openFullThread();
            chatApi.getMessages.mockClear();
            IntersectionObserverStub.current().intersect();
            expect(chatApi.getMessages).not.toHaveBeenCalled();

            chatApi.getMessages.mockReturnValueOnce(of([]));
            userScrolls();
            IntersectionObserverStub.current().intersect();
            expect(chatApi.getMessages).toHaveBeenCalledTimes(1);
            expect(chatApi.getMessages).toHaveBeenCalledWith('c-1', 'm-0');
        });

        it('sends one request while a page is loading and labels the button as loading', () => {
            openFullThread();
            chatApi.getMessages.mockClear();
            const page$ = new Subject<ChatOperatorMessage[]>();
            chatApi.getMessages.mockReturnValueOnce(page$);
            userScrolls();
            IntersectionObserverStub.current().intersect();
            fixture.detectChanges();
            IntersectionObserverStub.current().intersect();
            expect(chatApi.getMessages).toHaveBeenCalledTimes(1);
            expect(text('.thread__older button')).toEqual(['Loading older messages…']);
            page$.next(thread(3, 'old'));
            page$.complete();
            fixture.detectChanges();
            expect(
                fixture.componentInstance
                    .messages()
                    .slice(0, 3)
                    .map((message) => message.id)
            ).toEqual(['old-0', 'old-1', 'old-2']);
        });

        it('stops at the first page and keeps the view where it was while older messages are prepended', () => {
            openFullThread();
            chatApi.getMessages.mockReturnValueOnce(of(thread(3, 'old')));
            userScrolls();
            scroller().scrollTop = -120;
            IntersectionObserverStub.current().intersect();
            fixture.detectChanges();
            // Regression guard only (jsdom has no layout): the thread stays a column-reverse scroller, which keeps
            // its offset from the bottom, and the code never shifts scrollTop by hand.
            expect(getComputedStyle(scroller()).flexDirection).toBe('column-reverse');
            expect(scroller().scrollTop).toBe(-120);
            expect(fixture.nativeElement.querySelector('.thread__older')).toBeNull();
        });

        it('keeps loading while a landed page leaves the sentinel in view, and stops at the first page', () => {
            const box = (top: number, bottom: number) => ({ top, bottom }) as DOMRect;
            openFullThread();
            vi.spyOn(scroller(), 'getBoundingClientRect').mockReturnValue(box(0, 500));
            const sentinel = fixture.nativeElement.querySelector('.thread__older') as HTMLElement;
            vi.spyOn(sentinel, 'getBoundingClientRect').mockReturnValue(box(0, 30));
            chatApi.getMessages.mockClear();
            chatApi.getMessages
                .mockReturnValueOnce(of(thread(CHAT_MESSAGES_PAGE_SIZE, 'old')))
                .mockReturnValueOnce(of(thread(3, 'older')));
            userScrolls();
            IntersectionObserverStub.current().intersect();
            // Runs the after-render check the landed page scheduled.
            TestBed.tick();

            expect(chatApi.getMessages.mock.calls.map((call) => (call as unknown[])[1])).toEqual(['m-0', 'old-0']);
            expect(fixture.nativeElement.querySelector('.thread__older')).toBeNull();
        });

        it('does not chain a load when the landed page pushed the sentinel out of view', () => {
            const box = (top: number, bottom: number) => ({ top, bottom }) as DOMRect;
            openFullThread();
            vi.spyOn(scroller(), 'getBoundingClientRect').mockReturnValue(box(0, 500));
            const sentinel = fixture.nativeElement.querySelector('.thread__older') as HTMLElement;
            vi.spyOn(sentinel, 'getBoundingClientRect').mockReturnValue(box(-900, -870));
            chatApi.getMessages.mockClear();
            chatApi.getMessages.mockReturnValueOnce(of(thread(CHAT_MESSAGES_PAGE_SIZE, 'old')));
            userScrolls();
            IntersectionObserverStub.current().intersect();
            // Runs the after-render check the landed page scheduled.
            TestBed.tick();
            expect(chatApi.getMessages).toHaveBeenCalledTimes(1);
        });

        it('does not count a scroll event at the bottom (a browser clamp) as the user scrolling', () => {
            openFullThread();
            chatApi.getMessages.mockClear();
            scroller().scrollTop = 0;
            scroller().dispatchEvent(new Event('scroll'));
            IntersectionObserverStub.current().intersect();
            expect(chatApi.getMessages).not.toHaveBeenCalled();
        });

        it('keeps focus on the Load older messages button while it loads and announces the loading', () => {
            openFullThread();
            const page$ = new Subject<ChatOperatorMessage[]>();
            chatApi.getMessages.mockReturnValueOnce(page$);
            const button = fixture.nativeElement.querySelector('.thread__older button') as HTMLButtonElement;
            button.focus();
            button.click();
            fixture.detectChanges();
            const during = fixture.nativeElement.querySelector('.thread__older button') as HTMLButtonElement;
            expect(during).toBe(button);
            expect(document.activeElement).toBe(button);
            expect(button.textContent?.trim()).toBe('Loading older messages…');
            expect(fixture.nativeElement.querySelector('.thread__older [role="status"]')?.textContent?.trim()).toBe(
                'Loading older messages…'
            );
            expect(fixture.nativeElement.querySelector('.thread__older')?.getAttribute('role')).toBeNull();
            page$.complete();
        });

        it('drops an older page still loading when another conversation opens, which can page at once', () => {
            conversationUpdated$.next(row({ id: 'c-2', last_message_preview: 'second' }));
            openFullThread();
            const stale$ = new Subject<ChatOperatorMessage[]>();
            chatApi.getMessages.mockReturnValueOnce(stale$);
            userScrolls();
            IntersectionObserverStub.current().intersect();
            expect(stale$.observed).toBe(true);

            openFullThread('c-2');
            expect(stale$.observed).toBe(false);
            expect(fixture.componentInstance.isLoadingOlder()).toBe(false);
            expect(text('.thread__older button')).toEqual(['Load older messages']);
            chatApi.getMessages.mockClear();
            chatApi.getMessages.mockReturnValueOnce(of([]));
            (fixture.nativeElement.querySelector('.thread__older button') as HTMLButtonElement).click();
            expect(chatApi.getMessages).toHaveBeenCalledWith('c-2', 'm-0');
        });

        it('never prepends a page requested before switching away and back (A → B → A)', () => {
            conversationUpdated$.next(row({ id: 'c-2', last_message_preview: 'second' }));
            openFullThread();
            const stale$ = new Subject<ChatOperatorMessage[]>();
            chatApi.getMessages.mockReturnValueOnce(stale$);
            userScrolls();
            IntersectionObserverStub.current().intersect();
            openFullThread('c-2');
            openFullThread('c-1');
            stale$.next(thread(3, 'old'));
            stale$.complete();
            fixture.detectChanges();
            expect(fixture.componentInstance.messages().some((message) => message.id.startsWith('old-'))).toBe(false);
        });

        it('stops chaining when a landed page added nothing older', () => {
            const box = (top: number, bottom: number) => ({ top, bottom }) as DOMRect;
            openFullThread();
            vi.spyOn(scroller(), 'getBoundingClientRect').mockReturnValue(box(0, 500));
            const sentinel = fixture.nativeElement.querySelector('.thread__older') as HTMLElement;
            vi.spyOn(sentinel, 'getBoundingClientRect').mockReturnValue(box(0, 30));
            chatApi.getMessages.mockClear();
            // A full page of messages already listed: the oldest stays the same.
            chatApi.getMessages.mockReturnValueOnce(of(thread(CHAT_MESSAGES_PAGE_SIZE)));
            userScrolls();
            IntersectionObserverStub.current().intersect();
            TestBed.tick();
            expect(chatApi.getMessages).toHaveBeenCalledTimes(1);
        });

        it('keeps a Load older messages button for keyboard and screen-reader users', () => {
            openFullThread();
            chatApi.getMessages.mockClear();
            chatApi.getMessages.mockReturnValueOnce(of([]));
            (fixture.nativeElement.querySelector('.thread__older button') as HTMLButtonElement).click();
            expect(chatApi.getMessages).toHaveBeenCalledWith('c-1', 'm-0');
        });

        it('starts over on another conversation: no paging until the user scrolls that thread', () => {
            conversationUpdated$.next(row({ id: 'c-2', last_message_preview: 'second' }));
            openFullThread();
            userScrolls();
            openFullThread('c-2');
            chatApi.getMessages.mockClear();
            IntersectionObserverStub.current().intersect();
            expect(chatApi.getMessages).not.toHaveBeenCalled();
        });
    });

    it('offers a take-over on 409 claimed_by_other and claims with force after confirmation', () => {
        chatApi.claim
            .mockReturnValueOnce(
                throwError(
                    () => new HttpErrorResponse({ status: 409, error: { code: 'claimed_by_other', message: 'held' } })
                )
            )
            .mockReturnValueOnce(of(row({ id: 'c-1', mode: 'human', assigned_operator_id: 3 })));
        confirmation.confirm.mockReturnValue(of(true));

        fixture.componentInstance.claim(row({ id: 'c-1' }));

        expect(confirmation.confirm).toHaveBeenCalledTimes(1);
        expect(chatApi.claim).toHaveBeenLastCalledWith('c-1', true);
    });

    it('sends the typed reply on Enter in the composer without a native form submit', () => {
        const claimed = handedOff('c-1', '2026-10-10T09:00:00Z', { mode: 'human', assigned_operator_id: 3 });
        chatApi.reply.mockReturnValue(
            of({
                id: 'm-9',
                role: 'operator',
                content: 'on my way',
                actions: null,
                action: null,
                session_id: null,
                created_at: '2026-10-10T10:02:00Z',
                author_user_id: 3,
            } as ChatOperatorMessage)
        );
        reloadWith(page([claimed]), page([]));
        fixture.componentInstance.selectConversation('c-1');
        fixture.detectChanges();
        const host: HTMLElement = fixture.nativeElement;
        typeInComposer('on my way');
        expect(host.querySelector('form')).toBeNull();
        host.querySelector('.composer app-custom-input')?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
        expect(chatApi.reply).toHaveBeenCalledWith('c-1', 'on my way');
        fixture.detectChanges();
        expect(text('.message__content')).toEqual(['on my way']);
    });

    it('keeps the selection and the thread while a reconnect reload is in flight, then merges both', () => {
        const component = fixture.componentInstance;
        const first: ChatOperatorMessage = {
            id: 'm-1',
            role: 'user',
            content: 'first',
            actions: null,
            action: null,
            session_id: null,
            created_at: '2026-10-10T10:00:00Z',
            author_user_id: null,
        };
        const second: ChatOperatorMessage = {
            ...first,
            id: 'm-2',
            role: 'assistant',
            content: 'second',
            created_at: '2026-10-10T10:01:00Z',
        };
        const third: ChatOperatorMessage = {
            ...second,
            id: 'm-3',
            content: 'third',
            created_at: '2026-10-10T10:02:00Z',
        };
        chatApi.getMessages.mockReturnValueOnce(of([first, second]));
        expandBot();
        component.selectConversation('c-1');
        fixture.detectChanges();
        expect(text('.message__content')).toEqual(['first', 'second']);

        const page$ = new Subject<ChatConversationPage>();
        const thread$ = new Subject<ChatOperatorMessage[]>();
        chatApi.getMessages.mockReturnValueOnce(thread$);
        reloadWith(page([]), page$);
        expect(component.selectedId()).toBe('c-1');
        expect(text('.message__content')).toEqual(['first', 'second']);
        expect(text('.conversation__preview')).toEqual(['hello']);

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
        thread$.next([second, third]);
        fixture.detectChanges();
        expect(text('.conversation__preview')).toEqual(['live', 'fresh']);
        expect(component.selectedId()).toBe('c-1');
        expect(component.selected()?.id).toBe('c-1');
        expect(text('.message__content')).toEqual(['first', 'second', 'third']);
    });

    it('loads more with the cursor and lists a row returned by two pages once, the later page winning', () => {
        const component = fixture.componentInstance;
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
        expect(text('.inbox__more')).toEqual(['Load more']);

        chatApi.getConversations.mockReturnValueOnce(
            page([
                row({ id: 'c-1', last_message_preview: 'later copy' }),
                row({ id: 'c-3', last_message_at: '2026-10-10T08:00:00Z', last_message_preview: 'oldest' }),
            ])
        );
        component.loadMoreConversations('bot');
        fixture.detectChanges();

        expect(chatApi.getConversations).toHaveBeenLastCalledWith({
            section: 'bot',
            binding: null,
            cursor: 'cursor-2',
        });
        expect(text('.conversation__preview')).toEqual(['later copy', 'older', 'oldest']);
        expect(component.inbox().bot.nextCursor).toBeNull();
        expect(text('.inbox__more')).toEqual([]);
    });

    it('shows a started test conversation in the header even when its stream event came first', () => {
        const component = fixture.componentInstance;
        const created = row({ id: 'c-9', is_test: true, last_message_at: null, last_message_preview: '' });
        conversationUpdated$.next(created);
        component.onTestConversationStarted(created);
        fixture.detectChanges();
        expect(component.selected()).toEqual(created);
    });

    it('keeps a row streamed after the reload when a Load more page brings an older copy', () => {
        const component = fixture.componentInstance;
        reloadWith(page([]), page([row({ id: 'c-1', last_message_preview: 'hello' })], 'cursor-2'));
        expandBot();

        conversationUpdated$.next(
            row({ id: 'c-2', last_message_at: '2026-10-10T12:00:00Z', last_message_preview: 'live' })
        );
        chatApi.getConversations.mockReturnValueOnce(
            of({
                results: [row({ id: 'c-2', last_message_at: '2026-10-10T08:00:00Z', last_message_preview: 'stale' })],
                next_cursor: null,
            })
        );
        component.loadMoreConversations('bot');
        fixture.detectChanges();

        expect(text('.conversation__preview')).toEqual(['live', 'hello']);
    });

    it('does not list a streamed conversation without messages but keeps it as the selected header', () => {
        const component = fixture.componentInstance;
        const created = row({ id: 'c-9', is_test: true, last_message_at: null, last_message_preview: '' });
        component.onTestConversationStarted(created);
        conversationUpdated$.next({ ...created, state: 'processing' });
        fixture.detectChanges();
        expect(text('.conversation__preview')).toEqual([]);
        expect(component.selected()?.state).toBe('processing');

        conversationUpdated$.next(
            row({ id: 'c-9', is_test: true, last_message_at: '2026-10-10T11:00:00Z', last_message_preview: 'first' })
        );
        fixture.detectChanges();
        expect(text('.conversation__preview')).toEqual(['first']);
    });

    it('enables the composer from the claim response without waiting for a stream event', () => {
        const component = fixture.componentInstance;
        chatApi.claim.mockReturnValue(of(row({ id: 'c-1', mode: 'human', assigned_operator_id: 3 })));
        component.selectConversation('c-1');
        fixture.detectChanges();
        expect(component.isClaimedByMe()).toBe(false);

        component.claim(row({ id: 'c-1' }));
        fixture.detectChanges();
        expect(component.isClaimedByMe()).toBe(true);
        expect(composerInput().disabled).toBe(false);
    });

    describe('visitor token of an older test conversation', () => {
        const visitorButton = (): HTMLButtonElement =>
            fixture.nativeElement.querySelectorAll('.composer__roles app-tab-button button')[0];
        const caption = (): string =>
            fixture.nativeElement.querySelector('.composer__caption')?.textContent?.trim() ?? '';

        function selectTest(id: string): void {
            conversationUpdated$.next(row({ id, is_test: true }));
            fixture.componentInstance.selectConversation(id);
            fixture.detectChanges();
        }

        it('fetches one token when it is selected, keeps it in memory and enables Visitor', () => {
            const token$ = new Subject<{ visitor_token: string }>();
            chatApi.issueVisitorToken.mockReturnValueOnce(token$);
            selectTest('t-1');
            expect(visitorButton().disabled).toBe(true);
            expect(caption()).toBe('Getting a visitor token…');

            // A stream update of the same conversation while the request is in flight sends no second one.
            conversationUpdated$.next(row({ id: 't-1', is_test: true, last_message_preview: 'again' }));
            fixture.detectChanges();
            expect(chatApi.issueVisitorToken).toHaveBeenCalledTimes(1);
            expect(chatApi.issueVisitorToken).toHaveBeenCalledWith('t-1');

            token$.next({ visitor_token: 'vt-1' });
            token$.complete();
            fixture.detectChanges();
            expect(fixture.componentInstance.visitorTokens()).toEqual({ 't-1': 'vt-1' });
            expect(visitorButton().disabled).toBe(false);
            expect(visitorButton().getAttribute('aria-pressed')).toBe('true');
        });

        it('keeps Visitor disabled with the reason when the token is refused, and retries when selected again', () => {
            chatApi.issueVisitorToken.mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 500 })));
            selectTest('t-1');
            expect(visitorButton().disabled).toBe(true);
            expect(caption()).toBe("Couldn't get a visitor token. Select the conversation again to retry.");

            chatApi.issueVisitorToken.mockReturnValueOnce(of({ visitor_token: 'vt-2' }));
            fixture.componentInstance.selectConversation('t-1');
            fixture.detectChanges();
            expect(chatApi.issueVisitorToken).toHaveBeenCalledTimes(2);
            expect(visitorButton().disabled).toBe(false);
        });

        it('stores a token that arrives after switching away without changing the open composer, and reuses it', () => {
            const token$ = new Subject<{ visitor_token: string }>();
            chatApi.issueVisitorToken.mockReturnValueOnce(token$);
            selectTest('t-1');
            fixture.componentInstance.selectConversation('c-1');
            fixture.detectChanges();
            token$.next({ visitor_token: 'vt-late' });
            token$.complete();
            fixture.detectChanges();
            expect(fixture.componentInstance.visitorTokens()).toEqual({ 't-1': 'vt-late' });
            expect(fixture.componentInstance.visitorTokenPendingFor()).toBeNull();
            // The open conversation is a real one: still no visitor switch.
            expect(fixture.nativeElement.querySelector('.composer__roles')).toBeNull();

            fixture.componentInstance.selectConversation('t-1');
            fixture.detectChanges();
            expect(chatApi.issueVisitorToken).toHaveBeenCalledTimes(1);
            expect(visitorButton().disabled).toBe(false);
        });

        it('fetches nothing for a test started on this page, which already has its token', () => {
            const created = row({ id: 't-9', is_test: true, last_message_at: null });
            chatApi.createTestConversation.mockReturnValue(of({ visitor_token: 'vt-9', conversation: created }));
            listBindings([binding]);
            scopeTo('b-1');
            fixture.componentInstance.startTest();
            fixture.detectChanges();
            expect(chatApi.issueVisitorToken).not.toHaveBeenCalled();
        });
    });

    describe('thread header', () => {
        const header = (): HTMLElement => fixture.nativeElement.querySelector('.thread-header');
        const rings = (): string[] =>
            Array.from(header().querySelectorAll('.usage-ring')).map((ring) => ring.getAttribute('aria-label') ?? '');

        const pillTooltip = (): string =>
            fixture.debugElement.query(By.css('.thread-header .mode-badge')).injector.get(MatTooltip).message;

        function open(conversation: ChatConversation): void {
            listBindings([binding]);
            conversationUpdated$.next(conversation);
            fixture.componentInstance.selectConversation(conversation.id);
            fixture.detectChanges();
        }

        it("shows the mode, title, Test chip and today's turns and tokens against the binding's limits", () => {
            open(row({ id: 'c-1', is_test: true, tokens_used: 9000, tokens_today: 250, turns: 40, turns_today: 3 }));
            expect(text('.thread-header .mode-badge')).toEqual(['Bot']);
            expect(text('.thread-header__title')).toEqual(['Support · c-1']);
            expect(text('.thread-header .test-chip')).toEqual(['Test']);
            expect(rings()).toEqual(['Turns today: 3 of 50', 'Tokens today: 250 of 1,000']);
            expect(
                Array.from(header().querySelectorAll('.usage-ring__icon use')).map((use) => use.getAttribute('href'))
            ).toEqual(['#icon-message', '#icon-token']);
            // The shared status chip, with the closest of its looks per mode.
            expect(header().querySelector('.mode-badge')?.className).toContain('mode-badge--bot');
            expect(text('.usage-ring__text')).toEqual(['3/50', '250/1K']);
            expect(header().querySelector('.thread-header__reason')).toBeNull();
        });

        it('names who holds the conversation on the mode pill and shows the handoff reason only once handed off', () => {
            open(
                handedOff('c-1', '2026-10-10T09:00:00Z', {
                    mode: 'human',
                    assigned_operator_id: 7,
                    handoff_reason: 'Asked for a human',
                })
            );
            const pill = header().querySelector('.mode-badge') as HTMLElement;
            // The visible mode is its name; who holds it is the tooltip, announced as its description.
            expect(pill.hasAttribute('aria-label')).toBe(false);
            expect(pill.getAttribute('tabindex')).toBe('0');
            expect(pillTooltip()).toBe('Held by Operator #7');
            expect(text('.thread-header__reason')).toEqual(['Asked for a human']);

            conversationUpdated$.next(row({ id: 'c-1', handoff_reason: 'Asked for a human' }));
            fixture.detectChanges();
            expect(header().querySelector('.thread-header__reason')).toBeNull();
            expect(pill.hasAttribute('tabindex')).toBe(false);

            conversationUpdated$.next(row({ id: 'c-1', mode: 'human', assigned_operator_id: 3 }));
            fixture.detectChanges();
            expect(pillTooltip()).toBe('Held by you');
        });

        it('has no Claim or Take over in the header: the composer offers claiming', () => {
            open(row({ id: 'c-1' }));
            const labels = Array.from(header().querySelectorAll('button')).map((button) => button.textContent?.trim());
            expect(labels).not.toContain('Claim');
            expect(labels).not.toContain('Take over');
            expect(header().querySelector('.thread-header__menu-btn')).toBeNull();
            expect(text('.composer app-button')).toContain('Claim to reply');
        });

        it('offers Take over and Release to bot in the ⋯ menu when another operator holds it', () => {
            open(handedOff('c-1', '2026-10-10T09:00:00Z', { mode: 'human', assigned_operator_id: 7 }));
            chatApi.claim.mockReturnValue(of(row({ id: 'c-1', mode: 'human', assigned_operator_id: 3 })));
            (header().querySelector('.thread-header__menu-btn') as HTMLButtonElement).click();
            fixture.detectChanges();
            const item = (label: string) =>
                Array.from(document.querySelectorAll<HTMLButtonElement>('.thread-menu__item')).find(
                    (button) => button.textContent?.trim() === label
                );
            expect(item('Release to bot')).toBeDefined();
            item('Take over')!.click();
            expect(chatApi.claim).toHaveBeenCalledWith('c-1');
            fixture.detectChanges();
            expect(document.querySelector('.thread-menu')).toBeNull();
        });

        it('offers Release next to the menu when the current user holds it, and it releases', () => {
            open(handedOff('c-1', '2026-10-10T09:00:00Z', { mode: 'human', assigned_operator_id: 3 }));
            chatApi.release.mockReturnValue(of(row({ id: 'c-1' })));
            const release = Array.from(header().querySelectorAll<HTMLButtonElement>('app-button button')).find(
                (button) => button.textContent?.trim() === 'Release'
            )!;
            // The holder's only other action would be Release again: no ⋯ menu.
            expect(header().querySelector('.thread-header__menu-btn')).toBeNull();
            release.click();
            expect(chatApi.release).toHaveBeenCalledWith('c-1');
        });

        it('hides the conversation actions without chats:use', () => {
            permissions.can = () => false;
            try {
                fixture = TestBed.createComponent(ChatPageComponent);
                fixture.detectChanges();
                open(handedOff('c-1', '2026-10-10T09:00:00Z', { mode: 'human', assigned_operator_id: 3 }));
                expect(header().querySelector('.thread-header__menu-btn')).toBeNull();
                expect(header().querySelector('app-button')).toBeNull();
            } finally {
                permissions.can = (resource, action) => resource === ResourceCode.Chats && action === ActionCode.Use;
            }
        });
    });
});
