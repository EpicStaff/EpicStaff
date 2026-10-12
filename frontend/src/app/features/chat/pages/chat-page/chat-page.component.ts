import { A11yModule } from '@angular/cdk/a11y';
import { Dialog } from '@angular/cdk/dialog';
import { OverlayModule } from '@angular/cdk/overlay';
import { DatePipe } from '@angular/common';
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
    linkedSignal,
    signal,
    untracked,
    viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Router, RouterLink } from '@angular/router';
import {
    AppSvgIconComponent,
    ButtonComponent,
    ConfirmationDialogService,
    ListComponent,
    SectionHeaderComponent,
    SpinnerComponent,
} from '@shared/components';
import { CollapseOnOverflowDirective, HideInlineSubtitleOnOverflowDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import { extractHttpErrorMessage } from '@shared/utils';
import { filter, Observable, Subscription, switchMap } from 'rxjs';

import { ActiveOrgService } from '../../../../services/auth/active-org.service';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ProfileService } from '../../../../services/auth/profile.service';
import { ToastService } from '../../../../services/notifications';
import { ChatBindingStatusComponent } from '../../components/chat-binding-status/chat-binding-status.component';
import {
    ChatBindingsDialogComponent,
    ChatBindingsDialogData,
} from '../../components/chat-bindings-dialog/chat-bindings-dialog.component';
import {
    ChatOperatorReplySent,
    ChatThreadComposerComponent,
} from '../../components/chat-thread-composer/chat-thread-composer.component';
import { ChatUsageRingComponent } from '../../components/chat-usage-ring/chat-usage-ring.component';
import {
    CHAT_MODE_LABELS,
    ChatBinding,
    ChatConversation,
    ChatErrorBody,
    ChatInboxSection,
    ChatMode,
    ChatOperatorMessage,
} from '../../models/chat.model';
import { CHAT_MESSAGES_PAGE_SIZE, ChatApiService } from '../../services/chat-api.service';
import { ChatBindingActionsService } from '../../services/chat-binding-actions.service';
import { ChatInboxStreamService } from '../../services/chat-inbox-stream.service';
import { actionLabel } from '../../utils/action-label.util';
import { INBOX_ORDER, inboxSection, placeRow, upsertMessage } from '../../utils/inbox-merge.util';

const ALL_BINDINGS = '';
// Pinned to the top of the sidebar; every other collapsed section rests at the bottom.
const TOP_SECTION: ChatInboxSection = 'human';

interface InboxSectionState {
    rows: ChatConversation[];
    nextCursor: string | null;
    // Last row fetched while more pages remain; live rows sorting after it wait for Load more.
    boundary: ChatConversation | null;
    isLoading: boolean;
}

interface InboxSectionView {
    id: ChatInboxSection;
    label: string;
    icon: string;
    emptyTitle: string;
    emptyDescription: string;
}

const INBOX_SECTIONS: InboxSectionView[] = [
    {
        id: 'human',
        label: 'Needs a human',
        icon: 'user',
        emptyTitle: 'Nothing waiting',
        emptyDescription: 'Conversations the bot hands off, or an operator takes over, line up here.',
    },
    {
        id: 'bot',
        label: 'Bot',
        icon: 'robot',
        emptyTitle: 'No conversations yet',
        emptyDescription: 'Conversations from your website the bot is answering show up here.',
    },
    {
        id: 'test',
        label: 'Tests',
        icon: 'player-play-filled',
        emptyTitle: 'No test conversations',
        emptyDescription: 'Start one with Test in a binding.',
    },
];

const emptySection = (): InboxSectionState => ({ rows: [], nextCursor: null, boundary: null, isLoading: false });

/** A row is listed in its own section; the server hides bot and test conversations without messages. */
const belongsTo = (row: ChatConversation, section: ChatInboxSection): boolean =>
    inboxSection(row) === section && (section === 'human' || !!row.last_message_at);

@Component({
    selector: 'app-chat-page',
    imports: [
        A11yModule,
        DatePipe,
        MatTooltipModule,
        OverlayModule,
        RouterLink,
        ChatUsageRingComponent,
        AppSvgIconComponent,
        ButtonComponent,
        ChatBindingStatusComponent,
        ChatThreadComposerComponent,
        CollapseOnOverflowDirective,
        HideInlineSubtitleOnOverflowDirective,
        ListComponent,
        SectionHeaderComponent,
        SpinnerComponent,
    ],
    templateUrl: './chat-page.component.html',
    styleUrls: ['./chat-page.component.scss'],
})
export class ChatPageComponent {
    /** From the route: the binding this workspace is scoped to; absent on the all-bindings inbox. */
    readonly bindingId = input<string>();

    private readonly composer = viewChild(ChatThreadComposerComponent);
    private readonly threadScroller = viewChild<ElementRef<HTMLElement>>('threadScroller');
    private readonly olderSentinel = viewChild<ElementRef<HTMLElement>>('olderSentinel');

    readonly bindings = signal<ChatBinding[]>([]);
    readonly inbox = signal<Record<ChatInboxSection, InboxSectionState>>({
        human: emptySection(),
        bot: emptySection(),
        test: emptySection(),
    });
    // Bot and Tests start collapsed: the human queue is the work; the others are there to look into.
    readonly expanded = signal<Record<ChatInboxSection, boolean>>({ human: true, bot: false, test: false });
    readonly selectedId = signal<string | null>(null);
    readonly messages = signal<ChatOperatorMessage[]>([]);
    readonly hasOlderMessages = signal(false);
    readonly isActionPending = signal(false);
    readonly isLoadingOlder = signal(false);
    readonly isStartingTest = signal(false);
    /** Visitor tokens of the test conversations started on this page; the server issues one only on create. */
    readonly visitorTokens = signal<Record<string, string>>({});
    // The test conversation a visitor token is being fetched for, and the ones whose fetch failed (until reselected).
    readonly visitorTokenPendingFor = signal<string | null>(null);
    readonly visitorTokenErrors = signal<Record<string, string>>({});
    private readonly selectedRow = signal<ChatConversation | null>(null);
    // The route binding the last bindings response was requested for.
    private readonly bindingsLoadedFor = signal<string | undefined | null>(null);
    // The filter whose first human page last landed: until then the human rows still belong to the previous filter.
    private readonly humanLoadedFor = signal<string | null>(null);

    // The conversation list's `binding` filter: the route binding, or every binding.
    readonly bindingFilter = computed(() => this.bindingId() ?? ALL_BINDINGS);
    readonly isAllBindings = computed(() => !this.bindingId());
    // Null until the bindings load; an id they do not list sends the user back to the bindings list.
    readonly routeBinding = computed(() => this.bindings().find((binding) => binding.id === this.bindingId()) ?? null);
    readonly title = computed(() =>
        this.isAllBindings() ? 'Inbox · all bindings' : (this.routeBinding()?.name ?? '')
    );
    readonly pauseLabel = computed(() => (this.routeBinding()?.is_active ? 'Pause' : 'Resume'));
    readonly pauseIcon = computed(() => (this.routeBinding()?.is_active ? 'pause' : 'activate'));
    readonly canStartTest = computed(() => !!this.routeBinding() && !this.isStartingTest());
    // The selection survives a reload that no longer lists it; its last known row keeps the header up.
    readonly selected = computed(() => {
        const id = this.selectedId();
        const fallback = this.selectedRow();
        return this.findRow(id) ?? (fallback?.id === id ? fallback : null);
    });
    readonly selectedBinding = computed(
        () => this.bindings().find((binding) => binding.id === this.selected()?.binding_id) ?? null
    );
    readonly canUse = computed(() => this.permissionsService.can(ResourceCode.Chats, ActionCode.Use));
    readonly canUpdate = computed(() => this.permissionsService.can(ResourceCode.Chats, ActionCode.Update));
    readonly isClaimedByMe = computed(() => {
        const conversation = this.selected();
        const me = this.profileService.currentUserSignal();
        return conversation?.mode === 'human' && !!me && conversation.assigned_operator_id === me.id;
    });
    // Who holds the open conversation, for the mode pill's tooltip: null while nobody does.
    readonly holderLabel = computed(() => {
        const operatorId = this.selected()?.assigned_operator_id ?? null;
        if (operatorId === null) return null;
        return operatorId === this.profileService.currentUserSignal()?.id ? 'you' : `Operator #${operatorId}`;
    });
    readonly isThreadMenuOpen = signal(false);
    /**
     * Without handoff a binding has no human queue, unless conversations handed off before it was turned off still
     * wait there: hiding those would leave them unreachable. Decided only once the human page for the current filter
     * has landed; meanwhile the previous decision stands, so a switch never flashes the section in and out.
     */
    private readonly showsHumanSection = linkedSignal<
        { bindingId: string; handoffEnabled: boolean; isLoaded: boolean; hasRows: boolean },
        boolean
    >({
        source: () => {
            const bindingId = this.bindingFilter();
            const binding = this.bindings().find((item) => item.id === bindingId);
            return {
                bindingId,
                handoffEnabled: binding?.handoff_enabled !== false,
                isLoaded: this.humanLoadedFor() === bindingId,
                hasRows: this.inbox().human.rows.length > 0,
            };
        },
        computation: (source, previous) => {
            if (!source.bindingId || source.handoffEnabled) return true;
            return source.isLoaded ? source.hasRows : (previous?.value ?? true);
        },
    });
    /**
     * Same layout as the agents explorer: the lowest expanded section fills the leftover height and scrolls, and
     * the first section below it is pushed to the bottom. The top section stays at the top.
     */
    protected readonly sectionLayout = computed(() => {
        const visible = INBOX_SECTIONS.filter(({ id }) => id !== 'human' || this.showsHumanSection());
        const expanded = this.expanded();
        const lastExpanded = visible.reduce((last, { id }, index) => (expanded[id] ? index : last), -1);
        const bottomAnchor = visible.findIndex(({ id }, index) => index > lastExpanded && id !== TOP_SECTION);
        return visible.map((section, index) => ({
            section,
            fills: index === lastExpanded,
            anchorsBottom: index === bottomAnchor,
        }));
    });

    /** Every `ready` means the stream is live from now, so a reload after it is complete (step 2 ruling). */
    private readonly reloadOnReady = effect(() => {
        this.chatInboxStream.readyEpoch();
        this.bindingFilter();
        untracked(() => this.reloadInbox());
    });
    // A route move to another binding reloads too: the list may predate that binding.
    private readonly reloadBindings = effect(() => {
        this.chatInboxStream.readyEpoch();
        this.bindingId();
        untracked(() => this.loadBindings());
    });
    // Decided only on a list loaded for the current route binding, so a binding created meanwhile is not refused.
    private readonly leaveUnknownBinding = effect(() => {
        const bindingId = this.bindingId();
        const bindings = this.bindings();
        if (!bindingId || this.bindingsLoadedFor() !== bindingId) return;
        if (bindings.some((binding) => binding.id === bindingId)) return;
        untracked(() => {
            // An org switch the org effect has not handled yet is not a deleted binding either.
            const orgSwitched = this.orgId !== undefined && this.activeOrgService.activeOrgId() !== this.orgId;
            if (this.isLeavingForOrgSwitch || orgSwitched) return;
            this.toastService.error('This chat binding does not exist anymore.');
            void this.router.navigate(['/chat-bindings']);
        });
    });
    // A binding belongs to one org: after an org switch its page has nothing to show, so it goes back to the list
    // without a message (the binding was not deleted). The all-bindings inbox simply reloads for the new org.
    private readonly leaveOnOrgSwitch = effect(() => {
        const orgId = this.activeOrgService.activeOrgId();
        untracked(() => {
            // null is a logout: the auth flow navigates away itself.
            if (this.orgId !== undefined && orgId !== null && orgId !== this.orgId && this.bindingId()) {
                this.isLeavingForOrgSwitch = true;
                void this.router.navigate(['/chat-bindings']).finally(() => (this.isLeavingForOrgSwitch = false));
            }
            this.orgId = orgId;
        });
    });
    // Another binding's conversation must not stay open when the route moves to a different scope.
    private readonly clearSelectionOnScope = effect(() => {
        const scope = this.bindingFilter();
        untracked(() => {
            if (this.scope !== null && scope !== this.scope) this.selectedId.set(null);
            this.scope = scope;
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
    private readonly fetchVisitorToken = effect(() => {
        const conversation = this.selected();
        if (!conversation?.is_test || !this.canUse()) return;
        untracked(() => this.ensureVisitorToken(conversation.id));
    });
    private readonly loadThreadOnSelect = effect(() => {
        const id = this.selectedId();
        this.chatInboxStream.readyEpoch();
        untracked(() => this.loadThread(id));
    });

    protected readonly ResourceCode = ResourceCode;
    protected readonly actionLabel = actionLabel;
    protected readonly trackConversation = (_index: number, item: ChatConversation): string => item.id;

    private readonly chatApi = inject(ChatApiService);
    private readonly chatInboxStream = inject(ChatInboxStreamService);
    private readonly profileService = inject(ProfileService);
    private readonly permissionsService = inject(PermissionsService);
    private readonly confirmationDialogService = inject(ConfirmationDialogService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly dialog = inject(Dialog);
    private readonly router = inject(Router);
    private readonly activeOrgService = inject(ActiveOrgService);
    private readonly bindingActions = inject(ChatBindingActionsService);
    private readonly injector = inject(Injector);
    private readonly listRequests: Partial<Record<ChatInboxSection, Subscription>> = {};
    // Rows streamed since the last reload: newer than any page fetched meanwhile, so they win over the first
    // pages and over Load more pages, in whichever section they now belong to.
    private rowsSinceReload = new Map<string, ChatConversation>();
    private threadId: string | null = null;
    private hasUserScrolled = false;
    // Bumped whenever another thread opens; an older page lands only in the thread it was requested for.
    private threadEpoch = 0;
    private olderRequest: Subscription | null = null;
    private scope: string | null = null;
    private orgId: number | null | undefined = undefined;
    private isLeavingForOrgSwitch = false;
    private bindingsRequest: Subscription | null = null;

    constructor() {
        this.chatInboxStream.conversationUpdated$
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((row) => this.applyRow(row));
        this.chatInboxStream.messageCreated$
            .pipe(
                filter((event) => event.conversation_id === this.selectedId()),
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
                        // The inbox event has no operator fields; the POST response (if any) fills them in.
                        session_id: null,
                        author_user_id: null,
                    })
                )
            );
    }

    selectConversation(id: string): void {
        this.isThreadMenuOpen.set(false);
        this.selectedRow.set(this.findRow(id));
        // Selecting again retries a failed visitor token.
        const hadFailed = !!this.visitorTokenErrors()[id];
        if (hadFailed) {
            this.visitorTokenErrors.update((errors) => {
                const rest = { ...errors };
                delete rest[id];
                return rest;
            });
        }
        this.selectedId.set(id);
        const row = this.selected();
        if (hadFailed && row?.is_test && this.canUse()) this.ensureVisitorToken(id);
    }

    // The created row seeds the header: its stream event may already have passed, before it was selected.
    onTestConversationStarted(conversation: ChatConversation): void {
        this.selectedRow.set(conversation);
        this.selectedId.set(conversation.id);
        this.expanded.update((state) => ({ ...state, test: true }));
    }

    /** Tests this workspace's binding; works on a paused one too (a test skips the active and origin checks). */
    startTest(): void {
        const bindingId = this.routeBinding()?.id;
        if (!bindingId || this.isStartingTest()) return;
        this.isStartingTest.set(true);
        this.chatApi
            .createTestConversation(bindingId)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: ({ conversation, visitor_token }) => {
                    this.isStartingTest.set(false);
                    this.visitorTokens.update((tokens) => ({ ...tokens, [conversation.id]: visitor_token }));
                    this.onTestConversationStarted(conversation);
                    afterNextRender(() => this.composer()?.focus(), { injector: this.injector });
                },
                error: (error: HttpErrorResponse) => {
                    this.isStartingTest.set(false);
                    this.toastService.error(extractHttpErrorMessage(error));
                },
            });
    }

    onOperatorMessageSent({ conversationId, message }: ChatOperatorReplySent): void {
        if (this.selectedId() === conversationId) this.messages.update((list) => upsertMessage(list, message));
    }

    toggleSection(section: ChatInboxSection): void {
        this.expanded.update((state) => ({ ...state, [section]: !state[section] }));
    }

    loadMoreConversations(section: ChatInboxSection): void {
        const cursor = this.inbox()[section].nextCursor;
        if (cursor) this.loadPage(section, cursor);
    }

    // At the bottom a column-reverse scroller sits at 0: a scroll event there (a browser clamp when the thread
    // changes) is not the user scrolling up.
    onThreadScroll(): void {
        this.hasUserScrolled ||= (this.threadScroller()?.nativeElement.scrollTop ?? 0) !== 0;
    }

    loadOlderMessages(): void {
        const id = this.selectedId();
        const oldest = this.messages()[0];
        if (!id || !oldest || this.isLoadingOlder()) return;
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

    claim(conversation: ChatConversation): void {
        this.runAction(
            this.chatApi.claim(conversation.id),
            (row) => this.applyRow(row),
            (error) => {
                if ((error.error as ChatErrorBody | null)?.code !== 'claimed_by_other') return null;
                return this.confirmationDialogService
                    .confirm({
                        title: 'Take over conversation',
                        message: 'Another operator holds this conversation. Take it over?',
                        confirmText: 'Take over',
                        cancelText: 'Cancel',
                        type: 'danger',
                    })
                    .pipe(
                        filter((confirmed) => confirmed === true),
                        switchMap(() => this.chatApi.claim(conversation.id, true))
                    );
            }
        );
    }

    release(conversation: ChatConversation): void {
        this.runAction(this.chatApi.release(conversation.id), (row) => this.applyRow(row));
    }

    openSettings(): void {
        const binding = this.routeBinding();
        if (!binding) return;
        this.dialog
            .open<unknown, ChatBindingsDialogData>(ChatBindingsDialogComponent, { width: '720px', data: { binding } })
            .closed.pipe(takeUntilDestroyed(this.destroyRef))
            // The dialog closes without a result; edits may have happened, so reload on every close.
            .subscribe(() => this.loadBindings());
    }

    // The same path as the bindings list's Copy snippet.
    copySnippet(): void {
        const binding = this.routeBinding();
        if (binding) this.bindingActions.copySnippet(binding);
    }

    togglePause(): void {
        const binding = this.routeBinding();
        if (!binding) return;
        (binding.is_active ? this.bindingActions.pause(binding) : this.bindingActions.resume(binding))
            .pipe(filter(Boolean), takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.loadBindings());
    }

    protected modeLabel(mode: ChatMode): string {
        return CHAT_MODE_LABELS[mode];
    }

    operatorLabel(operatorId: number | null): string {
        if (operatorId === null) return '—';
        return operatorId === this.profileService.currentUserSignal()?.id ? 'You' : `Operator #${operatorId}`;
    }

    sessionLink(message: ChatOperatorMessage): unknown[] | null {
        const graphId = this.selectedBinding()?.graph_id;
        return message.session_id && graphId ? ['/graph', graphId, 'session', message.session_id] : null;
    }

    /**
     * One mutation at a time. `recover` may turn an error into a follow-up request (the forced claim);
     * a follow-up that completes without emitting (the operator cancelled the confirm) just releases the lock.
     */
    private runAction<T>(
        request$: Observable<T>,
        onDone?: (result: T) => void,
        recover?: (error: HttpErrorResponse) => Observable<T> | null
    ): void {
        if (this.isActionPending()) return;
        this.isActionPending.set(true);
        request$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
            next: (result) => onDone?.(result),
            error: (error: HttpErrorResponse) => {
                this.isActionPending.set(false);
                const followUp = recover?.(error) ?? null;
                if (followUp) this.runAction(followUp, onDone);
                else this.toastService.error(extractHttpErrorMessage(error));
            },
            complete: () => this.isActionPending.set(false),
        });
    }

    /**
     * A stream or claim/release row: newest state wins, in the lists and for the selected header. It leaves the
     * section it was in and is placed by its section's order, so a handed-off row joins the end of the human queue
     * and a reply on a human row does not move it.
     */
    private applyRow(row: ChatConversation): void {
        if (row.id === this.selectedId()) this.selectedRow.set(row);
        const bindingId = this.bindingFilter();
        if (bindingId && row.binding_id !== bindingId) return;
        this.rowsSinceReload.set(row.id, row);
        this.inbox.update((inbox) => {
            const next = { ...inbox };
            for (const { id: section } of INBOX_SECTIONS) {
                const state = inbox[section];
                const rows = belongsTo(row, section)
                    ? placeRow(state.rows, row, INBOX_ORDER[section], state.boundary)
                    : state.rows.filter((item) => item.id !== row.id);
                next[section] = { ...state, rows };
            }
            return next;
        });
    }

    // The lists stay on screen until their first pages replace them: `ready` fires on every reconnect.
    private reloadInbox(): void {
        this.rowsSinceReload = new Map();
        for (const { id: section } of INBOX_SECTIONS) this.loadPage(section, null);
    }

    private loadPage(section: ChatInboxSection, cursor: string | null): void {
        const binding = this.bindingFilter() || null;
        // A failed reload must not leave the previous filter's cursor behind for Load more.
        this.patchSection(
            section,
            cursor ? { isLoading: true } : { isLoading: true, nextCursor: null, boundary: null }
        );
        // Only the latest request per section may land: an older response would overwrite fresher rows or the cursor.
        this.listRequests[section]?.unsubscribe();
        this.listRequests[section] = this.chatApi
            .getConversations({ section, binding, cursor })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (result) => {
                    if ((this.bindingFilter() || null) !== binding) return;
                    if (section === 'human' && !cursor) this.humanLoadedFor.set(binding ?? ALL_BINDINGS);
                    const order = INBOX_ORDER[section];
                    const boundary = result.next_cursor ? (result.results.at(-1) ?? null) : null;
                    const pageIds = new Set(result.results.map((item) => item.id));
                    // Rows the server returned unchanged are in its window by definition and are never filtered.
                    const serverRows = result.results.filter((item) => !this.rowsSinceReload.has(item.id));
                    // Everything else is ours: the rows already listed (Load more only) and every row streamed since
                    // the reload, which also covers a row dropped past the old boundary while this request was in
                    // flight. Streamed copies are newer and win; one that changed section is listed by the other.
                    const ours = new Map<string, ChatConversation>(
                        cursor ? this.inbox()[section].rows.map((item) => [item.id, item]) : []
                    );
                    this.rowsSinceReload.forEach((item, id) => ours.set(id, item));
                    const oursInWindow = [...ours.values()].filter(
                        (item) =>
                            belongsTo(item, section) &&
                            (!pageIds.has(item.id) || this.rowsSinceReload.has(item.id)) &&
                            (!boundary || order(item, boundary) <= 0)
                    );
                    const rows = [...serverRows, ...oursInWindow].sort(order);
                    this.patchSection(section, { rows, nextCursor: result.next_cursor, boundary, isLoading: false });
                },
                error: (error: HttpErrorResponse) => {
                    this.patchSection(section, { isLoading: false });
                    this.toastService.error(extractHttpErrorMessage(error));
                },
            });
    }

    private patchSection(section: ChatInboxSection, patch: Partial<InboxSectionState>): void {
        this.inbox.update((inbox) => ({ ...inbox, [section]: { ...inbox[section], ...patch } }));
    }

    private findRow(id: string | null): ChatConversation | null {
        const inbox = this.inbox();
        return INBOX_SECTIONS.flatMap(({ id: section }) => inbox[section].rows).find((item) => item.id === id) ?? null;
    }

    // A reload of the same thread merges into what is shown; only a different selection starts empty.
    private loadThread(id: string | null): void {
        if (id !== this.threadId) {
            this.threadId = id;
            this.threadEpoch++;
            this.olderRequest?.unsubscribe();
            this.olderRequest = null;
            this.isLoadingOlder.set(false);
            this.hasUserScrolled = false;
            this.messages.set([]);
            this.hasOlderMessages.set(false);
        }
        if (!id) return;
        this.chatApi
            .getMessages(id)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (page) => {
                    if (this.selectedId() !== id) return;
                    this.messages.update((list) => page.reduce(upsertMessage, list));
                    this.hasOlderMessages.set(page.length === CHAT_MESSAGES_PAGE_SIZE);
                },
                error: (error: HttpErrorResponse) => this.toastService.error(extractHttpErrorMessage(error)),
            });
    }

    private ensureVisitorToken(conversationId: string): void {
        if (this.visitorTokens()[conversationId] || this.visitorTokenErrors()[conversationId]) return;
        if (this.visitorTokenPendingFor() === conversationId) return;
        this.visitorTokenPendingFor.set(conversationId);
        this.chatApi
            .issueVisitorToken(conversationId)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                // Kept even after the operator moved on: it stays valid for its conversation, so returning to it
                // mints nothing new. The composer only shows the open conversation's token.
                next: ({ visitor_token }) =>
                    this.visitorTokens.update((tokens) => ({ ...tokens, [conversationId]: visitor_token })),
                error: () => {
                    if (this.visitorTokenPendingFor() === conversationId) this.visitorTokenPendingFor.set(null);
                    if (this.selectedId() !== conversationId) return;
                    this.visitorTokenErrors.update((errors) => ({
                        ...errors,
                        [conversationId]: "Couldn't get a visitor token. Select the conversation again to retry.",
                    }));
                },
                complete: () => {
                    if (this.visitorTokenPendingFor() === conversationId) this.visitorTokenPendingFor.set(null);
                },
            });
    }

    private loadOlderIfSentinelInView(): void {
        const sentinel = this.olderSentinel()?.nativeElement;
        const root = this.threadScroller()?.nativeElement;
        if (!sentinel || !root || !this.hasUserScrolled || !this.hasOlderMessages()) return;
        const sentinelBox = sentinel.getBoundingClientRect();
        const rootBox = root.getBoundingClientRect();
        if (sentinelBox.bottom > rootBox.top && sentinelBox.top < rootBox.bottom) this.loadOlderMessages();
    }

    private loadBindings(): void {
        const requestedFor = this.bindingId();
        // Only the latest list may land: an older one could drop a binding the route just moved to.
        this.bindingsRequest?.unsubscribe();
        this.bindingsRequest = this.chatApi
            .getBindings()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (bindings) => {
                    this.bindings.set(bindings);
                    this.bindingsLoadedFor.set(requestedFor);
                },
                error: (error: HttpErrorResponse) => this.toastService.error(extractHttpErrorMessage(error)),
            });
    }
}
