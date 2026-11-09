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
    output,
    signal,
    untracked,
    viewChild,
    viewChildren,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { SpinnerComponent } from '@shared/components';
import { ActionCode, ResourceCode } from '@shared/models';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ProfileService } from '../../../../services/auth/profile.service';
import { ChatConversation } from '../../models/chat.model';
import { ChatConversationActionsService } from '../../services/chat-conversation-actions.service';
import { ChatDesksStorageService } from '../../services/chat-desks-storage.service';
import { ChatInboxStreamService } from '../../services/chat-inbox-stream.service';
import { ConversationListPreferencesService } from '../../services/conversation-list-preferences.service';
import { isDeskBuilder } from '../../utils/chat-permissions.util';
import {
    ConversationListSection,
    ConversationListTab,
    tabOfConversation,
    tabOfSection,
} from '../../utils/conversation-list-tab.util';
import { ConversationDeskRules, deskRulesOf, visitorName } from '../../utils/conversation-row.util';
import { tickingNow } from '../../utils/ticking-now.util';
import { ConversationListTabsComponent } from '../conversation-list-tabs/conversation-list-tabs.component';
import { ConversationListToolbarComponent } from '../conversation-list-toolbar/conversation-list-toolbar.component';
import { ConversationRowComponent, ConversationRowMove } from '../conversation-row/conversation-row.component';
import { ConversationSectionHeaderComponent } from '../conversation-section-header/conversation-section-header.component';
import {
    CONVERSATION_SECTIONS,
    ConversationListQuery,
    ConversationListStore,
    listsSection,
    sectionHolds,
} from './conversation-list.store';
import { ConversationListMotion } from './conversation-list-motion';

// Relative times ("6m") move on without a reload.
const NOW_TICK_MS = 30_000;
// A wait counts the seconds ("12m 16s"): only Waiting's rows take this clock, so the others do not redraw every second.
const WAIT_TICK_MS = 1_000;
// A section's next page starts loading a little before its end scrolls into view.
const SENTINEL_MARGIN = '0px 0px 200px 0px';

let nextListId = 0;

/** See `ConversationListComponent.lookUp`. */
export type ConversationLookup = ChatConversation | 'loading' | 'missing';

/**
 * The conversations column: the Inbox / Bot Testing switch and a toolbar (search, Mine or New Test Chat) over
 * one scroll. Inbox has a section per inbox section (Waiting for a person, In progress, Closed, Bot); Bot Testing has
 * Bot and Closed, the open and the closed tests. Each sits under a sticky header that collapses it. Loads, pages as a
 * list's end scrolls into view, keeps the rows live, and moves the selection with ↑/↓ (one row is the Tab stop).
 */
@Component({
    selector: 'app-conversation-list',
    imports: [
        SpinnerComponent,
        ConversationListTabsComponent,
        ConversationListToolbarComponent,
        ConversationRowComponent,
        ConversationSectionHeaderComponent,
    ],
    providers: [ConversationListStore],
    templateUrl: './conversation-list.component.html',
    styleUrl: './conversation-list.component.scss',
})
export class ConversationListComponent {
    /** The desk listed; null lists every desk. */
    readonly bindingId = input<string | null>(null);
    readonly selectedId = input<string | null>(null);
    /** Why a test cannot start now (no desk open, one starting); null when New Test Chat may start one. */
    readonly testStartBlockedReason = input<string | null>(null);
    readonly selectedChange = output<ChatConversation>();
    /** New Test Chat was pressed: the page starts the test, as the column has no desk actions of its own. */
    readonly testStartRequested = output<void>();

    private readonly toolbar = viewChild.required(ConversationListToolbarComponent);
    private readonly scroller = viewChild.required<ElementRef<HTMLElement>>('scroller');
    private readonly sectionElements = viewChildren<ElementRef<HTMLElement>>('sectionElement');
    private readonly sectionHeaders = viewChildren(ConversationSectionHeaderComponent);
    private readonly sentinels = viewChildren<ElementRef<HTMLElement>>('sentinel');
    private readonly rows = viewChildren(ConversationRowComponent);
    private readonly rowItems = viewChildren<ElementRef<HTMLElement>>('rowItem');

    /** The list's own copy of the selected conversation: refetched on every reload. Null while it does not list it. */
    readonly selectedRow = computed(() => this.store.findRow(this.selectedId()));
    /** The desk whose conversations the column holds (null: every desk); the `bindingId` input until it has reloaded. */
    readonly listedBindingId = computed(() => this.store.query().bindingId);
    protected readonly now = tickingNow(NOW_TICK_MS);
    protected readonly waitNow = tickingNow(WAIT_TICK_MS);
    /** Take over, and Mine: both are about conversations the user holds. */
    protected readonly canUse = computed(() => this.permissionsService.can(ResourceCode.Chats, ActionCode.Use));
    /** Bot Testing: tests are for whoever builds desks (chats create or update), not for support staff. */
    protected readonly canBuildDesks = computed(() => isDeskBuilder(this.permissionsService));
    /**
     * The tab in this column: the remembered choice, which is Inbox for a user who cannot build desks. Showing a
     * conversation of the other tab (a test that started, a link) moves here only; the remembered choice stays.
     */
    protected readonly tab = linkedSignal(
        (): ConversationListTab => (this.canBuildDesks() ? this.preferences.tab() : 'inbox')
    );
    /** The search as applied: trimmed, once typing settles. Never remembered. */
    protected readonly search = signal('');
    /**
     * Mine in this column: the remembered choice, which does not apply to a user who has since lost chats use. Revealing
     * a section Mine hides sets it aside here only; the remembered choice stays.
     */
    protected readonly isMineOnly = linkedSignal(() => this.canUse() && this.preferences.isMineOnly());
    // Under Mine, whose conversations Inbox lists. A number, so a refreshed profile of the same user lists nothing anew.
    private readonly inboxHolderId = computed(() =>
        this.isMineOnly() ? (this.profileService.currentUserSignal()?.id ?? null) : null
    );
    /**
     * The Waiting count for what Inbox lists — this desk or every desk, and Mine — from the stream's waiting set, on
     * either tab. None while Inbox is searched: the set cannot tell what the search matches. A search on Bot Testing
     * says nothing about Inbox, so the number stays.
     */
    protected readonly waitingCount = computed(() => {
        const query = this.store.query();
        return query.search && query.tab === 'inbox'
            ? null
            : this.chatInboxStream.waitingCountFor(query.bindingId, this.inboxHolderId());
    });
    /** Every desk's name by id, on All desks only: each row says which desk it came in on. */
    protected readonly deskNames = computed((): ReadonlyMap<string, string> | null =>
        this.bindingId() ? null : new Map(this.desksStorage.desks().map((desk) => [desk.id, desk.name]))
    );
    /** Each desk's rules for its rows (how a close is worded, when a wait turns overdue), by desk id. */
    protected readonly deskRules = computed(
        (): ReadonlyMap<string, ConversationDeskRules> =>
            new Map(this.desksStorage.desks().map((desk) => [desk.id, deskRulesOf(desk)]))
    );
    /** The row Tab lands on: the selected one when it is shown, else the first. */
    protected readonly tabStopId = computed(() => {
        const rows = this.store.visibleRows();
        const selectedId = this.selectedId();
        return rows.some((row) => row.id === selectedId) ? selectedId : (rows[0]?.id ?? null);
    });
    /** Said once each time the open conversation's bot starts replying; nothing while it is not. */
    protected readonly replyingAnnouncement = computed(() => {
        const row = this.store.findRow(this.selectedId());
        return row?.state === 'processing' ? `Bot is replying to ${visitorName(row)}` : '';
    });

    /**
     * Every `ready` means the stream is live from now, so a load after it is complete. Another tab, desk, search or Mine
     * lists something else: every section starts over. Mine applies to Inbox only.
     */
    private readonly reloadOnReadyOrQuery = effect(() => {
        this.chatInboxStream.readyEpoch();
        const tab = this.tab();
        const query: ConversationListQuery = {
            tab,
            bindingId: this.bindingId(),
            search: this.search(),
            holderId: tab === 'inbox' ? this.inboxHolderId() : null,
        };
        untracked(() => this.store.load(query));
    });
    /**
     * A section's end entering the scroll view loads its next page. A sentinel is drawn only while its section has
     * another page and none is loading, so each landed page brings a new one; observing it reports at once whether it
     * is already in view, which keeps loading until the view is full.
     */
    private readonly loadNextPageOnSentinel = effect((onCleanup) => {
        const sentinels = this.sentinels();
        const root = this.scroller().nativeElement;
        if (!sentinels.length || typeof IntersectionObserver === 'undefined') return;
        const observer = new IntersectionObserver(
            (entries) =>
                entries
                    .filter((entry) => entry.isIntersecting)
                    .forEach((entry) => {
                        const section = sectionOf(entry.target);
                        if (section) this.store.loadMore(section);
                    }),
            { root, rootMargin: SENTINEL_MARGIN }
        );
        sentinels.forEach(({ nativeElement }) => observer.observe(nativeElement));
        onCleanup(() => observer.disconnect());
    });

    protected readonly store = inject(ConversationListStore);
    protected readonly isActionPending = inject(ChatConversationActionsService).isPending;
    protected readonly motion = new ConversationListMotion({
        prefersReducedMotion: () =>
            typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches,
        isShown: (conversationId) => this.store.visibleRows().some((row) => row.id === conversationId),
        restoreFocus: (conversationId) =>
            this.rows()
                .find((row) => row.conversation().id === conversationId)
                ?.focus({ preventScroll: true }),
        focusSectionHeader: (section) =>
            this.sectionHeaders()
                .find((header) => header.controlsId() === this.sectionBodyId(section))
                ?.focus(),
    });
    protected readonly bodyIdPrefix = `conversation-list-${nextListId++}`;

    private readonly permissionsService = inject(PermissionsService);
    private readonly profileService = inject(ProfileService);
    private readonly preferences = inject(ConversationListPreferencesService);
    private readonly desksStorage = inject(ChatDesksStorageService);
    private readonly chatInboxStream = inject(ChatInboxStreamService);
    private readonly conversationActions = inject(ChatConversationActionsService);
    private readonly injector = inject(Injector);

    constructor() {
        // Each change is noted before it renders; the first of a batch plays once the batch has rendered.
        this.store.changes$.pipe(takeUntilDestroyed()).subscribe((change) => {
            if (!this.motion.note(change, () => this.rowElements())) return;
            // The read phase runs after Angular's own leave and enter work for the render, in every version.
            afterNextRender({ read: () => this.motion.play(this.rowElements()) }, { injector: this.injector });
        });
        inject(DestroyRef).onDestroy(() => this.motion.destroy());
    }

    /**
     * Shows a section and scrolls it to the top, e.g. `test_open` when a test conversation starts: moves to its tab,
     * opens it, and drops the search or Mine when they would keep the new conversation out of the list. The tab and
     * Mine change for this column only: the remembered choices stay for the next visit. A tab the user cannot see
     * changes nothing, the search included.
     */
    reveal(section: ConversationListSection): void {
        const tab = tabOfSection(section);
        if (!this.showTab(tab)) return;
        if (this.store.isSearching()) this.toolbar().clearSearch();
        const query: ConversationListQuery = { ...this.store.query(), tab, holderId: this.inboxHolderId() };
        if (tab === 'inbox' && !listsSection(query, section)) this.isMineOnly.set(false);
        this.store.openForColumn(section);
        afterNextRender(() => this.sectionElement(section)?.scrollIntoView({ block: 'start' }), {
            injector: this.injector,
        });
    }

    /**
     * What the column can say about a conversation the page was asked to open: its row once listed; `loading` while
     * what it shows may still bring it; `missing` once that has loaded without it (or nothing is open to wait for).
     * Missing says nothing about why: Mine, a search, a folded section, the other tab or a page not fetched yet. Reads
     * signals only, so an effect that calls it follows the answer.
     */
    lookUp(id: string): ConversationLookup {
        const row = this.store.findRow(id);
        if (row) return row;
        const isWaiting = !this.store.isLoaded() && this.store.view().some(({ isExpanded }) => isExpanded);
        return isWaiting ? 'loading' : 'missing';
    }

    /**
     * Brings a conversation the page opened (a link, a reload, history) into the column when it is not shown: its tab,
     * its section opened, the search cleared, and Mine set aside only when Mine keeps it out. For this column only:
     * the remembered choices stay. A conversation already shown changes nothing, so opening a row found by a search
     * keeps the search, and so does one no section lists (a test without a message yet). A test for someone who cannot
     * build desks stays out.
     */
    revealConversation(conversation: ChatConversation): void {
        if (this.store.visibleRows().some((row) => row.id === conversation.id)) return;
        const section = CONVERSATION_SECTIONS.find(({ id }) => sectionHolds(id, conversation, null))?.id;
        if (!section) return;
        const tab = tabOfConversation(conversation);
        if (!this.showTab(tab)) return;
        if (this.store.isSearching()) this.toolbar().clearSearch();
        const holderId = this.inboxHolderId();
        const query: ConversationListQuery = { ...this.store.query(), tab, holderId };
        if (tab === 'inbox' && (!listsSection(query, section) || !sectionHolds(section, conversation, holderId))) {
            this.isMineOnly.set(false);
        }
        this.store.openForColumn(section);
    }

    /** Focuses a conversation's row, or the row Tab lands on when that one is no longer shown. */
    focusRow(id: string, options?: FocusOptions): void {
        const rows = this.rows();
        const row =
            rows.find((item) => item.conversation().id === id) ??
            rows.find((item) => item.conversation().id === this.tabStopId());
        row?.focus(options);
    }

    /**
     * Collapsing a section whose header is stuck (the user is deep inside it) would leave that header far above the
     * view, with the focus on it, and opening one folds the open one above it, which would pull the header out of view:
     * the column scrolls so the header stays where it was pressed. Opened from the bottom, where a pinned section's
     * header (Bot, Closed) waits while the section is below the view, the section comes up to the top instead: it would open out
     * of sight.
     */
    protected toggle(section: ConversationListSection): void {
        const scroller = this.scroller().nativeElement;
        const sectionTop = this.sectionTopInScroller(section);
        this.store.toggle(section);
        if (sectionTop === null) return;
        // The scroller's top padding is a header's height: past this, the header is pinned at the bottom, its own and
        // the pinned ones under it.
        const headerHeight = parseFloat(getComputedStyle(scroller).scrollPaddingTop) || 0;
        const pinnedBelow = CONVERSATION_SECTIONS.find(({ id }) => id === section)?.pinnedBelow;
        const pinnedFrom = scroller.clientHeight - ((pinnedBelow ?? 0) + 1) * headerHeight;
        if (pinnedBelow !== undefined && sectionTop - scroller.scrollTop > pinnedFrom) {
            afterNextRender(
                () => {
                    if (this.store.view().find((item) => item.section.id === section)?.isExpanded) {
                        this.sectionElement(section)?.scrollIntoView({ block: 'start' });
                    }
                },
                { injector: this.injector }
            );
            return;
        }
        const offsetInView = Math.max(0, sectionTop - scroller.scrollTop);
        afterNextRender(
            () => {
                const top = this.sectionTopInScroller(section);
                if (top !== null && top - scroller.scrollTop !== offsetInView) scroller.scrollTop = top - offsetInView;
            },
            { injector: this.injector }
        );
    }

    /** The user's own choice: remembered. */
    protected setTab(tab: ConversationListTab): void {
        this.preferences.setTab(tab);
        this.showTab(tab);
    }

    /** The user's own choice: remembered, and it ends a Mine set aside by a reveal. */
    protected setMineOnly(isMineOnly: boolean): void {
        this.preferences.setMineOnly(isMineOnly);
        this.isMineOnly.set(isMineOnly && this.canUse());
    }

    /** The id of a section's body, which its header controls. */
    protected sectionBodyId(section: string): string {
        return `${this.bodyIdPrefix}-${section}`;
    }

    protected takeOver(row: ChatConversation): void {
        this.conversationActions.takeOver(row);
    }

    /** ↑/↓/Home/End: focus and open the row it leads to, among the rows shown (collapsed sections have none). */
    protected move(from: ChatConversation, move: ConversationRowMove): void {
        const rows = this.store.visibleRows();
        const index = rows.findIndex((row) => row.id === from.id);
        const targetIndex =
            move === 'first' ? 0 : move === 'last' ? rows.length - 1 : index + (move === 'next' ? 1 : -1);
        const target = rows[targetIndex];
        if (!target || target.id === from.id) return;
        this.rows()
            .find((row) => row.conversation().id === target.id)
            ?.focus();
        this.selectedChange.emit(target);
    }

    // Bot Testing is not there for someone who cannot build desks. Says whether the column is on `tab` now.
    private showTab(tab: ConversationListTab): boolean {
        if (tab === 'testing' && !this.canBuildDesks()) return false;
        this.tab.set(tab);
        return true;
    }

    private rowElements(): HTMLElement[] {
        return this.rowItems().map(({ nativeElement }) => nativeElement);
    }

    private sectionElement(section: ConversationListSection): HTMLElement | null {
        return (
            this.sectionElements().find(({ nativeElement }) => sectionOf(nativeElement) === section)?.nativeElement ??
            null
        );
    }

    // Where the section starts in the scroller's content, in the units of `scrollTop`.
    private sectionTopInScroller(section: ConversationListSection): number | null {
        const element = this.sectionElement(section);
        if (!element) return null;
        const scroller = this.scroller().nativeElement;
        return element.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop;
    }
}

/** The section a section's start marker or a sentinel belongs to, from its `data-section`. */
function sectionOf(element: Element): ConversationListSection | null {
    const value = (element as HTMLElement).dataset['section'];
    return CONVERSATION_SECTIONS.find(({ id }) => id === value)?.id ?? null;
}
