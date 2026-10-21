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
import { Router } from '@angular/router';
import { AppSvgIconComponent } from '@shared/components';
import { CollapseOnOverflowDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import { extractHttpErrorMessage } from '@shared/utils';
import { filter } from 'rxjs';

import { PhoneLayoutService } from '../../../../core/services/phone-layout.service';
import { ActiveOrgService } from '../../../../services/auth/active-org.service';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import {
    ChatActionMenuComponent,
    ChatActionMenuItem,
} from '../../components/chat-action-menu/chat-action-menu.component';
import { ChatBindingStatusComponent } from '../../components/chat-binding-status/chat-binding-status.component';
import { ChatThreadComponent } from '../../components/chat-thread/chat-thread.component';
import { ConversationListComponent } from '../../components/conversation-list/conversation-list.component';
import { DeskAvatarComponent } from '../../components/desk-avatar/desk-avatar.component';
import { ChatConversation } from '../../models/chat.model';
import { ChatApiService } from '../../services/chat-api.service';
import { ChatBindingActionsService } from '../../services/chat-binding-actions.service';
import { ChatDesksStorageService } from '../../services/chat-desks-storage.service';
import { ChatMyAliasesStorageService } from '../../services/chat-my-aliases-storage.service';
import { ChatVisitorTokensStore } from '../../services/chat-visitor-tokens.store';
import { DeskDrawerService } from '../../services/desk-drawer.service';
import { OpenConversationService } from '../../services/open-conversation.service';
import { OpenConversationSyncService } from '../../services/open-conversation-sync.service';
import { isDeskBuilder } from '../../utils/chat-permissions.util';
import { ALL_DESKS_ICON } from '../../utils/desk-avatar.util';

const ALL_DESKS_ROUTE: readonly string[] = ['/chat-bindings', 'all'];

type DeskAction = 'my-name' | 'settings' | 'snippet' | 'pause' | 'delete';

/**
 * A desk's workspace (or All desks): the desk toolbar over the conversations and the open conversation's thread
 * (`ChatThreadComponent`). The open conversation is in the URL (`OpenConversationService`), so a reload or a link
 * reopens it, and its row follows the server (`OpenConversationSyncService`). On phones the conversations and the
 * thread are a navigation stack, as on iOS: the thread pushes in from the right over the list, and Back (the thread's
 * own, Safari's edge swipe, Android's back) pops it.
 */
@Component({
    selector: 'app-chat-page',
    imports: [
        MatTooltipModule,
        AppSvgIconComponent,
        ChatActionMenuComponent,
        ChatBindingStatusComponent,
        ChatThreadComponent,
        CollapseOnOverflowDirective,
        ConversationListComponent,
        DeskAvatarComponent,
    ],
    providers: [OpenConversationService, OpenConversationSyncService, ChatVisitorTokensStore],
    templateUrl: './chat-page.component.html',
    styleUrls: ['./chat-page.component.scss'],
})
export class ChatPageComponent {
    /** From the route: the binding this workspace is scoped to; absent on the all-bindings inbox. */
    readonly bindingId = input<string>();

    private readonly thread = viewChild(ChatThreadComponent);
    private readonly conversationList = viewChild(ConversationListComponent);
    private readonly deskSwitcher = viewChild<ElementRef<HTMLButtonElement>>('deskSwitcher');

    readonly isStartingTest = signal(false);
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
    // The thread follows the conversation shown, not an id that has no row yet.
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
    readonly pauseLabel = computed(() => (this.routeBinding()?.is_active ? 'Pause' : 'Resume'));
    readonly pauseIcon = computed(() => (this.routeBinding()?.is_active ? 'pause' : 'activate'));
    readonly canStartTest = computed(() => !!this.routeBinding() && !this.isStartingTest());
    readonly canUse = computed(() => this.permissionsService.can(ResourceCode.Chats, ActionCode.Use));
    readonly canBuildDesks = computed(() => isDeskBuilder(this.permissionsService));
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
    readonly canUpdate = computed(() => this.permissionsService.can(ResourceCode.Chats, ActionCode.Update));
    readonly canDelete = computed(() => this.permissionsService.can(ResourceCode.Chats, ActionCode.Delete));
    /** Phones put every desk action except Test in the list screen's ⋯ menu; the same permissions as the toolbar's. */
    readonly deskMenuItems = computed((): ChatActionMenuItem<DeskAction>[] => {
        if (!this.routeBinding()) return [];
        const canUpdate = this.canUpdate();
        const items: (ChatActionMenuItem<DeskAction> | false)[] = [
            this.canUse() && { id: 'my-name', label: this.myNameLabel() },
            canUpdate && { id: 'settings', label: 'Settings' },
            this.canBuildDesks() && { id: 'snippet', label: 'Get snippet' },
            canUpdate && { id: 'pause', label: this.pauseLabel() },
            this.canDelete() && { id: 'delete', label: 'Delete' },
        ];
        return items.filter((item) => item !== false);
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
                this.openConversationSync.cancelRefresh();
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
     * The sync takes that desk's rows only from now on.
     */
    private readonly clearSelectionOnScope = effect(() => {
        const scope = this.bindingId() ?? null;
        untracked(() => {
            this.openConversationSync.setScope(scope);
            if (this.scope !== undefined && scope !== this.scope) this.openConversation.forget();
            this.scope = scope;
        });
    });
    /**
     * An id the page did not open itself (a reload, a link, history) takes its row from the conversations column, once
     * the column holds the route's desk (until then its rows are another desk's). A column that hides rows (Mine, a
     * search, a collapsed section) shows everything first; what it then finds, or that it lacks the id, goes to the sync
     * (`OpenConversationSyncService.resolve`).
     */
    private readonly openConversationFromUrl = effect(() => {
        const id = this.openConversation.id();
        const list = this.conversationList();
        if (!id || !list || this.openConversation.row()) return;
        if (list.listedBindingId() !== (this.bindingId() ?? null)) return;
        const lookup = list.lookUp(id);
        untracked(() => {
            if (lookup === 'hidden') list.showEverything();
            else if (lookup !== 'loading') this.openConversationSync.resolve(id, lookup);
        });
    });
    // Phones: the focus goes with the screen the user moved to: the thread's Back, or the row the thread was opened from.
    private readonly moveFocusWithStack = effect(() => {
        const openId = this.isPhone() ? this.shownConversationId() : undefined;
        untracked(() => {
            const previousId = this.stackOpenId;
            this.stackOpenId = openId;
            if (openId === undefined || previousId === undefined) return;
            if (openId && !previousId) {
                afterNextRender(() => this.thread()?.focusBack(), { injector: this.injector });
            } else if (!openId && previousId) {
                // Without scrolling: a pane still sliding may be past the edge, and the browser would scroll to it.
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

    protected readonly allDesksIcon = ALL_DESKS_ICON;
    protected readonly deskDrawer = inject(DeskDrawerService);
    protected readonly openConversation = inject(OpenConversationService);
    protected readonly isPhone = inject(PhoneLayoutService).isPhone;

    private readonly chatApi = inject(ChatApiService);
    private readonly permissionsService = inject(PermissionsService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly router = inject(Router);
    private readonly activeOrgService = inject(ActiveOrgService);
    private readonly bindingActions = inject(ChatBindingActionsService);
    private readonly desksStorage = inject(ChatDesksStorageService);
    private readonly myAliasesStorage = inject(ChatMyAliasesStorageService);
    private readonly visitorTokens = inject(ChatVisitorTokensStore);
    private readonly openConversationSync = inject(OpenConversationSyncService);
    private readonly injector = inject(Injector);
    private scope: string | null | undefined = undefined;
    // Phones: the conversation the stack showed last (null: the list); undefined off phones and before the first look.
    private stackOpenId: string | null | undefined = undefined;
    private orgId: number | null | undefined = undefined;
    private isLeavingForOrgSwitch = false;

    selectConversation(conversation: ChatConversation): void {
        // Selecting again retries a failed visitor token.
        const hadFailed = this.visitorTokens.clearError(conversation.id);
        this.openConversation.open(conversation);
        if (hadFailed && conversation.is_test && this.canBuildDesks()) this.visitorTokens.ensure(conversation.id);
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
                    this.visitorTokens.remember(conversation.id, visitor_token);
                    this.onTestConversationStarted(conversation);
                    afterNextRender(() => this.thread()?.focusComposer(), { injector: this.injector });
                },
                error: (error: HttpErrorResponse) => {
                    this.isStartingTest.set(false);
                    this.toastService.error(extractHttpErrorMessage(error));
                },
            });
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
}
