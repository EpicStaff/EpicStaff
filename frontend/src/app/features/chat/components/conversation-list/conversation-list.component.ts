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
    NgZone,
    output,
    signal,
    untracked,
    viewChild,
    viewChildren,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { SpinnerComponent } from '@shared/components';
import { ActionCode, ResourceCode } from '@shared/models';
import { interval } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ProfileService } from '../../../../services/auth/profile.service';
import { ChatConversation, ChatInboxOrder, ChatInboxSection } from '../../models/chat.model';
import { ChatConversationActionsService } from '../../services/chat-conversation-actions.service';
import { ChatDesksStorageService } from '../../services/chat-desks-storage.service';
import { ChatInboxStreamService } from '../../services/chat-inbox-stream.service';
import { ConversationListPreferencesService } from '../../services/conversation-list-preferences.service';
import { visitorName } from '../../utils/conversation-row.util';
import { ConversationListToolbarComponent } from '../conversation-list-toolbar/conversation-list-toolbar.component';
import { ConversationRowComponent, ConversationRowMove } from '../conversation-row/conversation-row.component';
import { ConversationSectionHeaderComponent } from '../conversation-section-header/conversation-section-header.component';
import {
    CONVERSATION_SECTIONS,
    ConversationListQuery,
    ConversationListStore,
    listsSection,
} from './conversation-list.store';
import { ConversationListMotion } from './conversation-list-motion';

// Relative times ("6m") move on without a reload.
const NOW_TICK_MS = 30_000;
// A section's next page starts loading a little before its end scrolls into view.
const SENTINEL_MARGIN = '0px 0px 200px 0px';

let nextListId = 0;

/**
 * The conversations column: a toolbar (search, Mine, sort) over one scroll with a section per inbox section (Waiting
 * for a person, In progress, Tests, Bot), each under a sticky header that collapses it. Loads, pages as each section's
 * end scrolls into view, keeps the rows live, and moves the selection with ↑/↓ (one row is the Tab stop).
 */
@Component({
    selector: 'app-conversation-list',
    imports: [
        SpinnerComponent,
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
    readonly selectedChange = output<ChatConversation>();

    private readonly toolbar = viewChild.required(ConversationListToolbarComponent);
    private readonly scroller = viewChild.required<ElementRef<HTMLElement>>('scroller');
    private readonly sectionElements = viewChildren<ElementRef<HTMLElement>>('sectionElement');
    private readonly sectionHeaders = viewChildren(ConversationSectionHeaderComponent);
    private readonly sentinels = viewChildren<ElementRef<HTMLElement>>('sentinel');
    private readonly rows = viewChildren(ConversationRowComponent);
    private readonly rowItems = viewChildren<ElementRef<HTMLElement>>('rowItem');

    /** The list's own copy of the selected conversation: refetched on every reload. Null while it does not list it. */
    readonly selectedRow = computed(() => this.store.findRow(this.selectedId()));
    protected readonly now = signal(Date.now());
    /** Take over, and Mine: both are about conversations the user holds. */
    protected readonly canUse = computed(() => this.permissionsService.can(ResourceCode.Chats, ActionCode.Use));
    /** The search as applied: trimmed, once typing settles. Never remembered. */
    protected readonly search = signal('');
    protected readonly order = computed(() => this.preferences.order());
    /**
     * Mine in this column: the remembered choice, which does not apply to a user who has since lost chats use. Revealing
     * a section Mine hides sets it aside here only; the remembered choice stays.
     */
    protected readonly isMineOnly = linkedSignal(() => this.canUse() && this.preferences.isMineOnly());
    // Under Mine, whose conversations are listed. A number, so a refreshed profile of the same user lists nothing anew.
    private readonly holderId = computed(() =>
        this.isMineOnly() ? (this.profileService.currentUserSignal()?.id ?? null) : null
    );
    /**
     * The Waiting count for what is listed — this desk or every desk, and Mine — from the stream's waiting set. None
     * while searching: the set cannot tell what the search matches.
     */
    protected readonly waitingCount = computed(() => {
        const query = this.store.query();
        return query.search ? null : this.chatInboxStream.waitingCountFor(query.bindingId, query.holderId);
    });
    /** Every desk's name by id, on All desks only: each row says which desk it came in on. */
    protected readonly deskNames = computed((): ReadonlyMap<string, string> | null =>
        this.bindingId() ? null : new Map(this.desksStorage.desks().map((desk) => [desk.id, desk.name]))
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
     * Every `ready` means the stream is live from now, so a load after it is complete. Another desk, search, sort or
     * Mine lists something else: every section starts over.
     */
    private readonly reloadOnReadyOrQuery = effect(() => {
        this.chatInboxStream.readyEpoch();
        const query: ConversationListQuery = {
            bindingId: this.bindingId(),
            search: this.search(),
            order: this.order(),
            holderId: this.holderId(),
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
        // Outside the zone: a pending interval would keep the app from ever being stable. The signal still re-renders.
        inject(NgZone).runOutsideAngular(() =>
            interval(NOW_TICK_MS)
                .pipe(takeUntilDestroyed())
                .subscribe(() => this.now.set(Date.now()))
        );
    }

    /**
     * Shows a section and scrolls it to the top, e.g. Tests when a test conversation starts: opens it, and drops the
     * search or Mine when they would keep the new conversation out of the list. Mine is dropped for this column only:
     * the remembered choice stays for the next visit.
     */
    reveal(section: ChatInboxSection): void {
        if (this.store.isSearching()) this.toolbar().clearSearch();
        if (!listsSection(this.store.query(), section)) this.isMineOnly.set(false);
        this.store.setCollapsed(section, false);
        afterNextRender(() => this.sectionElement(section)?.scrollIntoView({ block: 'start' }), {
            injector: this.injector,
        });
    }

    /**
     * Collapsing a section whose header is stuck (the user is deep inside it) would leave that header far above the
     * view, with the focus on it: the column scrolls back so the collapsed header stays where it was pressed.
     */
    protected toggle(section: ChatInboxSection): void {
        const isCollapsing = this.store.view().some((item) => item.section.id === section && item.isExpanded);
        const scroller = this.scroller().nativeElement;
        const sectionTop = this.sectionTopInScroller(section);
        this.store.toggle(section);
        if (!isCollapsing || sectionTop === null || sectionTop >= scroller.scrollTop) return;
        afterNextRender(() => (scroller.scrollTop = sectionTop), { injector: this.injector });
    }

    protected setOrder(order: ChatInboxOrder): void {
        this.preferences.setOrder(order);
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

    private rowElements(): HTMLElement[] {
        return this.rowItems().map(({ nativeElement }) => nativeElement);
    }

    private sectionElement(section: ChatInboxSection): HTMLElement | null {
        return (
            this.sectionElements().find(({ nativeElement }) => sectionOf(nativeElement) === section)?.nativeElement ??
            null
        );
    }

    // Where the section starts in the scroller's content, in the units of `scrollTop`.
    private sectionTopInScroller(section: ChatInboxSection): number | null {
        const element = this.sectionElement(section);
        if (!element) return null;
        const scroller = this.scroller().nativeElement;
        return element.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop;
    }
}

/** The section a section wrapper or a sentinel belongs to, from its `data-section`. */
function sectionOf(element: Element): ChatInboxSection | null {
    const value = (element as HTMLElement).dataset['section'];
    return CONVERSATION_SECTIONS.find(({ id }) => id === value)?.id ?? null;
}
