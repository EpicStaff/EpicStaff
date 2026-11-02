import { DatePipe, DOCUMENT } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
    afterNextRender,
    Component,
    computed,
    DestroyRef,
    effect,
    ElementRef,
    inject,
    Injector,
    input,
    LOCALE_ID,
    signal,
    untracked,
    viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { AppSvgIconComponent, ButtonComponent, JsonEditorComponent, SpinnerComponent } from '@shared/components';
import { ActionCode, ResourceCode } from '@shared/models';
import { extractHttpErrorMessage } from '@shared/utils';
import { filter, Subscription } from 'rxjs';

import { PhoneLayoutService } from '../../../../core/services/phone-layout.service';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ProfileService } from '../../../../services/auth/profile.service';
import { ToastService } from '../../../../services/notifications';
import { ChatConversation, ChatOperatorMessage } from '../../models/chat.model';
import { ChatMarkdownPipe } from '../../pipes/chat-markdown.pipe';
import { CHAT_MESSAGES_PAGE_SIZE, ChatApiService } from '../../services/chat-api.service';
import { ChatConversationActionsService } from '../../services/chat-conversation-actions.service';
import { ChatDesksStorageService } from '../../services/chat-desks-storage.service';
import { ChatInboxStreamService } from '../../services/chat-inbox-stream.service';
import { ChatMyAliasesStorageService } from '../../services/chat-my-aliases-storage.service';
import { ChatVisitorTokensStore } from '../../services/chat-visitor-tokens.store';
import { isDeskBuilder } from '../../utils/chat-permissions.util';
import { closedSummary, isClosed } from '../../utils/conversation-close.util';
import { operatorName } from '../../utils/conversation-row.util';
import { microseconds, upsertMessage } from '../../utils/inbox-merge.util';
import { tickingNow } from '../../utils/ticking-now.util';
import {
    ChatOperatorReplySent,
    ChatThreadComposerComponent,
} from '../chat-thread-composer/chat-thread-composer.component';
import { ChatThreadHeaderComponent } from '../chat-thread-header/chat-thread-header.component';

// The closed banner's time changes form at midnight only ("14:05", then "Oct 5, 14:05"): a minute is close enough.
const CLOCK_TICK_MS = 60_000;

/**
 * The open conversation: its header, its messages (newest first in view, older ones paged in as the user scrolls up)
 * and its composer. A closed conversation is read-only: a banner says why it closed where the composer was. Needs the
 * chat page's `OpenConversationService` and `ChatVisitorTokensStore`.
 */
@Component({
    selector: 'app-chat-thread',
    imports: [
        DatePipe,
        RouterLink,
        AppSvgIconComponent,
        ButtonComponent,
        ChatMarkdownPipe,
        ChatThreadComposerComponent,
        ChatThreadHeaderComponent,
        JsonEditorComponent,
        SpinnerComponent,
    ],
    templateUrl: './chat-thread.component.html',
    styleUrl: './chat-thread.component.scss',
    host: {
        '[class.chat-thread--phone]': 'isPhone()',
    },
})
export class ChatThreadComponent {
    readonly conversation = input.required<ChatConversation>();
    /** The list the phone's Back returns to: the desk name or All desks; empty while not known. */
    readonly listTitle = input('');
    readonly isAllBindings = input(false);

    private readonly header = viewChild(ChatThreadHeaderComponent);
    private readonly composer = viewChild(ChatThreadComposerComponent);
    private readonly threadScroller = viewChild<ElementRef<HTMLElement>>('threadScroller');
    private readonly olderSentinel = viewChild<ElementRef<HTMLElement>>('olderSentinel');
    private readonly closedBannerElement = viewChild<ElementRef<HTMLElement>>('closedBannerElement');

    readonly messages = signal<ChatOperatorMessage[]>([]);
    readonly hasOlderMessages = signal(false);
    /** Messages whose raw data is open. */
    protected readonly openRawIds = signal<ReadonlySet<string>>(new Set());
    readonly isLoadingOlder = signal(false);

    private readonly conversationId = computed(() => this.conversation().id);
    /** The conversation's desk; null while that desk is not known. */
    readonly binding = computed(
        () => this.desksStorage.desks().find((binding) => binding.id === this.conversation().binding_id) ?? null
    );
    readonly canUse = computed(() => this.permissionsService.can(ResourceCode.Chats, ActionCode.Use));
    private readonly canBuildDesks = computed(() => isDeskBuilder(this.permissionsService));
    private readonly canReadFlows = computed(() => this.permissionsService.can(ResourceCode.Flows, ActionCode.Read));
    /** Closed: read-only, with no actions, and a banner where the composer was. */
    readonly isClosed = computed(() => isClosed(this.conversation()));
    // The current time, for the banner's: it shows a date once the close is no longer today.
    private readonly now = tickingNow(CLOCK_TICK_MS);
    /** Why and when the conversation closed: "Closed · Resolved by Mike · 14:05"; empty while it is open. */
    readonly closedBanner = computed(() => {
        const conversation = this.conversation();
        if (!isClosed(conversation)) return '';
        const myUserId = this.profileService.currentUserSignal()?.id ?? null;
        return closedSummary(conversation, this.binding()?.style ?? null, myUserId, this.now(), this.locale);
    });
    /** The name visitors see on the user's replies on the conversation's desk; null until that desk is known. */
    readonly myNameOnConversationDesk = computed(() => {
        const binding = this.binding();
        return binding ? this.myAliasesStorage.visibleNameOn(binding) : null;
    });
    /** The user holds the conversation, which is still open: a closed one is nobody's to work on. */
    readonly isClaimedByMe = computed(() => {
        const conversation = this.conversation();
        const me = this.profileService.currentUserSignal();
        return (
            conversation.mode === 'human' &&
            !isClosed(conversation) &&
            !!me &&
            conversation.assigned_operator_id === me.id
        );
    });

    /**
     * A close takes away what the user was on (the composer, Resolve, the ⋯ menu): once the conversation turns
     * closed, the focus moves to the banner that says so, unless it is still somewhere on the page.
     */
    private readonly focusBannerOnClose = effect(() => {
        const id = this.conversationId();
        const closed = this.isClosed();
        untracked(() => {
            const turnedClosed = closed && this.openState?.id === id && !this.openState.closed;
            this.openState = { id, closed };
            if (!turnedClosed) return;
            afterNextRender(
                () => {
                    const active = this.document.activeElement;
                    if (!active || active === this.document.body || !active.isConnected) {
                        this.closedBannerElement()?.nativeElement.focus();
                    }
                },
                { injector: this.injector }
            );
        });
    });
    /**
     * Infinite scroll up: the sentinel row entering the thread viewport loads the next older page. Only after the
     * user scrolled this thread, so the first render (anchored at the bottom) does not page by itself. The thread
     * is a column-reverse scroller anchored at its end, so prepended messages leave the view where it was.
     */
    private readonly loadOlderOnSentinel = effect((onCleanup) => {
        const sentinel = this.olderSentinel()?.nativeElement;
        const root = this.threadScroller()?.nativeElement;
        if (!sentinel || !root || typeof IntersectionObserver === 'undefined') return;
        const observer = new IntersectionObserver(
            (entries) => {
                if (this.hasUserScrolled && entries.some((entry) => entry.isIntersecting)) this.loadOlderMessages();
            },
            { root }
        );
        observer.observe(sentinel);
        onCleanup(() => observer.disconnect());
    });
    // A test conversation started elsewhere (or before a reload) has no token here yet: get one to write as its visitor.
    // A closed one takes no more messages.
    private readonly fetchVisitorToken = effect(() => {
        const conversation = this.conversation();
        if (!conversation.is_test || !this.canBuildDesks() || isClosed(conversation)) return;
        untracked(() => this.visitorTokens.ensure(conversation.id));
    });
    private readonly loadThreadOnSelect = effect(() => {
        const id = this.conversationId();
        this.chatInboxStream.readyEpoch();
        untracked(() => this.loadThread(id));
    });
    // Not on a reconnect: the same messages stay on screen, open.
    private readonly closeRawDataOnSelect = effect(() => {
        this.conversationId();
        untracked(() => this.openRawIds.set(new Set()));
    });

    protected readonly isActionPending = inject(ChatConversationActionsService).isPending;
    protected readonly isPhone = inject(PhoneLayoutService).isPhone;
    protected readonly visitorTokens = inject(ChatVisitorTokensStore);

    private readonly chatApi = inject(ChatApiService);
    private readonly chatInboxStream = inject(ChatInboxStreamService);
    private readonly conversationActions = inject(ChatConversationActionsService);
    private readonly desksStorage = inject(ChatDesksStorageService);
    private readonly myAliasesStorage = inject(ChatMyAliasesStorageService);
    private readonly profileService = inject(ProfileService);
    private readonly permissionsService = inject(PermissionsService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly injector = inject(Injector);
    private readonly document = inject(DOCUMENT);
    private readonly locale = inject(LOCALE_ID);
    private threadId: string | null = null;
    private hasUserScrolled = false;
    // Bumped whenever the shown messages start over; an older page lands only in the thread it was requested for.
    private threadEpoch = 0;
    private olderRequest: Subscription | null = null;
    // The conversation shown last and whether it was closed, to tell a close from opening a closed conversation.
    private openState: { id: string; closed: boolean } | null = null;

    constructor() {
        this.chatInboxStream.messageCreated$
            .pipe(
                filter((event) => event.conversation_id === this.conversationId()),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((event) =>
                this.messages.update((list) =>
                    upsertMessage(list, {
                        id: event.id,
                        role: event.role,
                        content: event.content,
                        actions: event.actions,
                        action: event.action,
                        created_at: event.created_at,
                        // The inbox event carries no run id; the next page of messages fills it in.
                        session_id: null,
                        author_user_id: event.author_user_id,
                        author_name: event.author_name,
                        visible_name: event.visible_name,
                    })
                )
            );
    }

    /** Phones: the thread screen's Back, where the focus goes as the thread pushes in. */
    focusBack(): void {
        this.header()?.focusBack();
    }

    focusComposer(): void {
        this.composer()?.focus();
    }

    claim(conversation: ChatConversation): void {
        this.conversationActions.takeOver(conversation);
    }

    onOperatorMessageSent({ conversationId, message }: ChatOperatorReplySent): void {
        if (this.conversationId() === conversationId) this.messages.update((list) => upsertMessage(list, message));
    }

    // At the bottom a column-reverse scroller sits at 0: a scroll event there (a browser clamp when the thread
    // changes) is not the user scrolling up.
    onThreadScroll(): void {
        this.hasUserScrolled ||= (this.threadScroller()?.nativeElement.scrollTop ?? 0) !== 0;
    }

    loadOlderMessages(): void {
        const id = this.conversationId();
        const oldest = this.messages()[0];
        if (!oldest || this.isLoadingOlder()) return;
        this.isLoadingOlder.set(true);
        // Another thread opened meanwhile (even A → B → A) must not get this page prepended to its fresh start.
        const epoch = this.threadEpoch;
        let landed = false;
        this.olderRequest = this.chatApi
            .getMessages(id, oldest.id)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (page) => {
                    if (epoch !== this.threadEpoch) return;
                    landed = true;
                    this.messages.update((list) => page.reduce(upsertMessage, list));
                    this.hasOlderMessages.set(page.length === CHAT_MESSAGES_PAGE_SIZE);
                },
                error: (error: HttpErrorResponse) => {
                    this.isLoadingOlder.set(false);
                    this.toastService.error(extractHttpErrorMessage(error));
                },
                complete: () => {
                    this.isLoadingOlder.set(false);
                    // A page too short to push the sentinel out of view gets no new intersection: check after render.
                    // A page that added nothing older (all already listed) ends the chain.
                    if (landed && this.messages()[0]?.id !== oldest.id) {
                        afterNextRender(() => this.loadOlderIfSentinelInView(), { injector: this.injector });
                    }
                },
            });
    }

    /**
     * Who wrote an operator message: "You", their name, or "Operator #7" while the name is not known; then the name
     * visitors saw on it when that was another one: "Bea Agent · as Mike". Operators only see this line.
     */
    operatorLabel(message: ChatOperatorMessage): string {
        const author = this.operatorAuthor(message);
        const visibleName = message.visible_name;
        return visibleName && visibleName !== message.author_name ? `${author} · as ${visibleName}` : author;
    }

    /** The message's action payloads as JSON; null when it carries none. */
    rawData(message: ChatOperatorMessage): string | null {
        const { action, actions } = message;
        if (!action && !actions?.length) return null;
        const raw: Record<string, unknown> = {};
        if (action) raw['action'] = action;
        if (actions?.length) raw['actions'] = actions;
        return JSON.stringify(raw, null, 2);
    }

    onRawToggle(messageId: string, event: Event): void {
        const isOpen = (event.target as HTMLDetailsElement).open;
        this.openRawIds.update((ids) => {
            const next = new Set(ids);
            if (isOpen) next.add(messageId);
            else next.delete(messageId);
            return next;
        });
    }

    sessionLink(message: ChatOperatorMessage): unknown[] | null {
        const graphId = this.binding()?.graph_id;
        return message.session_id && graphId && this.canReadFlows()
            ? ['/graph', graphId, 'session', message.session_id]
            : null;
    }

    private operatorAuthor(message: ChatOperatorMessage): string {
        const authorId = message.author_user_id;
        if (authorId === null) return message.author_name || '—';
        if (authorId === this.profileService.currentUserSignal()?.id) return 'You';
        return operatorName(authorId, message.author_name);
    }

    // A reload of the same thread (a reconnect) merges into what is shown; only another conversation starts empty.
    private loadThread(id: string): void {
        if (id !== this.threadId) {
            this.threadId = id;
            this.restartPaging();
            this.hasUserScrolled = false;
            this.messages.set([]);
            this.hasOlderMessages.set(false);
        }
        this.chatApi
            .getMessages(id)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (page) => {
                    if (this.conversationId() !== id) return;
                    this.messages.set(page.reduce(upsertMessage, this.withoutGapBefore(this.messages(), page)));
                    this.hasOlderMessages.set(page.length === CHAT_MESSAGES_PAGE_SIZE);
                },
                error: (error: HttpErrorResponse) => this.toastService.error(extractHttpErrorMessage(error)),
            });
    }

    /**
     * The shown messages a fresh newest page can merge with. A full page sharing none of them may sit above a hole
     * (more than a page arrived while the stream was down): the shown ones older than the page go, so paging back
     * from the page fetches them again in order; newer ones (streamed since the page was read) stay.
     */
    private withoutGapBefore(shown: ChatOperatorMessage[], page: ChatOperatorMessage[]): ChatOperatorMessage[] {
        if (page.length < CHAT_MESSAGES_PAGE_SIZE || !shown.length) return shown;
        const pageIds = new Set(page.map((message) => message.id));
        if (shown.some((message) => pageIds.has(message.id))) return shown;
        // An older page on its way was asked for before the dropped messages: it would rebuild the hole.
        this.restartPaging();
        const pageStart = Math.min(...page.map((message) => microseconds(message.created_at)));
        return shown.filter((message) => microseconds(message.created_at) >= pageStart);
    }

    // Drops an older page still on its way: it belongs to messages no longer shown.
    private restartPaging(): void {
        this.threadEpoch++;
        this.olderRequest?.unsubscribe();
        this.olderRequest = null;
        this.isLoadingOlder.set(false);
    }

    private loadOlderIfSentinelInView(): void {
        const sentinel = this.olderSentinel()?.nativeElement;
        const root = this.threadScroller()?.nativeElement;
        if (!sentinel || !root || !this.hasUserScrolled || !this.hasOlderMessages()) return;
        const sentinelBox = sentinel.getBoundingClientRect();
        const rootBox = root.getBoundingClientRect();
        if (sentinelBox.bottom > rootBox.top && sentinelBox.top < rootBox.bottom) this.loadOlderMessages();
    }
}
