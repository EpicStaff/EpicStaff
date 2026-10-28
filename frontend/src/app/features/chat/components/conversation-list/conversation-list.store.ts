import { HttpErrorResponse } from '@angular/common/http';
import { computed, DestroyRef, inject, Injectable, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { extractHttpErrorMessage } from '@shared/utils';
import { merge, Observable, Subject, Subscription } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { ChatConversation, ChatInboxOrder, ChatInboxSection } from '../../models/chat.model';
import { ChatApiService } from '../../services/chat-api.service';
import { ChatConversationActionsService } from '../../services/chat-conversation-actions.service';
import { ChatInboxStreamService } from '../../services/chat-inbox-stream.service';
import { ConversationListPreferencesService } from '../../services/conversation-list-preferences.service';
import { belongsTo, inboxOrder, placeRow } from '../../utils/inbox-merge.util';

/**
 * Why the rows changed: `live` for a stream event or an action result, `load` for anything that loads or re-arranges
 * them (first pages, paging, reloads, another desk, search, sort, Mine, collapsing). Only live changes animate.
 */
export type ConversationListChange = 'live' | 'load';

/** What the column lists; any change starts every section over. */
export interface ConversationListQuery {
    // One desk, or every desk for null.
    bindingId: string | null;
    // Trimmed; empty lists without searching.
    search: string;
    order: ChatInboxOrder;
    // Mine: the user whose conversations are listed; null lists everyone's.
    holderId: number | null;
    // Tests are for whoever builds desks (chats create or update), not for support staff.
    showsTests: boolean;
}

const EVERYTHING: ConversationListQuery = {
    bindingId: null,
    search: '',
    order: 'newest',
    holderId: null,
    showsTests: false,
};

export interface ConversationSectionState {
    rows: ChatConversation[];
    nextCursor: string | null;
    // Last row fetched while more pages remain; live rows sorting after it wait for the next page.
    boundary: ChatConversation | null;
    isLoading: boolean;
    // The query (by generation) whose first page landed here; until it is the current one the section has not loaded.
    loadedFor: number | null;
}

export interface ConversationSectionView {
    id: ChatInboxSection;
    label: string;
    icon: string;
    emptyTitle: string;
    emptyDescription: string;
    // Said instead under Mine; only the sections Mine lists have one.
    mineEmptyTitle?: string;
    // Above the rows of a section that ignores the sort order.
    orderNote?: string;
}

/**
 * Top to bottom: the queue first (the one open by default), then what operators are on, Tests and Closed (there to
 * look into, not to work through), and Bot last — always live and endless, so anything below it would be out of reach.
 */
export const CONVERSATION_SECTIONS: readonly ConversationSectionView[] = [
    {
        id: 'waiting',
        label: 'Waiting for a person',
        icon: 'hourglass',
        emptyTitle: 'Nobody is waiting',
        emptyDescription: 'Visitors the bot hands over, or who write after an operator took over, line up here.',
        mineEmptyTitle: 'Nobody is waiting for you',
        orderNote: 'Longest wait first',
    },
    {
        id: 'in_progress',
        label: 'In progress',
        icon: 'user',
        emptyTitle: 'Nothing in progress',
        emptyDescription: 'Conversations an operator took over and answered last show up here.',
        mineEmptyTitle: 'None of yours in progress',
    },
    {
        id: 'test',
        label: 'Tests',
        icon: 'player-play-filled',
        emptyTitle: 'No test conversations',
        emptyDescription: 'Start one with Test on a desk.',
    },
    {
        id: 'closed',
        label: 'Closed',
        icon: 'circle-check',
        emptyTitle: 'Nothing closed yet',
        emptyDescription: 'Conversations an operator resolved, the visitor ended or that went quiet end up here.',
        orderNote: 'Most recently closed first',
    },
    {
        id: 'bot',
        label: 'Bot',
        icon: 'robot',
        emptyTitle: 'No conversations yet',
        emptyDescription: 'Conversations from your website the bot is answering show up here.',
    },
];

// Mine lists what the user holds: the bot holds nothing, tests are not work to pick up, and closed conversations are
// done.
const MINE_SECTIONS: ReadonlySet<ChatInboxSection> = new Set(['waiting', 'in_progress']);

/** Whether a query lists a section at all: Mine hides Bot, Tests and Closed; Tests also need `showsTests`. */
export const listsSection = (query: ConversationListQuery, section: ChatInboxSection): boolean =>
    (query.holderId === null || MINE_SECTIONS.has(section)) && (section !== 'test' || query.showsTests);

const emptySection = (): ConversationSectionState => ({
    rows: [],
    nextCursor: null,
    boundary: null,
    isLoading: false,
    loadedFor: null,
});

/**
 * The conversations column's state, one per column: the query, a section per inbox section, its pages, and live rows
 * from the stream and from this user's actions merged in. A collapsed section, or one the query does not list, never
 * loads. Provided on `ConversationListComponent`.
 */
@Injectable()
export class ConversationListStore {
    readonly sections = signal<Record<ChatInboxSection, ConversationSectionState>>({
        waiting: emptySection(),
        in_progress: emptySection(),
        test: emptySection(),
        closed: emptySection(),
        bot: emptySection(),
    });
    private readonly querySignal = signal(EVERYTHING);
    readonly query = this.querySignal.asReadonly();
    readonly isSearching = computed(() => !!this.query().search);
    readonly isMineOnly = computed(() => this.query().holderId !== null);
    /** The server refused the search (`invalid_search`): said next to the field, instead of a list or a toast. */
    readonly searchError = signal<string | null>(null);
    // Bumped by every load: a section has loaded once its first page for the current generation has landed.
    private readonly generation = signal(0);
    /**
     * Sections opened for this column only, beside the remembered one: to look for a conversation the page was asked
     * to open, or for a test that started. Folding one ends its opening; opening a folded one ends them all.
     */
    private readonly openedForColumn = signal<ReadonlySet<ChatInboxSection>>(new Set());
    /**
     * The sections open while a search runs, for this column only: every one as it starts, then as the user folds and
     * opens them. Clearing the search returns to the remembered one. Nothing of it is remembered.
     */
    private readonly openedForSearch = signal<ReadonlySet<ChatInboxSection>>(new Set());
    // Open as shown: the search's own while searching, else the remembered section and those opened for this column.
    private readonly expanded = computed((): ReadonlySet<ChatInboxSection> => {
        if (this.isSearching()) return this.openedForSearch();
        const remembered = this.preferences.expanded();
        return new Set([...(remembered ? [remembered] : []), ...this.openedForColumn()]);
    });
    /** Each section the query lists, in column order, with its state and whether it is open. */
    readonly view = computed(() => {
        const sections = this.sections();
        const expanded = this.expanded();
        const query = this.query();
        return CONVERSATION_SECTIONS.filter((section) => listsSection(query, section.id)).map((section) => ({
            section,
            state: sections[section.id],
            isExpanded: expanded.has(section.id),
        }));
    });
    /** The rows as shown, top to bottom: those of the open sections, in order. What ↑/↓ moves through. */
    readonly visibleRows = computed(() =>
        this.view()
            .filter(({ isExpanded }) => isExpanded)
            .flatMap(({ state }) => state.rows)
    );
    private readonly changesSubject = new Subject<ConversationListChange>();
    /** Every change to the rows, as it is made and before it renders. */
    readonly changes$: Observable<ConversationListChange> = this.changesSubject.asObservable();
    /**
     * Some section is open and every open one has its first page for the current query: what the column shows is
     * known. A section that failed to load keeps it false, so nothing concludes a conversation is not listed from a
     * list that did not load; so does a column with every section collapsed, which shows nothing to conclude from.
     */
    readonly isLoaded = computed(() => {
        const generation = this.generation();
        const open = this.view().filter(({ isExpanded }) => isExpanded);
        return open.length > 0 && open.every(({ state }) => state.loadedFor === generation);
    });
    /** Rows the column could list are kept out of it: by Mine, a search or a collapsed section. */
    readonly hidesSome = computed(() => {
        const query = this.query();
        return query.holderId !== null || !!query.search || this.view().some(({ isExpanded }) => !isExpanded);
    });
    /** Every open section has loaded and has nothing: the column says so once, not once per section. */
    private readonly chatApi = inject(ChatApiService);
    private readonly toastService = inject(ToastService);
    private readonly preferences = inject(ConversationListPreferencesService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly pageRequests: Partial<Record<ChatInboxSection, Subscription>> = {};
    // Rows streamed since the last load: newer than any page fetched meanwhile, so they win over the first pages and
    // over later pages, in whichever section they now belong to.
    private rowsSinceReload = new Map<string, ChatConversation>();

    constructor() {
        merge(inject(ChatInboxStreamService).conversationUpdated$, inject(ChatConversationActionsService).changed$)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((row) => this.applyRow(row));
    }

    /**
     * Lists `query` from the start: every section starts over. Open sections keep their rows on screen until their
     * first pages land; a collapsed section, or one the query does not list, is emptied and loads only once shown. A
     * search starting opens every section; clearing it folds them back.
     */
    load(query: ConversationListQuery): void {
        const wasSearching = !!this.query().search;
        if (!query.search) this.openedForSearch.set(new Set());
        else if (!wasSearching) this.openedForSearch.set(new Set(CONVERSATION_SECTIONS.map(({ id }) => id)));
        this.querySignal.set(query);
        this.generation.update((generation) => generation + 1);
        this.rowsSinceReload = new Map();
        this.searchError.set(null);
        this.changesSubject.next('load');
        for (const { id: section } of CONVERSATION_SECTIONS) {
            if (this.isOpen(section)) {
                this.loadPage(section, null);
            } else {
                this.pageRequests[section]?.unsubscribe();
                this.patchSection(section, emptySection());
            }
        }
    }

    /** The next page of an open section, once its first has landed; one request at a time per section. */
    loadMore(section: ChatInboxSection): void {
        const state = this.sections()[section];
        if (state.isLoading || !state.nextCursor || !this.isOpen(section)) return;
        this.loadPage(section, state.nextCursor);
    }

    toggle(section: ChatInboxSection): void {
        if (this.isSearching()) {
            this.openedForSearch.update((sections) =>
                sections.has(section) ? withoutSection(sections, section) : new Set([...sections, section])
            );
        } else if (this.expanded().has(section)) {
            this.openedForColumn.update((sections) => withoutSection(sections, section));
            if (this.preferences.expanded() === section) this.preferences.setExpanded(null);
        } else {
            this.openedForColumn.set(new Set());
            this.preferences.setExpanded(section);
        }
        this.showChange(section);
    }

    /** Opens a collapsed section in this column only; the remembered choice stays as it is. */
    openForColumn(section: ChatInboxSection): void {
        if (this.preferences.expanded() === section || this.openedForColumn().has(section)) return;
        this.openedForColumn.update((sections) => new Set([...sections, section]));
        this.showChange(section);
    }

    findRow(id: string | null): ChatConversation | null {
        const sections = this.sections();
        return (
            CONVERSATION_SECTIONS.flatMap(({ id: section }) => sections[section].rows).find((row) => row.id === id) ??
            null
        );
    }

    private isOpen(section: ChatInboxSection): boolean {
        return listsSection(this.query(), section) && this.expanded().has(section);
    }

    // A section opened or closed: re-arranged rows do not animate, and a newly open one loads its first page.
    private showChange(section: ChatInboxSection): void {
        this.changesSubject.next('load');
        const state = this.sections()[section];
        if (this.isOpen(section) && state.loadedFor !== this.generation() && !state.isLoading) {
            this.loadPage(section, null);
        }
    }

    /**
     * A stream or action row: newest state wins. It leaves the section it was in and is placed by its section's order,
     * so a fresh wait joins the end of the queue and a visitor writing again does not move a waiting row.
     */
    private applyRow(row: ChatConversation): void {
        const query = this.query();
        if (query.bindingId && row.binding_id !== query.bindingId) return;
        this.rowsSinceReload.set(row.id, row);
        if (query.search) {
            this.applySearchedRow(row, query);
            return;
        }
        this.sections.update((sections) => {
            const next = { ...sections };
            for (const { id: section } of CONVERSATION_SECTIONS) {
                const state = sections[section];
                const rows =
                    listsSection(query, section) && belongsTo(row, section, query.holderId)
                        ? placeRow(state.rows, row, inboxOrder(section, query.order), state.boundary)
                        : state.rows.filter((item) => item.id !== row.id);
                next[section] = { ...state, rows };
            }
            return next;
        });
        this.changesSubject.next('live');
    }

    /**
     * While searching, the server decides what matches, and what it matches depends on the section (an operator's name
     * only in Waiting and In progress, a signed id never in Tests). So a shown row is updated in place while it keeps
     * its section and holder, and leaves when either changes: it comes back with the next search load if it still
     * matches. A row not shown is never added.
     */
    private applySearchedRow(row: ChatConversation, query: ConversationListQuery): void {
        const sections = this.sections();
        const shownIn = CONVERSATION_SECTIONS.map(({ id }) => id).filter((section) =>
            sections[section].rows.some((item) => item.id === row.id)
        );
        if (!shownIn.length) return;
        const next = { ...sections };
        for (const section of shownIn) {
            const state = sections[section];
            const shown = state.rows.find((item) => item.id === row.id)!;
            const rows = keepsMatch(shown, row, section, query.holderId)
                ? placeRow(state.rows, row, inboxOrder(section, query.order), state.boundary)
                : state.rows.filter((item) => item.id !== row.id);
            next[section] = { ...state, rows };
        }
        this.sections.set(next);
        this.changesSubject.next('live');
    }

    private loadPage(section: ChatInboxSection, cursor: string | null): void {
        const query = this.query();
        const generation = this.generation();
        // A failed reload must not leave the previous query's cursor behind for the next page.
        this.patchSection(
            section,
            cursor ? { isLoading: true } : { isLoading: true, nextCursor: null, boundary: null }
        );
        // Only the latest request per section may land: an older response would overwrite fresher rows or the cursor.
        this.pageRequests[section]?.unsubscribe();
        this.pageRequests[section] = this.chatApi
            .getConversations({
                section,
                binding: query.bindingId,
                cursor,
                mine: query.holderId !== null,
                order: query.order,
                q: query.search,
            })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (result) => {
                    if (this.generation() !== generation) return;
                    const boundary = result.next_cursor ? (result.results.at(-1) ?? null) : null;
                    // Later pages add to the rows already listed; a first page replaces them.
                    const listed = cursor ? this.sections()[section].rows : [];
                    const page: SectionPage = { section, query, listed, results: result.results, boundary };
                    const rows = query.search ? this.searchedPageRows(page) : this.pageRows(page);
                    this.patchSection(section, {
                        rows,
                        nextCursor: result.next_cursor,
                        boundary,
                        isLoading: false,
                        loadedFor: generation,
                    });
                    this.changesSubject.next('load');
                },
                error: (error: HttpErrorResponse) => {
                    if (isInvalidSearch(error)) {
                        // Every section gets the same answer: nothing is listed for a search the server cannot run.
                        this.searchError.set(invalidSearchMessage(error));
                        this.patchSection(section, { ...emptySection(), loadedFor: generation });
                        this.changesSubject.next('load');
                        return;
                    }
                    this.patchSection(section, { isLoading: false });
                    this.toastService.error(extractHttpErrorMessage(error));
                },
            });
    }

    /**
     * A page merged with what the column already knows. Rows the server returned unchanged are in its window by
     * definition and are never filtered. Everything else is ours: the rows already listed and every row streamed since
     * the load, which also covers a row dropped past the old boundary while this request was in flight. Streamed
     * copies are newer and win; one that changed section is listed by the other.
     */
    private pageRows({ section, query, listed, results, boundary }: SectionPage): ChatConversation[] {
        const order = inboxOrder(section, query.order);
        const pageIds = new Set(results.map((item) => item.id));
        const serverRows = results.filter((item) => !this.rowsSinceReload.has(item.id));
        const ours = new Map<string, ChatConversation>(listed.map((item) => [item.id, item]));
        this.rowsSinceReload.forEach((item, id) => ours.set(id, item));
        const oursInWindow = [...ours.values()].filter(
            (item) =>
                belongsTo(item, section, query.holderId) &&
                (!pageIds.has(item.id) || this.rowsSinceReload.has(item.id)) &&
                (!boundary || order(item, boundary) <= 0)
        );
        return [...serverRows, ...oursInWindow].sort(order);
    }

    /**
     * A search page: only what the server matched. A row streamed since the load replaces its page copy while it
     * keeps the section and holder the search matched it in, and drops it otherwise; nothing streamed is added.
     */
    private searchedPageRows({ section, query, listed, results, boundary }: SectionPage): ChatConversation[] {
        const order = inboxOrder(section, query.order);
        const pageIds = new Set(results.map((item) => item.id));
        const pageRows = results.flatMap((item) => {
            const newer = this.rowsSinceReload.get(item.id);
            if (!newer) return [item];
            const isInWindow = !boundary || order(newer, boundary) <= 0;
            return keepsMatch(item, newer, section, query.holderId) && isInWindow ? [newer] : [];
        });
        return [...listed.filter((item) => !pageIds.has(item.id)), ...pageRows].sort(order);
    }

    private patchSection(section: ChatInboxSection, patch: Partial<ConversationSectionState>): void {
        this.sections.update((sections) => ({ ...sections, [section]: { ...sections[section], ...patch } }));
    }
}

/** One landed page of a section, for the query it was requested for. */
interface SectionPage {
    section: ChatInboxSection;
    query: ConversationListQuery;
    listed: ChatConversation[];
    results: ChatConversation[];
    boundary: ChatConversation | null;
}

/** While searching: a newer copy still matches where the search found it only in the same section, with the same holder. */
const keepsMatch = (
    matched: ChatConversation,
    newer: ChatConversation,
    section: ChatInboxSection,
    holderId: number | null
): boolean => belongsTo(newer, section, holderId) && newer.assigned_operator_id === matched.assigned_operator_id;

const isInvalidSearch = (error: HttpErrorResponse): boolean =>
    error.status === 400 && readErrorField(error, 'code') === 'invalid_search';

// The server says what is wrong (too long, a NUL character); the fallback covers an answer without a message.
const invalidSearchMessage = (error: HttpErrorResponse): string =>
    readErrorField(error, 'message') ?? 'This search cannot be run. Try a shorter one.';

function readErrorField(error: HttpErrorResponse, field: string): string | null {
    const body: unknown = error.error;
    if (!body || typeof body !== 'object') return null;
    const value: unknown = (body as Record<string, unknown>)[field];
    return typeof value === 'string' && value ? value : null;
}

function withoutSection(
    sections: ReadonlySet<ChatInboxSection>,
    section: ChatInboxSection
): ReadonlySet<ChatInboxSection> {
    return new Set([...sections].filter((item) => item !== section));
}
