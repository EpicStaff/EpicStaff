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

import { PhoneLayoutService } from '../../../../core/services/phone-layout.service';
import { ActiveOrgService } from '../../../../services/auth/active-org.service';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ProfileService } from '../../../../services/auth/profile.service';
import { ToastService } from '../../../../services/notifications';
import {
    ChatActionMenuComponent,
    ChatActionMenuItem,
} from '../../components/chat-action-menu/chat-action-menu.component';
import { ChatBindingStatusComponent } from '../../components/chat-binding-status/chat-binding-status.component';
import {
    ChatOperatorReplySent,
    ChatThreadComposerComponent,
} from '../../components/chat-thread-composer/chat-thread-composer.component';
import { ChatUsageRingComponent } from '../../components/chat-usage-ring/chat-usage-ring.component';
import { ConversationListComponent } from '../../components/conversation-list/conversation-list.component';
import { DeskAvatarComponent } from '../../components/desk-avatar/desk-avatar.component';
import { CHAT_MODE_LABELS, ChatConversation, ChatMode, ChatOperatorMessage } from '../../models/chat.model';
import { CHAT_MESSAGES_PAGE_SIZE, ChatApiService } from '../../services/chat-api.service';
import { ChatBindingActionsService } from '../../services/chat-binding-actions.service';
import { ChatConversationActionsService } from '../../services/chat-conversation-actions.service';
import { ChatDesksStorageService } from '../../services/chat-desks-storage.service';
import { ChatInboxStreamService } from '../../services/chat-inbox-stream.service';
import { ChatMyAliasesStorageService } from '../../services/chat-my-aliases-storage.service';
import { DeskDrawerService } from '../../services/desk-drawer.service';
import { OpenConversationService } from '../../services/open-conversation.service';
import { actionLabel } from '../../utils/action-label.util';
import { operatorName, visitorName } from '../../utils/conversation-row.util';
import { ALL_DESKS_ICON } from '../../utils/desk-avatar.util';
import { upsertMessage } from '../../utils/inbox-merge.util';

const ALL_DESKS_ROUTE: readonly string[] = ['/chat-bindings', 'all'];

type DeskAction = 'my-name' | 'settings' | 'snippet' | 'pause' | 'delete';
type ConversationAction = 'take-over' | 'release';

/**
 * A desk's workspace (or All desks): the desk toolbar over the conversations and the open conversation's thread. The
 * open conversation is in the URL (`OpenConversationService`), so a reload or a link reopens it. On phones the
 * conversations and the thread are a navigation stack, as on iOS: the thread pushes in from the right over the list,
 * and Back (the thread's own, Safari's edge swipe, Android's back) pops it.
 */
@Component({
    selector: 'app-chat-page',
    imports: [
        DatePipe,
        MatTooltipModule,
        RouterLink,
        ChatUsageRingComponent,
        AppSvgIconComponent,
        ButtonComponent,
        ChatActionMenuComponent,
        ChatBindingStatusComponent,
        ChatThreadComposerComponent,
        CollapseOnOverflowDirective,
        ConversationListComponent,
        DeskAvatarComponent,
        SpinnerComponent,
    ],
    providers: [OpenConversationService],
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
    private readonly deskSwitcher = viewChild<ElementRef<HTMLButtonElement>>('deskSwitcher');
    private readonly threadBack = viewChild<ElementRef<HTMLButtonElement>>('threadBack');

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

    /** The open conversation's id; the list marks its row even before the row itself is known. */
    readonly selectedId = computed(() => this.openConversation.id());
    /**
     * The open conversation: the list's row when it lists it, so a reconnect reload (another operator took it over
     * meanwhile) reaches the header and the composer; else the row as last known. Matched by id, as the list's
     * `selectedId` input catches up one change detection later. Null while the open id has no row yet (a link, a reload).
     */
    readonly selected = computed(() => {
        const row = this.openConversation.row();
        const listed = this.conversationList()?.selectedRow();
        return row && listed?.id === row.id ? listed : row;
    });
    // The thread's messages follow the conversation shown, not an id that has no row yet.
    private readonly shownConversationId = computed(() => this.selected()?.id ?? null);
    readonly isAllBindings = computed(() => !this.bindingId());
    // Null until the desks load; an id they do not list sends the user back to All desks.
    readonly routeBinding = computed(
        () => this.desksStorage.desks().find((binding) => binding.id === this.bindingId()) ?? null
    );
    readonly title = computed(() => (this.isAllBindings() ? 'All desks' : (this.routeBinding()?.name ?? '')));
    readonly deskSwitcherLabel = computed(() => {
        const title = this.title();
        return title ? `Switch desk, current: ${title}` : 'Switch desk';
    });
    /** The thread's Back on phones, named after the list it returns to. */
    readonly backText = computed(() => this.title() || 'Back');
    readonly backLabel = computed(() => {
        const title = this.title();
        return title ? `Back to ${title}` : 'Back';
    });
    readonly pauseLabel = computed(() => (this.routeBinding()?.is_active ? 'Pause' : 'Resume'));
    readonly pauseIcon = computed(() => (this.routeBinding()?.is_active ? 'pause' : 'activate'));
    readonly canStartTest = computed(() => !!this.routeBinding() && !this.isStartingTest());
    readonly selectedBinding = computed(
        () => this.desksStorage.desks().find((binding) => binding.id === this.selected()?.binding_id) ?? null
    );
    readonly canUse = computed(() => this.permissionsService.can(ResourceCode.Chats, ActionCode.Use));
    /**
     * The name visitors see on the user's replies on the open desk: their alias there, else its operator name. Null
     * while not known: the My name action then names no one rather than a name that may be wrong.
     */
    readonly myNameOnDesk = computed(() => {
        const binding = this.routeBinding();
        return binding ? this.myAliasesStorage.visibleNameOn(binding) : null;
    });
    readonly myNameLabel = computed(() => {
        const name = this.myNameOnDesk();
        return name ? `My name: ${name}` : 'My name';
    });
    readonly myNameTooltip = computed(() => {
        const name = this.myNameOnDesk();
        return name ? `Visitors see you as ${name}` : '';
    });
    /** The same on the open conversation's desk, for the composer; null until that desk is known. */
    readonly myNameOnConversationDesk = computed(() => {
        const binding = this.selectedBinding();
        return binding ? this.myAliasesStorage.visibleNameOn(binding) : null;
    });
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
    /** Phones put every desk action except Test in the list screen's ⋯ menu; the same permissions as the toolbar's. */
    readonly deskMenuItems = computed((): ChatActionMenuItem<DeskAction>[] => {
        if (!this.routeBinding()) return [];
        const canUpdate = this.canUpdate();
        const items: (ChatActionMenuItem<DeskAction> | false)[] = [
            this.canUse() && { id: 'my-name', label: this.myNameLabel() },
            canUpdate && { id: 'settings', label: 'Settings' },
            { id: 'snippet', label: 'Get snippet' },
            canUpdate && { id: 'pause', label: this.pauseLabel() },
            this.canDelete() && { id: 'delete', label: 'Delete' },
        ];
        return items.filter((item) => item !== false);
    });
    /**
     * The open conversation's actions in its ⋯ menu: Take over and Release to bot while another operator holds it.
     * The holder releases with a button beside the title, which phones have no room for: Release is in the menu there.
     */
    readonly conversationMenuItems = computed((): ChatActionMenuItem<ConversationAction>[] => {
        const conversation = this.selected();
        if (!conversation || !this.canUse()) return [];
        const disabled = this.isActionPending();
        if (this.isClaimedByMe()) return this.isPhone() ? [{ id: 'release', label: 'Release', disabled }] : [];
        if (conversation.mode !== 'human') return [];
        return [
            { id: 'take-over', label: 'Take over', disabled },
            { id: 'release', label: 'Release to bot', disabled },
        ];
    });

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
    /**
     * The open conversation belongs to the previous org after a switch (or a logout), and this page forgets it. On All
     * desks it closes at once, so neither its thread nor its composer stays usable, and its id leaves the URL in place;
     * that lands before the org switch reads the URL to return to, so the new org's page does not try to open it. A
     * binding's page goes back to All desks without a message (the binding was not deleted), which replaces the page;
     * a logout leaves the page to the login flow.
     */
    private readonly leaveOnOrgSwitch = effect(() => {
        const orgId = this.activeOrgService.activeOrgId();
        untracked(() => {
            if (this.orgId !== undefined && orgId !== this.orgId) {
                // null is a logout: the auth flow navigates away itself.
                if (orgId === null) {
                    this.openConversation.forget();
                } else if (this.bindingId()) {
                    this.openConversation.forget();
                    this.isLeavingForOrgSwitch = true;
                    void this.router.navigate(ALL_DESKS_ROUTE).finally(() => (this.isLeavingForOrgSwitch = false));
                } else {
                    this.openConversation.drop();
                }
            }
            this.orgId = orgId;
        });
    });
    /**
     * Another desk's conversation must not stay open when the route moves to a different scope. A link to another desk
     * leaves the id out of its URL by itself; a move through history brings that desk's own id along, which stays.
     */
    private readonly clearSelectionOnScope = effect(() => {
        const scope = this.bindingId() ?? null;
        untracked(() => {
            if (this.scope !== undefined && scope !== this.scope) this.openConversation.forget();
            this.scope = scope;
        });
    });
    /**
     * An id the page did not open itself (a reload, a link, history) takes its row from the conversations column, once
     * the column holds the route's desk (until then its rows are another desk's). A column that hides rows (Mine, a
     * search, a collapsed section) shows everything first; the chat service cannot fetch one conversation by id, so an
     * id that everything the column can list does not have leaves the URL, with a message.
     */
    private readonly openConversationFromUrl = effect(() => {
        const id = this.openConversation.id();
        const list = this.conversationList();
        if (!id || !list || this.openConversation.row()) return;
        if (list.listedBindingId() !== (this.bindingId() ?? null)) return;
        const lookup = list.lookUp(id);
        untracked(() => {
            if (typeof lookup !== 'string') {
                if (this.isOfThisPage(lookup)) this.openConversation.remember(lookup);
                else this.dropMissing();
            } else if (lookup === 'hidden') {
                list.showEverything();
            } else if (lookup === 'missing') {
                this.dropMissing();
            }
        });
    });
    // Phones: the focus goes with the screen the user moved to: the thread's Back, or the row the thread was opened from.
    private readonly moveFocusWithStack = effect(() => {
        const openId = this.isPhone() ? this.shownConversationId() : undefined;
        untracked(() => {
            const previousId = this.stackOpenId;
            this.stackOpenId = openId;
            if (openId === undefined || previousId === undefined) return;
            // Without scrolling: a pane still sliding in may be past the edge, and the browser would scroll to it.
            if (openId && !previousId) {
                afterNextRender(() => this.threadBack()?.nativeElement.focus({ preventScroll: true }), {
                    injector: this.injector,
                });
            } else if (!openId && previousId) {
                afterNextRender(() => this.conversationList()?.focusRow(previousId, { preventScroll: true }), {
                    injector: this.injector,
                });
            }
        });
    });
    // The desk drawer returns the focus to the switcher shown now, whichever page shows it.
    private readonly registerDeskSwitcher = effect((onCleanup) => {
        const switcher = this.deskSwitcher()?.nativeElement;
        if (!switcher) return;
        this.deskDrawer.registerSwitcher(switcher);
        onCleanup(() => this.deskDrawer.unregisterSwitcher(switcher));
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
        const id = this.shownConversationId();
        this.chatInboxStream.readyEpoch();
        untracked(() => this.loadThread(id));
    });

    protected readonly isActionPending = inject(ChatConversationActionsService).isPending;
    protected readonly actionLabel = actionLabel;
    protected readonly visitorName = visitorName;
    protected readonly allDesksIcon = ALL_DESKS_ICON;
    protected readonly deskDrawer = inject(DeskDrawerService);
    protected readonly openConversation = inject(OpenConversationService);
    protected readonly isPhone = inject(PhoneLayoutService).isPhone;

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
    private readonly myAliasesStorage = inject(ChatMyAliasesStorageService);
    private readonly conversationActions = inject(ChatConversationActionsService);
    private readonly injector = inject(Injector);
    private threadId: string | null = null;
    private hasUserScrolled = false;
    // Bumped whenever another thread opens; an older page lands only in the thread it was requested for.
    private threadEpoch = 0;
    private olderRequest: Subscription | null = null;
    private scope: string | null | undefined = undefined;
    // Phones: the conversation the stack showed last (null: the list); undefined off phones and before the first look.
    private stackOpenId: string | null | undefined = undefined;
    private orgId: number | null | undefined = undefined;
    private isLeavingForOrgSwitch = false;

    constructor() {
        // The newest state of the open conversation, streamed or returned by an action, keeps the thread current.
        merge(this.chatInboxStream.conversationUpdated$, this.conversationActions.changed$)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((row) => {
                if (this.isOfThisPage(row)) this.openConversation.remember(row);
            });
        this.chatInboxStream.messageCreated$
            .pipe(
                filter((event) => event.conversation_id === this.shownConversationId()),
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

    selectConversation(conversation: ChatConversation): void {
        const id = conversation.id;
        // Selecting again retries a failed visitor token.
        const hadFailed = !!this.visitorTokenErrors()[id];
        if (hadFailed) {
            this.visitorTokenErrors.update((errors) => {
                const rest = { ...errors };
                delete rest[id];
                return rest;
            });
        }
        this.openConversation.open(conversation);
        if (hadFailed && conversation.is_test && this.canUse()) this.ensureVisitorToken(id);
    }

    // The created row seeds the header: its stream event may already have passed, before it was selected.
    onTestConversationStarted(conversation: ChatConversation): void {
        this.openConversation.open(conversation);
        this.conversationList()?.reveal('test');
    }

    /** The slide has ended: later moves are instant unless one made here asks again. */
    onStackTransitionEnd(event: TransitionEvent): void {
        if (event.target === event.currentTarget && event.propertyName === 'transform')
            this.openConversation.stackSlid();
    }

    runDeskAction(action: DeskAction): void {
        const run: Record<DeskAction, () => void> = {
            'my-name': () => this.editMyAlias(),
            settings: () => this.openSettings(),
            snippet: () => this.copySnippet(),
            pause: () => this.togglePause(),
            delete: () => this.deleteDesk(),
        };
        run[action]();
    }

    runConversationAction(action: ConversationAction): void {
        const conversation = this.selected();
        if (!conversation) return;
        if (action === 'take-over') this.claim(conversation);
        else this.release(conversation);
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

    /** The name the user goes by on the open desk; the dialog stores a change itself. */
    editMyAlias(): void {
        const binding = this.routeBinding();
        if (binding) this.bindingActions.editMyAlias(binding);
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

    /**
     * Who wrote an operator message: "You", their name, or "Operator #7" while the name is not known; then the name
     * visitors saw on it when that was another one: "Bea Agent · as Mike". Operators only see this line.
     */
    operatorLabel(message: ChatOperatorMessage): string {
        const author = this.operatorAuthor(message);
        const visibleName = message.visible_name;
        return visibleName && visibleName !== message.author_name ? `${author} · as ${visibleName}` : author;
    }

    private operatorAuthor(message: ChatOperatorMessage): string {
        const authorId = message.author_user_id;
        if (authorId === null) return message.author_name || '—';
        if (authorId === this.profileService.currentUserSignal()?.id) return 'You';
        return operatorName(authorId, message.author_name);
    }

    sessionLink(message: ChatOperatorMessage): unknown[] | null {
        const graphId = this.selectedBinding()?.graph_id;
        return message.session_id && graphId ? ['/graph', graphId, 'session', message.session_id] : null;
    }

    /**
     * A desk's page shows that desk's conversations only. The stream and the actions report every desk's rows, so an
     * id in the URL of another desk's conversation (a hand-made link) must not open it here from a live update.
     */
    private isOfThisPage(row: ChatConversation): boolean {
        const bindingId = this.bindingId();
        return !bindingId || row.binding_id === bindingId;
    }

    private dropMissing(): void {
        this.toastService.error("Couldn't open that conversation.");
        this.openConversation.drop();
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
                    if (this.shownConversationId() !== id) return;
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
