import { HttpErrorResponse } from '@angular/common/http';
import { provideLocationMocks } from '@angular/common/testing';
import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatTooltip } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';
import { provideRouter, Router } from '@angular/router';
import { ConfirmationDialogService } from '@shared/components';
import { ActionCode, ResourceCode } from '@shared/models';
import { NEVER, Observable, of, Subject, throwError } from 'rxjs';

import { PhoneLayoutService } from '../../../../core/services/phone-layout.service';
import { ActiveOrgService } from '../../../../services/auth/active-org.service';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ProfileService } from '../../../../services/auth/profile.service';
import { ToastService } from '../../../../services/notifications';
import { ConversationListComponent } from '../../components/conversation-list/conversation-list.component';
import {
    CHAT_BINDING_DEFAULTS,
    ChatBinding,
    ChatConversation,
    ChatConversationPage,
    ChatInboxMessageEvent,
    ChatMyAlias,
    ChatOperatorMessage,
} from '../../models/chat.model';
import { CHAT_MESSAGES_PAGE_SIZE, ChatApiService, ConversationListParams } from '../../services/chat-api.service';
import { ChatBindingActionsService } from '../../services/chat-binding-actions.service';
import { ChatDesksStorageService } from '../../services/chat-desks-storage.service';
import { ChatInboxStreamService } from '../../services/chat-inbox-stream.service';
import { ChatMyAliasesStorageService } from '../../services/chat-my-aliases-storage.service';
import { ConversationListPreferencesService } from '../../services/conversation-list-preferences.service';
import { DeskDrawerService } from '../../services/desk-drawer.service';
import { OpenConversationService } from '../../services/open-conversation.service';
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
    /** The live observer of the thread's older-messages sentinel (the conversations column has its own). */
    static current(): IntersectionObserverStub {
        return IntersectionObserverStub.instances
            .filter((instance) => !instance.disconnected)
            .filter((instance) => instance.observed.some((target) => target.classList.contains('thread__older')))
            .at(-1)!;
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
    // What the bindings endpoint returns; the desks storage loads it (the page only for a route desk it lacks).
    let serverBindings: ChatBinding[] = [];
    let fixture: ComponentFixture<ChatPageComponent>;
    let navigate: ReturnType<typeof vi.spyOn>;
    const conversationUpdated$ = new Subject<ChatConversation>();
    const messageCreated$ = new Subject<ChatInboxMessageEvent>();
    const readyEpoch = signal(0);
    // Wider than a phone unless a spec says otherwise.
    const isPhone = signal(false);
    const chatApi = {
        getBindings: vi.fn(() => of(serverBindings)),
        getMyAliases: vi.fn(() => of([] as ChatMyAlias[])),
        // By default Waiting, In progress and Tests are empty and Bot holds one conversation.
        getConversations: vi.fn(
            (params: ConversationListParams): Observable<ChatConversationPage> =>
                page(params.section === 'bot' ? [row({ id: 'c-1' })] : [])
        ),
        getMessages: vi.fn(() => of([] as ChatOperatorMessage[])),
        createTestConversation: vi.fn(),
        // Selecting a test conversation fetches its visitor token: by default the request has not answered yet.
        issueVisitorToken: vi.fn((): Observable<{ visitor_token: string }> => NEVER),
        sendAsVisitor: vi.fn(),
        claim: vi.fn(),
        release: vi.fn(),
        reply: vi.fn(),
    };
    const confirmation = { confirm: vi.fn() };
    const permissions: { can: (resource: ResourceCode, action: ActionCode) => boolean } = {
        can: (resource, action) => resource === ResourceCode.Chats && action === ActionCode.Use,
    };
    const bindingActions = {
        pause: vi.fn(),
        resume: vi.fn(),
        delete: vi.fn(),
        copySnippet: vi.fn(),
        openSettings: vi.fn(),
        editMyAlias: vi.fn(),
    };

    /** The user's aliases load, as the desks shell loads them; none means the desks' operator names. */
    function loadAliases(aliases: ChatMyAlias[] = []): void {
        chatApi.getMyAliases.mockReturnValueOnce(of(aliases));
        TestBed.inject(ChatMyAliasesStorageService).reload();
        fixture.detectChanges();
    }

    /** The user goes by `alias` on a desk, as a save in the dialog stores it. */
    function goBy(alias: string | null, bindingId = 'b-1'): void {
        TestBed.inject(ChatMyAliasesStorageService).remember({
            binding_id: bindingId,
            alias,
            visible_name: alias ?? binding.operator_display_name,
        });
        fixture.detectChanges();
    }

    function text(selector: string): string[] {
        const host: HTMLElement = fixture.nativeElement;
        return Array.from(host.querySelectorAll(selector)).map(
            (node) => node.textContent?.replace(/\s+/g, ' ').trim() ?? ''
        );
    }

    const collapsedSections = (): string[] => [...TestBed.inject(ConversationListPreferencesService).collapsed()];

    /** A reload requests the open sections in column order: Waiting, In progress, then Bot (Tests start collapsed). */
    function reloadWith(
        waiting: Observable<ChatConversationPage>,
        bot: Observable<ChatConversationPage>,
        inProgress: Observable<ChatConversationPage> = page([])
    ): void {
        chatApi.getConversations.mockReturnValueOnce(waiting).mockReturnValueOnce(inProgress).mockReturnValueOnce(bot);
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

    /** The server lists these desks and the storage has loaded them, as the desks shell does around the page. */
    function listBindings(bindings: ChatBinding[]): void {
        serverBindings = bindings;
        TestBed.inject(ChatDesksStorageService).reload();
    }

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        vi.stubGlobal('IntersectionObserver', IntersectionObserverStub);
        IntersectionObserverStub.instances = [];
        Element.prototype.scrollIntoView = vi.fn();
        vi.clearAllMocks();
        serverBindings = [];
        isPhone.set(false);
        TestBed.configureTestingModule({
            imports: [ChatPageComponent],
            providers: [
                provideRouter([]),
                // The page writes the open conversation to the URL: each spec gets a history of its own.
                provideLocationMocks(),
                { provide: ChatApiService, useValue: chatApi },
                { provide: ChatBindingActionsService, useValue: bindingActions },
                {
                    provide: ChatInboxStreamService,
                    useValue: {
                        conversationUpdated$,
                        messageCreated$,
                        readyEpoch,
                        status: signal('open'),
                        waitingCountFor: () => 0,
                    },
                },
                { provide: ProfileService, useValue: { currentUserSignal: signal({ id: 3 }) } },
                { provide: PermissionsService, useValue: permissions },
                { provide: ConfirmationDialogService, useValue: confirmation },
                { provide: ToastService, useValue: { error: vi.fn(), success: vi.fn() } },
                // The desks shell provides it around the page.
                DeskDrawerService,
                { provide: PhoneLayoutService, useValue: { isPhone } },
            ],
        });
        // Signed in to an org: the desks storage asks for nothing without one.
        TestBed.inject(ActiveOrgService).set(1);
        // Desk pages are not routed here; the open conversation's URL (navigateByUrl) is, against the root route.
        navigate = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
        fixture = TestBed.createComponent(ChatPageComponent);
        fixture.detectChanges();
    });

    afterEach(() => {
        vi.unstubAllGlobals();
        localStorage.clear();
        delete (Element.prototype as Partial<Element>).scrollIntoView;
    });

    it('keeps the open conversation current as it changes, whatever the list shows', () => {
        const component = fixture.componentInstance;
        component.selectConversation(row({ id: 'c-1' }));

        conversationUpdated$.next(row({ id: 'c-1', mode: 'awaiting_human', handoff_at: '2026-10-10T11:00:00Z' }));
        conversationUpdated$.next(row({ id: 'c-2', mode: 'human' }));

        expect(component.selectedId()).toBe('c-1');
        expect(component.selected()?.mode).toBe('awaiting_human');
    });

    it('hosts the conversations column for the route desk and opens what it selects', () => {
        const component = fixture.componentInstance;
        const list = (): ConversationListComponent =>
            fixture.debugElement.query(By.directive(ConversationListComponent)).componentInstance;
        expect(list().bindingId()).toBeNull();
        scopeTo('b-2');
        expect(list().bindingId()).toBe('b-2');

        list().selectedChange.emit(row({ id: 'c-4', binding_id: 'b-2' }));
        fixture.detectChanges();
        expect(component.selectedId()).toBe('c-4');
        expect(list().selectedId()).toBe('c-4');
    });

    it('expands Tests, not Bot, in the conversations column when a test conversation starts', () => {
        expect(collapsedSections()).toEqual(['test']);
        fixture.componentInstance.onTestConversationStarted(row({ id: 'c-9', is_test: true, last_message_at: null }));
        expect(collapsedSections()).toEqual([]);
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
        expect(text('.desk-toolbar__title')).toEqual(['Sales']);
        expect(text('.desk-toolbar app-chat-binding-status')).toEqual(['Live']);
        expect(fixture.nativeElement.querySelector('h2 app-chat-binding-status')).toBeNull();
        expect(host.querySelector('.inbox__toolbar, app-select')).toBeNull();

        headerButton('Test')!.click();
        fixture.detectChanges();

        expect(chatApi.createTestConversation).toHaveBeenCalledWith('b-2');
        expect(collapsedSections()).not.toContain('test');
        expect(component.selectedId()).toBe('c-9');
        expect(text('.thread-header .test-chip')).toEqual(['Test']);
        expect(host.querySelector('app-tab-button button[aria-pressed="true"]')?.textContent?.trim()).toBe('Visitor');

        typeInComposer('hi');
        host.querySelector('.composer app-custom-input')?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
        expect(chatApi.sendAsVisitor).toHaveBeenCalledWith('c-9', 'vt-9', 'hi', {});
        expect(chatApi.reply).not.toHaveBeenCalled();
    });

    // Waiting, In progress and Bot: Tests start collapsed and load only when opened.
    it('lists only the route binding conversations', () => {
        chatApi.getConversations.mockClear();
        scopeTo('b-2');
        expect(chatApi.getConversations.mock.calls.map(([params]) => params.binding)).toEqual(['b-2', 'b-2', 'b-2']);
    });

    it('shows the all-bindings inbox unscoped, without My name, Settings, Get snippet, Pause or Test', () => {
        listBindings([binding]);
        fixture.detectChanges();
        expect(text('.desk-toolbar__title')).toEqual(['All desks']);
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

            bindingActions.openSettings.mockReturnValue(of(undefined));
            headerButton('Settings')!.click();
            expect(bindingActions.openSettings).toHaveBeenCalledWith({ ...binding, is_active: false });
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
                    [...button.classList].filter((name) => name.startsWith('header-action')).join(' '),
                    button.getAttribute('aria-label'),
                ])
            ).toEqual([
                // My aliases have not loaded here: the action names no one rather than a name that may be wrong.
                ['header-action header-action--ghost', 'My name'],
                ['header-action header-action--ghost', 'Settings'],
                ['header-action header-action--ghost', 'Delete'],
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

    it('deletes the route binding after its confirmation, goes to All desks, then reloads the desks; a cancel stays', async () => {
        permissions.can = () => true;
        try {
            listBindings([binding]);
            scopeTo('b-1');
            const callsBefore = chatApi.getBindings.mock.calls.length;
            let finishNavigation: (navigated: boolean) => void = () => undefined;
            navigate.mockReturnValueOnce(new Promise<boolean>((resolve) => (finishNavigation = resolve)));
            bindingActions.delete.mockReturnValueOnce(of(true));
            headerButton('Delete')!.click();
            expect(bindingActions.delete).toHaveBeenCalledWith(binding);
            expect(navigate).toHaveBeenCalledWith(['/chat-bindings', 'all']);
            // Only once the page has left: a list without the desk must not read as "no longer exists".
            expect(chatApi.getBindings).toHaveBeenCalledTimes(callsBefore);
            finishNavigation(true);
            await vi.waitFor(() => expect(chatApi.getBindings).toHaveBeenCalledTimes(callsBefore + 1));
            expect(TestBed.inject(ToastService).error).not.toHaveBeenCalled();

            navigate.mockClear();
            // The shared action completes without emitting when the confirm is cancelled or the delete fails.
            bindingActions.delete.mockReturnValueOnce(of());
            headerButton('Delete')!.click();
            expect(navigate).not.toHaveBeenCalled();
        } finally {
            permissions.can = (resource, action) => resource === ResourceCode.Chats && action === ActionCode.Use;
        }
    });

    it('only reloads the desks when the route moved to another desk before the delete finished', () => {
        permissions.can = () => true;
        try {
            listBindings([binding, { ...binding, id: 'b-2', name: 'Sales' }]);
            scopeTo('b-1');
            const deleted$ = new Subject<boolean>();
            bindingActions.delete.mockReturnValueOnce(deleted$);
            headerButton('Delete')!.click();
            scopeTo('b-2');
            const callsBefore = chatApi.getBindings.mock.calls.length;

            deleted$.next(true);
            expect(navigate).not.toHaveBeenCalled();
            expect(chatApi.getBindings).toHaveBeenCalledTimes(callsBefore + 1);
        } finally {
            permissions.can = (resource, action) => resource === ResourceCode.Chats && action === ActionCode.Use;
        }
    });

    it('hides Pause and Settings without chats:update, Delete without chats:delete, Test and My name without chats:use', () => {
        listBindings([binding]);
        scopeTo('b-1');
        expect(headerButton('Test')).toBeDefined();
        expect(headerButton('My name')).toBeDefined();
        expect(headerButton('Pause')).toBeUndefined();
        expect(headerButton('Settings')).toBeUndefined();
        expect(headerButton('Delete')).toBeUndefined();

        const can = permissions.can;
        permissions.can = () => false;
        try {
            fixture = TestBed.createComponent(ChatPageComponent);
            listBindings([binding]);
            scopeTo('b-1');
            expect(headerButton('Test')).toBeUndefined();
            expect(headerButton('My name')).toBeUndefined();
        } finally {
            permissions.can = can;
        }
    });

    describe('my name on the desk', () => {
        it('names the action after the name visitors see once it is known, and opens the dialog for the open desk', () => {
            listBindings([binding]);
            scopeTo('b-1');
            const action = (): HTMLButtonElement => headerButton('My name')!;
            const tooltipOf = (): MatTooltip =>
                fixture.debugElement
                    .queryAll(By.directive(MatTooltip))
                    .find((element) => element.nativeElement === action())!
                    .injector.get(MatTooltip);
            const tooltip = (): string => tooltipOf().message;
            // Not known yet: no name at all, rather than the desk's while visitors may see an alias.
            expect(action().getAttribute('aria-label')).toBe('My name');
            expect(tooltipOf().disabled).toBe(true);

            loadAliases();
            expect(action().getAttribute('aria-label')).toBe('My name: Support');
            expect(tooltipOf().disabled).toBe(false);
            expect(tooltip()).toBe('Visitors see you as Support');

            goBy('Mike');
            expect(action().getAttribute('aria-label')).toBe('My name: Mike');
            expect(tooltip()).toBe('Visitors see you as Mike');

            action().click();
            expect(bindingActions.editMyAlias).toHaveBeenCalledWith(binding);
        });

        it("says under the operator composer which name visitors see on the open conversation's desk, once known", () => {
            listBindings([binding]);
            fixture.componentInstance.selectConversation(row({ id: 'c-1', mode: 'human', assigned_operator_id: 3 }));
            fixture.detectChanges();
            expect(text('.composer__visible-name')).toEqual([]);

            loadAliases();
            expect(text('.composer__visible-name')).toEqual(['Visitors see you as Support']);

            goBy('Mike');
            expect(text('.composer__visible-name')).toEqual(['Visitors see you as Mike']);
            // Another desk's alias is not this one's.
            goBy('Ann', 'b-2');
            expect(text('.composer__visible-name')).toEqual(['Visitors see you as Mike']);
        });

        it('shows the name visitors saw beside the author of an operator message, for operators only', () => {
            const operatorMessage = (
                id: string,
                authorId: number,
                authorName: string | null,
                visibleName: string | null
            ): ChatOperatorMessage => ({
                id,
                role: 'operator',
                content: id,
                actions: null,
                action: null,
                session_id: null,
                created_at: `2026-10-10T10:0${id.slice(-1)}:00Z`,
                author_user_id: authorId,
                author_name: authorName,
                visible_name: visibleName,
            });
            chatApi.getMessages.mockReturnValueOnce(
                of([
                    operatorMessage('m-1', 7, 'Bea Agent', 'Mike'),
                    operatorMessage('m-2', 3, 'Ada Lovelace', 'Support'),
                    operatorMessage('m-3', 9, null, 'Support'),
                    // Under their own name: nothing to add.
                    operatorMessage('m-4', 7, 'Bea Agent', 'Bea Agent'),
                ])
            );
            fixture.componentInstance.selectConversation(row({ id: 'c-1', mode: 'human', assigned_operator_id: 7 }));
            fixture.detectChanges();
            expect(text('.message__author')).toEqual([
                'Bea Agent · as Mike',
                'You · as Support',
                'Operator #9 · as Support',
                'Bea Agent',
            ]);
        });

        it('keeps the name visitors saw on a streamed operator message, and on a later copy without it', () => {
            fixture.componentInstance.selectConversation(row({ id: 'c-1' }));
            fixture.detectChanges();
            const streamed = {
                conversation_id: 'c-1',
                id: 'm-1',
                role: 'operator' as const,
                content: 'on my way',
                actions: null,
                action: null,
                created_at: '2026-10-10T10:01:00Z',
                author_user_id: 7,
                author_name: 'Bea Agent',
                visible_name: 'Mike',
            };
            messageCreated$.next(streamed);
            messageCreated$.next({ ...streamed, visible_name: null });
            fixture.detectChanges();
            expect(fixture.componentInstance.messages()).toEqual([expect.objectContaining({ visible_name: 'Mike' })]);
            expect(text('.message__author')).toEqual(['Bea Agent · as Mike']);
        });
    });

    it('sends a binding the route moves to and the server does not list back to All desks', () => {
        serverBindings = [binding];
        scopeTo('b-1');
        expect(navigate).not.toHaveBeenCalled();
        expect(text('.desk-toolbar__title')).toEqual(['Support']);

        scopeTo('gone');
        expect(navigate).toHaveBeenCalledWith(['/chat-bindings', 'all']);
        expect(TestBed.inject(ToastService).error).toHaveBeenCalledWith('This desk no longer exists.');
    });

    it('follows the route to another binding: its title, status and actions', () => {
        serverBindings = [binding, { ...binding, id: 'b-2', name: 'Sales', is_active: false }];
        scopeTo('b-1');
        expect(text('.desk-toolbar__title')).toEqual(['Support']);
        scopeTo('b-2');
        expect(text('.desk-toolbar__title')).toEqual(['Sales']);
        expect(text('.desk-toolbar app-chat-binding-status')).toEqual(['Paused']);
        expect(navigate).not.toHaveBeenCalled();
    });

    it('asks for a fresh list once for a desk the list lacks, and stays when that list has it', () => {
        listBindings([binding]);
        const callsBefore = chatApi.getBindings.mock.calls.length;
        serverBindings = [binding, { ...binding, id: 'b-9', name: 'Created elsewhere' }];
        scopeTo('b-9');
        expect(chatApi.getBindings).toHaveBeenCalledTimes(callsBefore + 1);
        expect(text('.desk-toolbar__title')).toEqual(['Created elsewhere']);
        expect(navigate).not.toHaveBeenCalled();
    });

    it('waits for a desk list already loading before it decides anything about the route desk', () => {
        const pending$ = new Subject<ChatBinding[]>();
        chatApi.getBindings.mockReturnValueOnce(pending$);
        // The desks shell's first load, still in flight when the page opens on a desk.
        TestBed.inject(ChatDesksStorageService).reload();
        scopeTo('b-2');
        expect(chatApi.getBindings).toHaveBeenCalledTimes(1);

        pending$.next([binding, { ...binding, id: 'b-2', name: 'Sales' }]);
        fixture.detectChanges();
        expect(text('.desk-toolbar__title')).toEqual(['Sales']);
        expect(text('.desk-toolbar app-chat-binding-status')).toEqual(['Live']);
        expect(fixture.nativeElement.querySelector('h2 app-chat-binding-status')).toBeNull();
        expect(chatApi.getBindings).toHaveBeenCalledTimes(1);
        expect(navigate).not.toHaveBeenCalled();
    });

    it('sends no desk request on a logout from a desk page, and neither warns nor leaves', () => {
        listBindings([binding]);
        scopeTo('b-1');
        const desksStorage = TestBed.inject(ChatDesksStorageService);
        const callsBefore = chatApi.getBindings.mock.calls.length;

        // What a logout does before its request returns: every storage cleared, the active org gone.
        desksStorage.clear();
        TestBed.inject(ActiveOrgService).set(null);
        fixture.detectChanges();

        expect(chatApi.getBindings).toHaveBeenCalledTimes(callsBefore);
        expect(desksStorage.desks()).toEqual([]);
        expect(desksStorage.isLoaded()).toBe(false);
        expect(navigate).not.toHaveBeenCalled();
        expect(TestBed.inject(ToastService).error).not.toHaveBeenCalled();
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

    it('puts the desk toolbar, its actions and the conversations inside the one main landmark', () => {
        listBindings([binding]);
        scopeTo('b-1');
        const host: HTMLElement = fixture.nativeElement;
        const mains = host.querySelectorAll('main, [role="main"]');
        expect(mains.length).toBe(1);
        expect(mains[0].querySelector('.desk-toolbar h2')?.textContent?.trim()).toBe('Support');
        expect(mains[0].querySelector('.desk-toolbar .header-actions')).not.toBeNull();
        expect(mains[0].querySelector('.inbox .inbox__thread')).not.toBeNull();
        expect(mains[0].classList).toContain('chat-page');
    });

    it('shows no desk title until the desk name is known', () => {
        scopeTo('b-1');
        expect(fixture.nativeElement.querySelector('.desk-toolbar h2')).toBeNull();
    });

    it('is headed by a desk toolbar, not a page title: the desk name or All desks in an h2, never an h1', () => {
        listBindings([binding]);
        fixture.detectChanges();
        const host: HTMLElement = fixture.nativeElement;
        // The one h1 is the desks shell's page header.
        expect(host.querySelectorAll('h1').length).toBe(0);
        expect(text('.desk-toolbar h2')).toEqual(['All desks']);
        expect(host.querySelector('.desk-toolbar a')).toBeNull();

        scopeTo('b-1');
        expect(host.querySelectorAll('h1').length).toBe(0);
        expect(text('.desk-toolbar h2')).toEqual(['Support']);
        expect(text('.desk-toolbar app-chat-binding-status')).toEqual(['Live']);
    });

    it('goes back to All desks without a message when the org changes on a binding page', () => {
        const activeOrg = TestBed.inject(ActiveOrgService);
        const previousOrg = activeOrg.activeOrgId();
        serverBindings = [binding];
        scopeTo('b-1');
        try {
            // As an org switch does: the storages are cleared, the org changes, the desks shell reloads the desks.
            const desksStorage = TestBed.inject(ChatDesksStorageService);
            desksStorage.clear();
            activeOrg.set((previousOrg ?? 0) + 1);
            // The new org's list does not have the binding.
            serverBindings = [];
            desksStorage.reload();
            fixture.detectChanges();
            expect(navigate).toHaveBeenCalledWith(['/chat-bindings', 'all']);
            expect(TestBed.inject(ToastService).error).not.toHaveBeenCalled();
        } finally {
            activeOrg.set(previousOrg);
        }
    });

    it('closes the open conversation when the route moves to another binding, not before', () => {
        const component = fixture.componentInstance;
        component.selectConversation(row({ id: 'c-1' }));
        fixture.detectChanges();
        expect(component.selectedId()).toBe('c-1');

        scopeTo('b-2');
        expect(component.selectedId()).toBeNull();
        expect(component.messages()).toEqual([]);
    });

    it('keeps the operator-only composer without a Visitor / Operator switch on a real conversation', () => {
        fixture.componentInstance.selectConversation(row({ id: 'c-1' }));
        fixture.detectChanges();
        const host: HTMLElement = fixture.nativeElement;
        expect(host.querySelector('app-chat-thread-composer')).not.toBeNull();
        expect(host.querySelector('.composer__roles')).toBeNull();
        expect(composerInput().placeholder).toBe('Claim the conversation to reply');
    });

    it('adds an operator reply only to the thread it was sent on', () => {
        const component = fixture.componentInstance;
        component.selectConversation(row({ id: 'c-1' }));
        fixture.detectChanges();
        const message = { id: 'm-a', role: 'operator', content: 'for A' } as ChatOperatorMessage;
        component.onOperatorMessageSent({ conversationId: 'c-a', message });
        expect(component.messages()).toEqual([]);
        component.onOperatorMessageSent({ conversationId: 'c-1', message });
        expect(component.messages()).toEqual([message]);
    });

    it('names who wrote each operator message: you, their name, or their number while it is not known', () => {
        const operatorMessage = (id: string, authorId: number, authorName: string | null): ChatOperatorMessage => ({
            id,
            role: 'operator',
            content: id,
            actions: null,
            action: null,
            session_id: null,
            created_at: `2026-10-10T10:0${id.slice(-1)}:00Z`,
            author_user_id: authorId,
            author_name: authorName,
            visible_name: null,
        });
        chatApi.getMessages.mockReturnValueOnce(
            of([
                operatorMessage('m-1', 3, 'Ada Lovelace'),
                operatorMessage('m-2', 7, 'Grace Hopper'),
                operatorMessage('m-3', 9, null),
            ])
        );
        fixture.componentInstance.selectConversation(row({ id: 'c-1', mode: 'human', assigned_operator_id: 7 }));
        fixture.detectChanges();
        expect(text('.message__author')).toEqual(['You', 'Grace Hopper', 'Operator #9']);
    });

    it('keeps the author of a streamed operator message', () => {
        fixture.componentInstance.selectConversation(row({ id: 'c-1' }));
        fixture.detectChanges();
        messageCreated$.next({
            conversation_id: 'c-1',
            id: 'm-1',
            role: 'operator',
            content: 'on my way',
            actions: null,
            action: null,
            created_at: '2026-10-10T10:01:00Z',
            author_user_id: 7,
            author_name: 'Grace Hopper',
            visible_name: null,
        });
        fixture.detectChanges();
        expect(fixture.componentInstance.messages()[0]).toEqual(
            expect.objectContaining({ author_user_id: 7, author_name: 'Grace Hopper' })
        );
        expect(text('.message__author')).toEqual(['Grace Hopper']);
    });

    it('appends a streamed message to the open thread once', () => {
        fixture.componentInstance.selectConversation(row({ id: 'c-1' }));
        fixture.detectChanges();
        const event: ChatInboxMessageEvent = {
            conversation_id: 'c-1',
            id: 'm-1',
            role: 'assistant',
            content: 'reply',
            actions: null,
            action: null,
            created_at: '2026-10-10T10:01:00Z',
            author_user_id: null,
            author_name: null,
            visible_name: null,
        };
        messageCreated$.next(event);
        messageCreated$.next(event);
        messageCreated$.next({ ...event, id: 'm-2', conversation_id: 'other' });
        fixture.detectChanges();
        expect(text('.message__content')).toEqual(['reply']);
    });

    it('shows a visitor action reply as text, alone when the message has no text, and keeps it through the stream', () => {
        fixture.componentInstance.selectConversation(row({ id: 'c-1' }));
        fixture.detectChanges();
        const event: ChatInboxMessageEvent = {
            conversation_id: 'c-1',
            id: 'm-1',
            role: 'user',
            content: '',
            actions: null,
            action: { type: 'button', label: '<b>Yes</b>' },
            created_at: '2026-10-10T10:01:00Z',
            author_user_id: null,
            author_name: null,
            visible_name: null,
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
                author_name: null,
                visible_name: null,
            }));
        const scroller = (): HTMLElement => fixture.nativeElement.querySelector('.thread');

        function openFullThread(id = 'c-1'): void {
            chatApi.getMessages.mockReturnValueOnce(of(thread(CHAT_MESSAGES_PAGE_SIZE)));
            fixture.componentInstance.selectConversation(row({ id }));
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
                author_name: 'Ada Lovelace',
                visible_name: null,
            } as ChatOperatorMessage)
        );
        reloadWith(page([claimed]), page([]));
        fixture.componentInstance.selectConversation(claimed);
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
            author_name: null,
            visible_name: null,
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
        component.selectConversation(row({ id: 'c-1' }));
        fixture.detectChanges();
        expect(text('.message__content')).toEqual(['first', 'second']);

        const page$ = new Subject<ChatConversationPage>();
        const thread$ = new Subject<ChatOperatorMessage[]>();
        chatApi.getMessages.mockReturnValueOnce(thread$);
        reloadWith(page([]), page$);
        expect(component.selectedId()).toBe('c-1');
        expect(text('.message__content')).toEqual(['first', 'second']);
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
        thread$.next([second, third]);
        fixture.detectChanges();
        expect(text('.conversation-row__preview')).toEqual(['live', 'fresh']);
        expect(component.selectedId()).toBe('c-1');
        // No longer listed: the thread keeps the row it held.
        expect(component.selected()?.id).toBe('c-1');
        expect(text('.message__content')).toEqual(['first', 'second', 'third']);
    });

    it('takes the refetched row after a reconnect reload: a new holder reaches the header and the composer', () => {
        const component = fixture.componentInstance;
        const mine = handedOff('c-1', '2026-10-10T09:00:00Z', { mode: 'human', assigned_operator_id: 3 });
        listBindings([binding]);
        reloadWith(page([mine]), page([]));
        component.selectConversation(mine);
        fixture.detectChanges();
        expect(component.isClaimedByMe()).toBe(true);
        expect(composerInput().disabled).toBe(false);

        // The stream dropped meanwhile, and another operator took the conversation with force: no event reached us.
        reloadWith(page([{ ...mine, assigned_operator_id: 7 }]), page([]));

        expect(component.selected()?.assigned_operator_id).toBe(7);
        expect(component.isClaimedByMe()).toBe(false);
        expect(fixture.debugElement.query(By.css('.thread-header .mode-badge')).injector.get(MatTooltip).message).toBe(
            'Held by Operator #7'
        );
        expect(composerInput().disabled).toBe(true);
        expect(composerInput().placeholder).toBe('Claim the conversation to reply');
    });

    it('shows a started test conversation in the header even when its stream event came first', () => {
        const component = fixture.componentInstance;
        const created = row({ id: 'c-9', is_test: true, last_message_at: null, last_message_preview: '' });
        conversationUpdated$.next(created);
        component.onTestConversationStarted(created);
        fixture.detectChanges();
        expect(component.selected()).toEqual(created);
    });

    it('keeps a started test conversation as the open one while it has no messages, and follows its state', () => {
        const component = fixture.componentInstance;
        const created = row({ id: 'c-9', is_test: true, last_message_at: null, last_message_preview: '' });
        component.onTestConversationStarted(created);
        conversationUpdated$.next({ ...created, state: 'processing' });
        fixture.detectChanges();
        expect(component.selected()?.state).toBe('processing');
        expect(text('.thread-header__title')).toHaveLength(1);
    });

    it('enables the composer from the claim response without waiting for a stream event', () => {
        const component = fixture.componentInstance;
        chatApi.claim.mockReturnValue(of(row({ id: 'c-1', mode: 'human', assigned_operator_id: 3 })));
        component.selectConversation(row({ id: 'c-1' }));
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
            fixture.componentInstance.selectConversation(row({ id, is_test: true }));
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
            fixture.componentInstance.selectConversation(row({ id: 't-1', is_test: true }));
            fixture.detectChanges();
            expect(chatApi.issueVisitorToken).toHaveBeenCalledTimes(2);
            expect(visitorButton().disabled).toBe(false);
        });

        it('stores a token that arrives after switching away without changing the open composer, and reuses it', () => {
            const token$ = new Subject<{ visitor_token: string }>();
            chatApi.issueVisitorToken.mockReturnValueOnce(token$);
            selectTest('t-1');
            fixture.componentInstance.selectConversation(row({ id: 'c-1' }));
            fixture.detectChanges();
            token$.next({ visitor_token: 'vt-late' });
            token$.complete();
            fixture.detectChanges();
            expect(fixture.componentInstance.visitorTokens()).toEqual({ 't-1': 'vt-late' });
            expect(fixture.componentInstance.visitorTokenPendingFor()).toBeNull();
            // The open conversation is a real one: still no visitor switch.
            expect(fixture.nativeElement.querySelector('.composer__roles')).toBeNull();

            fixture.componentInstance.selectConversation(row({ id: 't-1', is_test: true }));
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
            fixture.componentInstance.selectConversation(conversation);
            fixture.detectChanges();
        }

        it("shows the mode, title, Test chip and today's turns and tokens against the binding's limits", () => {
            open(row({ id: 'c-1', is_test: true, tokens_used: 9000, tokens_today: 250, turns: 40, turns_today: 3 }));
            expect(text('.thread-header .mode-badge')).toEqual(['Bot']);
            expect(text('.thread-header__title')).toEqual(['Support · Visitor 1']);
            const title = fixture.debugElement.query(By.css('.thread-header__title'));
            expect(title.injector.get(MatTooltip).message).toBe('Conversation c-1');
            expect(title.nativeElement.getAttribute('tabindex')).toBe('0');
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

            conversationUpdated$.next(
                row({ id: 'c-1', mode: 'human', assigned_operator_id: 7, assigned_operator_name: 'Grace Hopper' })
            );
            fixture.detectChanges();
            expect(pillTooltip()).toBe('Held by Grace Hopper');
        });

        it('has no Claim or Take over in the header: the composer offers claiming', () => {
            open(row({ id: 'c-1' }));
            const labels = Array.from(header().querySelectorAll('button')).map((button) => button.textContent?.trim());
            expect(labels).not.toContain('Claim');
            expect(labels).not.toContain('Take over');
            expect(header().querySelector('.chat-action-menu__trigger')).toBeNull();
            expect(text('.composer app-button')).toContain('Claim to reply');
        });

        it('offers Take over and Release to bot in the ⋯ menu when another operator holds it', () => {
            open(handedOff('c-1', '2026-10-10T09:00:00Z', { mode: 'human', assigned_operator_id: 7 }));
            chatApi.claim.mockReturnValue(of(row({ id: 'c-1', mode: 'human', assigned_operator_id: 3 })));
            (header().querySelector('.chat-action-menu__trigger') as HTMLButtonElement).click();
            fixture.detectChanges();
            const item = (label: string) =>
                Array.from(document.querySelectorAll<HTMLButtonElement>('.chat-action-menu__item')).find(
                    (button) => button.textContent?.trim() === label
                );
            expect(item('Release to bot')).toBeDefined();
            item('Take over')!.click();
            expect(chatApi.claim).toHaveBeenCalledWith('c-1');
            fixture.detectChanges();
            expect(document.querySelector('.chat-action-menu')).toBeNull();
        });

        it('offers Release next to the menu when the current user holds it, and it releases', () => {
            open(handedOff('c-1', '2026-10-10T09:00:00Z', { mode: 'human', assigned_operator_id: 3 }));
            chatApi.release.mockReturnValue(of(row({ id: 'c-1' })));
            const release = Array.from(header().querySelectorAll<HTMLButtonElement>('app-button button')).find(
                (button) => button.textContent?.trim() === 'Release'
            )!;
            // The holder's only other action would be Release again: no ⋯ menu.
            expect(header().querySelector('.chat-action-menu__trigger')).toBeNull();
            release.click();
            expect(chatApi.release).toHaveBeenCalledWith('c-1');
        });

        it('hides the conversation actions without chats:use', () => {
            permissions.can = () => false;
            try {
                fixture = TestBed.createComponent(ChatPageComponent);
                fixture.detectChanges();
                open(handedOff('c-1', '2026-10-10T09:00:00Z', { mode: 'human', assigned_operator_id: 3 }));
                expect(header().querySelector('.chat-action-menu__trigger')).toBeNull();
                expect(header().querySelector('app-button')).toBeNull();
            } finally {
                permissions.can = (resource, action) => resource === ResourceCode.Chats && action === ActionCode.Use;
            }
        });
    });

    describe('on a phone', () => {
        const host = (): HTMLElement => fixture.nativeElement as HTMLElement;
        const inbox = (): HTMLElement => host().querySelector('.inbox') as HTMLElement;
        const switcher = (): HTMLButtonElement => host().querySelector('.phone-bar__switcher') as HTMLButtonElement;
        const back = (): HTMLButtonElement => host().querySelector('.thread-header__back') as HTMLButtonElement;
        const menuItems = (): string[] =>
            Array.from(document.querySelectorAll<HTMLButtonElement>('.chat-action-menu__item')).map(
                (item) => item.textContent?.trim() ?? ''
            );
        function openMenu(scope: string): void {
            (host().querySelector(`${scope} .chat-action-menu__trigger`) as HTMLButtonElement).click();
            fixture.detectChanges();
        }

        function chooseInMenu(label: string): void {
            Array.from(document.querySelectorAll<HTMLButtonElement>('.chat-action-menu__item'))
                .find((item) => item.textContent?.trim() === label)!
                .click();
            fixture.detectChanges();
        }

        /** A fresh page on desk b-1: permissions are read once, as the page is created. */
        function renderOnDesk(): void {
            fixture = TestBed.createComponent(ChatPageComponent);
            fixture.detectChanges();
            scopeTo('b-1');
        }

        beforeEach(() => {
            isPhone.set(true);
            listBindings([binding]);
            fixture.detectChanges();
        });

        it('shows one screen at a time: the hidden one is inert', () => {
            const sidebar = (): HTMLElement => host().querySelector('.inbox__sidebar') as HTMLElement;
            const thread = (): HTMLElement => host().querySelector('.inbox__thread') as HTMLElement;
            expect(sidebar().hasAttribute('inert')).toBe(false);
            expect(thread().hasAttribute('inert')).toBe(true);
            expect(host().querySelector('.desk-toolbar')).toBeNull();

            fixture.componentInstance.selectConversation(row({ id: 'c-1' }));
            fixture.detectChanges();
            expect(sidebar().hasAttribute('inert')).toBe(true);
            expect(thread().hasAttribute('inert')).toBe(false);
        });

        it('stops sliding once the thread has slid', () => {
            fixture.componentInstance.selectConversation(row({ id: 'c-1' }));
            fixture.detectChanges();
            const thread = host().querySelector('.inbox__thread') as HTMLElement;

            thread.dispatchEvent(Object.assign(new Event('transitionend'), { propertyName: 'opacity' }));
            fixture.detectChanges();
            expect(inbox().classList).toContain('inbox--animated');

            thread.dispatchEvent(Object.assign(new Event('transitionend'), { propertyName: 'transform' }));
            fixture.detectChanges();
            expect(inbox().classList).not.toContain('inbox--animated');
        });

        it('moves the focus to Back when a thread opens and to its row when it closes', async () => {
            fixture.componentInstance.selectConversation(row({ id: 'c-1' }));
            fixture.detectChanges();
            await fixture.whenStable();
            expect(document.activeElement).toBe(back());

            fixture.debugElement.injector.get(OpenConversationService).close();
            fixture.detectChanges();
            await fixture.whenStable();
            expect(document.activeElement?.closest('app-conversation-row')).not.toBeNull();
            expect(document.activeElement?.getAttribute('aria-label')).toContain('Visitor 1');
        });

        it("heads the list with the desk switcher, which opens the desk drawer and is the drawer's way back", () => {
            scopeTo('b-1');
            const drawer = TestBed.inject(DeskDrawerService);
            expect(host().querySelector('h2.phone-bar__heading .phone-bar__switcher')).toBe(switcher());
            expect(switcher().getAttribute('aria-label')).toBe('Switch desk, current: Support');
            expect(text('.phone-bar__desk-name')).toEqual(['Support']);
            expect(text('.phone-bar app-chat-binding-status')).toEqual(['Live']);
            expect(drawer.opener).toBe(switcher());

            switcher().click();
            expect(drawer.isOpen()).toBe(true);

            scopeTo('');
            expect(switcher().getAttribute('aria-label')).toBe('Switch desk, current: All desks');
            expect(host().querySelector('.phone-bar app-chat-binding-status')).toBeNull();
        });

        it('offers Test beside the switcher and the other desk actions in its ⋯ menu, by permission', () => {
            const permitted = permissions.can;
            try {
                permissions.can = () => true;
                renderOnDesk();
                expect(host().querySelector('.phone-bar [aria-label="Test"]')).not.toBeNull();
                openMenu('.phone-bar');
                expect(menuItems()).toEqual(['My name', 'Settings', 'Get snippet', 'Pause', 'Delete']);

                bindingActions.openSettings.mockReturnValue(of(undefined));
                chooseInMenu('Settings');
                expect(bindingActions.openSettings).toHaveBeenCalledWith(binding);
                expect(document.querySelector('.chat-action-menu')).toBeNull();

                permissions.can = (_resource, action) => action === ActionCode.Read;
                renderOnDesk();
                expect(host().querySelector('.phone-bar [aria-label="Test"]')).toBeNull();
                openMenu('.phone-bar');
                expect(menuItems()).toEqual(['Get snippet']);
            } finally {
                permissions.can = permitted;
            }
        });

        it('has no desk actions on All desks', () => {
            expect(host().querySelector('.phone-bar [aria-label="Test"]')).toBeNull();
            expect(host().querySelector('.phone-bar app-chat-action-menu')).toBeNull();
        });

        it("heads the thread with Back to the list, the visitor and the conversation's actions, Release included", () => {
            scopeTo('b-1');
            conversationUpdated$.next(row({ id: 'c-1', mode: 'human', assigned_operator_id: 3 }));
            fixture.componentInstance.selectConversation(row({ id: 'c-1', mode: 'human', assigned_operator_id: 3 }));
            fixture.detectChanges();
            chatApi.release.mockReturnValue(of(row({ id: 'c-1' })));

            expect(back().getAttribute('aria-label')).toBe('Back to Support');
            expect(text('.thread-header__back-label')).toEqual(['Support']);
            expect(text('.thread-header__title')).toEqual(['Visitor 1']);
            // No Release button beside the title: it is in the menu.
            expect(host().querySelector('.thread-header app-button')).toBeNull();

            openMenu('.thread-header__nav');
            expect(menuItems()).toEqual(['Release']);
            chooseInMenu('Release');
            expect(chatApi.release).toHaveBeenCalledWith('c-1');
        });
    });
});
