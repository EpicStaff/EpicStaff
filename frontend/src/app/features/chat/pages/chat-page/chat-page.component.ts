import { A11yModule } from '@angular/cdk/a11y';
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
    signal,
    untracked,
    viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Router, RouterLink } from '@angular/router';
import { AppSvgIconComponent, ButtonComponent, SpinnerComponent } from '@shared/components';
import { CollapseOnOverflowDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import { extractHttpErrorMessage } from '@shared/utils';
import { filter, merge, Subscription } from 'rxjs';

import { ActiveOrgService } from '../../../../services/auth/active-org.service';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ProfileService } from '../../../../services/auth/profile.service';
import { ToastService } from '../../../../services/notifications';
import { ChatBindingStatusComponent } from '../../components/chat-binding-status/chat-binding-status.component';
import {
    ChatOperatorReplySent,
    ChatThreadComposerComponent,
} from '../../components/chat-thread-composer/chat-thread-composer.component';
import { ChatUsageRingComponent } from '../../components/chat-usage-ring/chat-usage-ring.component';
import { ConversationListComponent } from '../../components/conversation-list/conversation-list.component';
import { CHAT_MODE_LABELS, ChatConversation, ChatMode, ChatOperatorMessage } from '../../models/chat.model';
import { CHAT_MESSAGES_PAGE_SIZE, ChatApiService } from '../../services/chat-api.service';
import { ChatBindingActionsService } from '../../services/chat-binding-actions.service';
import { ChatConversationActionsService } from '../../services/chat-conversation-actions.service';
import { ChatDesksStorageService } from '../../services/chat-desks-storage.service';
import { ChatInboxStreamService } from '../../services/chat-inbox-stream.service';
import { actionLabel } from '../../utils/action-label.util';
import { operatorName, visitorName } from '../../utils/conversation-row.util';
import { upsertMessage } from '../../utils/inbox-merge.util';

const ALL_DESKS_ROUTE: readonly string[] = ['/chat-bindings', 'all'];

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
        ConversationListComponent,
        SpinnerComponent,
    ],
    templateUrl: './chat-page.component.html',
    styleUrls: ['./chat-page.component.scss'],
})
export class ChatPageComponent {
    /** From the route: the binding this workspace is scoped to; absent on the all-bindings inbox. */
    readonly bindingId = input<string>();

    private readonly composer = viewChild(ChatThreadComposerComponent);
    private readonly conversationList = viewChild(ConversationListComponent);
    private readonly threadScroller = viewChild<ElementRef<HTMLElement>>('threadScroller');
    private readonly olderSentinel = viewChild<ElementRef<HTMLElement>>('olderSentinel');

    /**
     * The conversation as it was selected (or started as a test), kept current from the stream and from actions. What
     * the thread shows while the list does not have it: a test conversation without messages, a row past a loaded page.
     */
    private readonly held = signal<ChatConversation | null>(null);
    readonly messages = signal<ChatOperatorMessage[]>([]);
    readonly hasOlderMessages = signal(false);
    readonly isLoadingOlder = signal(false);
    readonly isStartingTest = signal(false);
    /** Visitor tokens of the test conversations started on this page; the server issues one only on create. */
    readonly visitorTokens = signal<Record<string, string>>({});
    // The test conversation a visitor token is being fetched for, and the ones whose fetch failed (until reselected).
    readonly visitorTokenPendingFor = signal<string | null>(null);
    readonly visitorTokenErrors = signal<Record<string, string>>({});
    // The desk list asked for once the route moved to a desk the list lacked: only that list can say it is gone.
    private readonly deskListRequestedFor = signal<{ bindingId: string; request: number } | null>(null);

    readonly selectedId = computed(() => this.held()?.id ?? null);
    /**
     * The open conversation: the list's row when it lists it, so a reconnect reload (another operator took it over
     * meanwhile) reaches the header and the composer; else the held row. Matched by id, as the list's `selectedId`
     * input catches up one change detection later.
     */
    readonly selected = computed(() => {
        const held = this.held();
        const listed = this.conversationList()?.selectedRow();
        return listed && listed.id === held?.id ? listed : held;
    });
    readonly isAllBindings = computed(() => !this.bindingId());
    // Null until the desks load; an id they do not list sends the user back to All desks.
    readonly routeBinding = computed(
        () => this.desksStorage.desks().find((binding) => binding.id === this.bindingId()) ?? null
    );
    readonly title = computed(() => (this.isAllBindings() ? 'All desks' : (this.routeBinding()?.name ?? '')));
    readonly pauseLabel = computed(() => (this.routeBinding()?.is_active ? 'Pause' : 'Resume'));
    readonly pauseIcon = computed(() => (this.routeBinding()?.is_active ? 'pause' : 'activate'));
    readonly canStartTest = computed(() => !!this.routeBinding() && !this.isStartingTest());
    readonly selectedBinding = computed(
        () => this.desksStorage.desks().find((binding) => binding.id === this.selected()?.binding_id) ?? null
    );
    readonly canUse = computed(() => this.permissionsService.can(ResourceCode.Chats, ActionCode.Use));
    readonly canUpdate = computed(() => this.permissionsService.can(ResourceCode.Chats, ActionCode.Update));
    readonly canDelete = computed(() => this.permissionsService.can(ResourceCode.Chats, ActionCode.Delete));
    readonly isClaimedByMe = computed(() => {
        const conversation = this.selected();
        const me = this.profileService.currentUserSignal();
        return conversation?.mode === 'human' && !!me && conversation.assigned_operator_id === me.id;
    });
    // Who holds the open conversation, for the mode pill's tooltip: "you", their name or "Operator #7"; null while nobody does.
    readonly holderLabel = computed(() => {
        const conversation = this.selected();
        const operatorId = conversation?.assigned_operator_id ?? null;
        if (operatorId === null) return null;
        if (operatorId === this.profileService.currentUserSignal()?.id) return 'you';
        return operatorName(operatorId, conversation?.assigned_operator_name ?? null);
    });
    readonly isThreadMenuOpen = signal(false);

    /**
     * A route desk the list lacks may be newer than the list (created in another tab): once no list is loading, ask for
     * a fresh one, and leave only if that list, or a later one, still lacks it.
     */
    private readonly leaveUnknownBinding = effect(() => {
        const bindingId = this.bindingId();
        const desks = this.desksStorage.desks();
        const landedRequest = this.desksStorage.landedRequest();
        if (!bindingId || desks.some((binding) => binding.id === bindingId)) return;
        if (this.desksStorage.isLoading() || this.desksStorage.loadFailed()) return;
        untracked(() => {
            const requested = this.deskListRequestedFor();
            if (requested?.bindingId !== bindingId) {
                const request = this.desksStorage.reload();
                // None sent: no active org (a logout), so nothing to decide either.
                if (request !== null) this.deskListRequestedFor.set({ bindingId, request });
                return;
            }
            if (landedRequest < requested.request) return;
            // An org switch the org effect has not handled yet is not a deleted binding either.
            const orgSwitched = this.orgId !== undefined && this.activeOrgService.activeOrgId() !== this.orgId;
            if (this.isLeavingForOrgSwitch || orgSwitched) return;
            this.toastService.error('This desk no longer exists.');
            void this.router.navigate(ALL_DESKS_ROUTE);
        });
    });
    // A binding belongs to one org: after an org switch its page has nothing to show, so it goes back to All desks
    // without a message (the binding was not deleted). The all-bindings inbox simply reloads for the new org.
    private readonly leaveOnOrgSwitch = effect(() => {
        const orgId = this.activeOrgService.activeOrgId();
        untracked(() => {
            // null is a logout: the auth flow navigates away itself.
            if (this.orgId !== undefined && orgId !== null && orgId !== this.orgId && this.bindingId()) {
                this.isLeavingForOrgSwitch = true;
                void this.router.navigate(ALL_DESKS_ROUTE).finally(() => (this.isLeavingForOrgSwitch = false));
            }
            this.orgId = orgId;
        });
    });
    // Another desk's conversation must not stay open when the route moves to a different scope.
    private readonly clearSelectionOnScope = effect(() => {
        const scope = this.bindingId() ?? null;
        untracked(() => {
            if (this.scope !== undefined && scope !== this.scope) this.held.set(null);
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

    protected readonly isActionPending = inject(ChatConversationActionsService).isPending;
    protected readonly actionLabel = actionLabel;
    protected readonly visitorName = visitorName;

    private readonly chatApi = inject(ChatApiService);
    private readonly chatInboxStream = inject(ChatInboxStreamService);
    private readonly profileService = inject(ProfileService);
    private readonly permissionsService = inject(PermissionsService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly router = inject(Router);
    private readonly activeOrgService = inject(ActiveOrgService);
    private readonly bindingActions = inject(ChatBindingActionsService);
    private readonly desksStorage = inject(ChatDesksStorageService);
    private readonly conversationActions = inject(ChatConversationActionsService);
    private readonly injector = inject(Injector);
    private threadId: string | null = null;
    private hasUserScrolled = false;
    // Bumped whenever another thread opens; an older page lands only in the thread it was requested for.
    private threadEpoch = 0;
    private olderRequest: Subscription | null = null;
    private scope: string | null | undefined = undefined;
    private orgId: number | null | undefined = undefined;
    private isLeavingForOrgSwitch = false;

    constructor() {
        // The newest state of the open conversation, streamed or returned by an action, keeps the thread current.
        merge(this.chatInboxStream.conversationUpdated$, this.conversationActions.changed$)
            .pipe(
                filter((row) => row.id === this.selectedId()),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((row) => this.held.set(row));
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
                        // The inbox event carries no run id; the next page of messages fills it in.
                        session_id: null,
                        author_user_id: event.author_user_id,
                        author_name: event.author_name,
                    })
                )
            );
    }

    selectConversation(conversation: ChatConversation): void {
        const id = conversation.id;
        this.isThreadMenuOpen.set(false);
        // Selecting again retries a failed visitor token.
        const hadFailed = !!this.visitorTokenErrors()[id];
        if (hadFailed) {
            this.visitorTokenErrors.update((errors) => {
                const rest = { ...errors };
                delete rest[id];
                return rest;
            });
        }
        this.held.set(conversation);
        if (hadFailed && conversation.is_test && this.canUse()) this.ensureVisitorToken(id);
    }

    // The created row seeds the header: its stream event may already have passed, before it was selected.
    onTestConversationStarted(conversation: ChatConversation): void {
        this.held.set(conversation);
        this.conversationList()?.reveal('test');
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
        this.conversationActions.takeOver(conversation);
    }

    release(conversation: ChatConversation): void {
        this.conversationActions.release(conversation);
    }

    openSettings(): void {
        const binding = this.routeBinding();
        if (!binding) return;
        this.bindingActions
            .openSettings(binding)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.desksStorage.reload());
    }

    /**
     * Still on the deleted desk's page, it leaves for All desks before the desks reload: a list without the desk would
     * otherwise read as "no longer exists". Moved on to another desk meanwhile, it only reloads.
     */
    deleteDesk(): void {
        const binding = this.routeBinding();
        if (!binding) return;
        this.bindingActions
            .delete(binding)
            .pipe(filter(Boolean), takeUntilDestroyed(this.destroyRef))
            .subscribe(() => {
                if (this.bindingId() !== binding.id) this.desksStorage.reload();
                else void this.router.navigate(ALL_DESKS_ROUTE).finally(() => this.desksStorage.reload());
            });
    }

    copySnippet(): void {
        const binding = this.routeBinding();
        if (binding) this.bindingActions.copySnippet(binding);
    }

    togglePause(): void {
        const binding = this.routeBinding();
        if (!binding) return;
        (binding.is_active ? this.bindingActions.pause(binding) : this.bindingActions.resume(binding))
            .pipe(filter(Boolean), takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.desksStorage.reload());
    }

    protected modeLabel(mode: ChatMode): string {
        return CHAT_MODE_LABELS[mode];
    }

    /** Who wrote an operator message: "You", their name, or "Operator #7" while the name is not known. */
    operatorLabel(message: ChatOperatorMessage): string {
        const authorId = message.author_user_id;
        if (authorId === null) return message.author_name || '—';
        if (authorId === this.profileService.currentUserSignal()?.id) return 'You';
        return operatorName(authorId, message.author_name);
    }

    sessionLink(message: ChatOperatorMessage): unknown[] | null {
        const graphId = this.selectedBinding()?.graph_id;
        return message.session_id && graphId ? ['/graph', graphId, 'session', message.session_id] : null;
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
}
