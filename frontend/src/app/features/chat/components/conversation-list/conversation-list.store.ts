import { HttpErrorResponse } from '@angular/common/http';
import { computed, DestroyRef, inject, Injectable, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { extractHttpErrorMessage } from '@shared/utils';
import { merge, Observable, Subject, Subscription } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { ChatConversation, ChatInboxSection } from '../../models/chat.model';
import { ChatApiService } from '../../services/chat-api.service';
import { ChatConversationActionsService } from '../../services/chat-conversation-actions.service';
import { ChatInboxStreamService } from '../../services/chat-inbox-stream.service';
import { ConversationListPreferencesService } from '../../services/conversation-list-preferences.service';
import { isClosed } from '../../utils/conversation-close.util';
import {
    ConversationListSection,
    ConversationListTab,
    isTestingSection,
    tabOfSection,
} from '../../utils/conversation-list-tab.util';
import { belongsTo, inboxOrder, placeRow } from '../../utils/inbox-merge.util';

/**
 * Why the rows changed: `live` for a stream event or an action result, `load` for anything that loads or re-arranges
 * them (first pages, paging, reloads, another desk, search, Mine, collapsing). Only live changes animate.
 */
export type ConversationListChange = 'live' | 'load';

/** What the column lists; any change starts every list over. */
export interface ConversationListQuery {
    // Inbox's sections, or Bot Testing's.
    tab: ConversationListTab;
    // One desk, or every desk for null.
    bindingId: string | null;
    // Trimmed; empty lists without searching.
    search: string;
    // Mine, on Inbox: the user whose conversations are listed; null lists everyone's.
    holderId: number | null;
}

const EVERYTHING: ConversationListQuery = {
    tab: 'inbox',
    bindingId: null,
    search: '',
    holderId: null,
};

/** One server list (`section=` of the API) as fetched so far: its rows, paged by its own cursor. */
export interface ConversationSectionState {
    rows: ChatConversation[];
    nextCursor: string | null;
    // Last row fetched while more pages remain; live rows sorting after it wait for the next page.
    boundary: ChatConversation | null;
    isLoading: boolean;
    // The query (by generation) whose first page landed here; until it is the current one the list has not loaded.
    loadedFor: number | null;
}

/**
 * A section the column shows. Its rows come from one server list (`list`): all of them for Inbox's sections, which
 * the server lists one by one, and a part of them (`shows`) for Bot Testing's, which share the server's one `test`
 * list. Paging and loading belong to the list, so two sections of one list page together.
 */
export interface ConversationSectionView {
    id: ConversationListSection;
    list: ChatInboxSection;
    // The part of the list this section shows; all of it when absent.
    shows?: (row: ChatConversation) => boolean;
    label: string;
    icon: string;
    // The icon's box when it is not the default one.
    iconSize?: string;
    // The icon's colour, a CSS value; muted when absent.
    iconColor?: string;
    emptyTitle: string;
    emptyDescription: string;
    // Said instead under Mine; only the sections Mine lists have one.
    mineEmptyTitle?: string;
    // Said instead on All desks, where nothing that starts with a desk is there to point at.
    allDesksEmptyDescription?: string;
    // Above the rows of a section that is not newest first, which every other one is.
    orderNote?: string;
    /**
     * Pinned at the column's bottom while the section is below the view, so the last ones are not lost under many open
     * sections: the number of pinned headers under its own. Absent: only on top, while the section scrolls by.
     */
    pinnedBelow?: number;
}

/**
 * Top to bottom. Inbox: the queue first (the one open by default), then what operators are on, what the bot is on,
 * and Closed last — there to look into, not to work through, and an endless history, so it goes below the live ones.
 * Bot Testing the same way: Tests (the ones still open), then the closed ones; both by the latest message, as the
 * server sorts them.
 */
export const CONVERSATION_SECTIONS: readonly ConversationSectionView[] = [
    {
        id: 'waiting',
        list: 'waiting',
        label: 'Waiting for a person',
        icon: 'waiting',
        iconSize: '12px',
        iconColor: 'var(--color-status-waiting)',
        emptyTitle: 'Nobody is waiting',
        emptyDescription: 'Visitors the bot hands over, or who write after an operator took over, line up here.',
        mineEmptyTitle: 'Nobody is waiting for you',
        orderNote: 'Longest wait first',
    },
    {
        id: 'in_progress',
        list: 'in_progress',
        label: 'In progress',
        icon: 'user-outline',
        emptyTitle: 'Nothing in progress',
        emptyDescription: 'Conversations an operator took over and answered last show up here.',
        mineEmptyTitle: 'None of yours in progress',
    },
    {
        id: 'bot',
        list: 'bot',
        label: 'Bot',
        icon: 'bot',
        iconSize: '14px',
        iconColor: 'var(--accent-color)',
        emptyTitle: 'No conversations yet',
        emptyDescription: 'Conversations from your website the bot is answering show up here.',
        pinnedBelow: 1,
    },
    {
        id: 'closed',
        list: 'closed',
        label: 'Closed',
        icon: 'closed',
        iconSize: '12px',
        emptyTitle: 'Nothing closed yet',
        emptyDescription: 'Conversations an operator resolved, the visitor ended or that went quiet end up here.',
        orderNote: 'Most recently closed first',
        pinnedBelow: 0,
    },
    {
        id: 'test_open',
        list: 'test',
        shows: (row) => !isClosed(row),
        label: 'Tests',
        icon: 'flask',
        iconSize: '12px',
        iconColor: 'var(--color-status-info)',
        emptyTitle: 'No test conversations',
        emptyDescription: 'Start one with New Test Chat above.',
        allDesksEmptyDescription: 'Open a desk to start one with New Test Chat.',
        pinnedBelow: 1,
    },
    {
        id: 'test_closed',
        list: 'test',
        shows: isClosed,
        label: 'Closed',
        icon: 'closed',
        iconSize: '12px',
        emptyTitle: 'No closed tests',
        emptyDescription: 'Test conversations that were closed or went quiet end up here.',
        pinnedBelow: 0,
    },
];

// The server lists, each fetched once however many sections show it.
const LISTS: readonly ChatInboxSection[] = ['waiting', 'in_progress', 'closed', 'bot', 'test'];

// Mine lists what the user holds: the bot holds nothing, tests are not work to pick up, and closed conversations are
// done.
const MINE_LISTS: ReadonlySet<ChatInboxSection> = new Set(['waiting', 'in_progress']);

const viewOf = (section: ConversationListSection): ConversationSectionView =>
    CONVERSATION_SECTIONS.find(({ id }) => id === section)!;

/** Whether a query lists a server list at all: only its tab's, and on Inbox, Mine hides Bot and Closed. */
const listsList = (query: ConversationListQuery, list: ChatInboxSection): boolean =>
    list === 'test'
        ? query.tab === 'testing'
        : query.tab === 'inbox' && (query.holderId === null || MINE_LISTS.has(list));

/** Whether a query shows a section at all: one of its tab's, whose list the query lists. */
export const listsSection = (query: ConversationListQuery, section: ConversationListSection): boolean =>
    tabOfSection(section) === query.tab && listsList(query, viewOf(section).list);

/** Whether `section` shows `row` (with `holderId`, under Mine): the server lists it there, and it is this part. */
export const sectionHolds = (
    section: ConversationListSection,
    row: ChatConversation,
    holderId: number | null
): boolean => {
    const view = viewOf(section);
    return belongsTo(row, view.list, holderId) && (view.shows?.(row) ?? true);
};

const emptyList = (): ConversationSectionState => ({
    rows: [],
    nextCursor: null,
    boundary: null,
    isLoading: false,
    loadedFor: null,
});

/**
 * The conversations column's state, one per column: the query, a fetched list per server list (its pages, and live
 * rows from the stream and from this user's actions merged in), and the sections shown from them. It owns the split
 * of the server's `test` list into Bot Testing's two sections. A list no open section shows never loads. Provided on
 * `ConversationListComponent`.
 */
@Injectable()
export class ConversationListStore {
    /** Each server list as fetched; the sections show them (`view`). */
    readonly lists = signal<Record<ChatInboxSection, ConversationSectionState>>({
        waiting: emptyList(),
        in_progress: emptyList(),
        test: emptyList(),
        closed: emptyList(),
        bot: emptyList(),
    });
    private readonly querySignal = signal(EVERYTHING);
    readonly query = this.querySignal.asReadonly();
    readonly isSearching = computed(() => !!this.query().search);
    readonly isMineOnly = computed(() => this.query().holderId !== null);
    /** The server refused the search (`invalid_search`): said next to the field, instead of a list or a toast. */
    readonly searchError = signal<string | null>(null);
    // Bumped by every load: a list has loaded once its first page for the current generation has landed.
    private readonly generation = signal(0);
    /**
     * Sections opened for this column only, beside each tab's remembered one: to look for a conversation the page was
     * asked to open, or for a test that started. Folding one ends its opening; opening a folded one ends them all.
     */
    private readonly openedForColumn = signal<ReadonlySet<ConversationListSection>>(new Set());
    /**
     * The sections open while a search runs, for this column only: every one as it starts, then as the user folds and
     * opens them. Clearing the search returns to the remembered one. Nothing of it is remembered.
     */
    private readonly openedForSearch = signal<ReadonlySet<ConversationListSection>>(new Set());
    // Open as shown: the search's own while searching, else the tab's remembered section and those opened for this
    // column.
    private readonly expanded = computed((): ReadonlySet<ConversationListSection> => {
        if (this.isSearching()) return this.openedForSearch();
        const remembered = this.rememberedIn(this.query().tab);
        return new Set([...(remembered ? [remembered] : []), ...this.openedForColumn()]);
    });
    /**
     * Each section the query shows, in column order, whether it is open, and its state: its list's, with only the rows
     * it shows. `pagesList`: a list's next page loads under the last section showing it, while that one is open. On
     * Bot Testing that is Closed: paging follows the scroll through the closed tests, and Tests shows the open tests
     * of the pages loaded so far, without paging of its own, so it never pages through the whole test history by
     * itself.
     */
    readonly view = computed(() => {
        const lists = this.lists();
        const expanded = this.expanded();
        const query = this.query();
        const shown = CONVERSATION_SECTIONS.filter((section) => listsSection(query, section.id));
        // Later sections overwrite earlier ones: each list ends up with its last.
        const pagingSection = new Map(shown.map((section) => [section.list, section.id]));
        return shown.map((section) => {
            const list = lists[section.list];
            const shows = section.shows;
            return {
                section,
                state: shows ? { ...list, rows: list.rows.filter(shows) } : list,
                isExpanded: expanded.has(section.id),
                pagesList: pagingSection.get(section.list) === section.id,
            };
        });
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
     * Some section is open and every open one has its list's first page for the current query: what the column shows
     * is known. A list that failed to load keeps it false, so nothing concludes a conversation is not listed from a
     * list that did not load; so does a column with every section collapsed, which shows nothing to conclude from.
     */
    readonly isLoaded = computed(() => {
        const generation = this.generation();
        const open = this.view().filter(({ isExpanded }) => isExpanded);
        return open.length > 0 && open.every(({ state }) => state.loadedFor === generation);
    });
    private readonly chatApi = inject(ChatApiService);
    private readonly toastService = inject(ToastService);
    private readonly preferences = inject(ConversationListPreferencesService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly pageRequests: Partial<Record<ChatInboxSection, Subscription>> = {};
    // Rows streamed since the last load: newer than any page fetched meanwhile, so they win over the first pages and
    // over later pages, in whichever list they now belong to.
    private rowsSinceReload = new Map<string, ChatConversation>();

    constructor() {
        merge(inject(ChatInboxStreamService).conversationUpdated$, inject(ChatConversationActionsService).changed$)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((row) => this.applyRow(row));
    }

    /**
     * Lists `query` from the start: every list starts over. Lists an open section shows keep their rows on screen
     * until their first pages land; any other list is emptied and loads only once shown. A search starting opens every
     * section; clearing it folds them back.
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
        for (const list of LISTS) {
            if (this.isShown(list)) {
                this.loadPage(list, null);
            } else {
                this.pageRequests[list]?.unsubscribe();
                this.patchList(list, emptyList());
            }
        }
    }

    /** The next page of an open section's list, once its first has landed; one request at a time per list. */
    loadMore(section: ConversationListSection): void {
        const list = viewOf(section).list;
        const state = this.lists()[list];
        if (state.isLoading || !state.nextCursor || !this.isShown(list)) return;
        this.loadPage(list, state.nextCursor);
    }

    /** Folds or opens a section; outside a search, opening one remembers it for its tab and folds the rest. */
    toggle(section: ConversationListSection): void {
        const tab = tabOfSection(section);
        if (this.isSearching()) {
            this.openedForSearch.update((sections) =>
                sections.has(section) ? withoutSection(sections, section) : new Set([...sections, section])
            );
        } else if (this.expanded().has(section)) {
            this.openedForColumn.update((sections) => withoutSection(sections, section));
            if (this.rememberedIn(tab) === section) this.remember(tab, null);
        } else {
            this.openedForColumn.set(new Set());
            this.remember(tab, section);
        }
        this.showChange(section);
    }

    /** Opens a collapsed section in this column only; the remembered choice stays as it is. */
    openForColumn(section: ConversationListSection): void {
        if (this.rememberedIn(tabOfSection(section)) === section || this.openedForColumn().has(section)) return;
        this.openedForColumn.update((sections) => new Set([...sections, section]));
        this.showChange(section);
    }

    findRow(id: string | null): ChatConversation | null {
        const lists = this.lists();
        return LISTS.flatMap((list) => lists[list].rows).find((row) => row.id === id) ?? null;
    }

    // Each tab remembers its own open section.
    private rememberedIn(tab: ConversationListTab): ConversationListSection | null {
        return tab === 'inbox' ? this.preferences.expanded() : this.preferences.testingExpanded();
    }

    private remember(tab: ConversationListTab, section: ConversationListSection | null): void {
        if (tab === 'testing') {
            this.preferences.setTestingExpanded(section && isTestingSection(section) ? section : null);
        } else {
            this.preferences.setExpanded(section && !isTestingSection(section) ? section : null);
        }
    }

    // A list loads while some open section the query shows takes its rows from it.
    private isShown(list: ChatInboxSection): boolean {
        const query = this.query();
        const expanded = this.expanded();
        return CONVERSATION_SECTIONS.some(
            (section) => section.list === list && expanded.has(section.id) && listsSection(query, section.id)
        );
    }

    // A section opened or closed: re-arranged rows do not animate, and a list newly shown loads its first page.
    private showChange(section: ConversationListSection): void {
        this.changesSubject.next('load');
        const list = viewOf(section).list;
        const state = this.lists()[list];
        if (this.isShown(list) && state.loadedFor !== this.generation() && !state.isLoading) {
            this.loadPage(list, null);
        }
    }

    /**
     * A stream or action row: newest state wins. It leaves the list it was in and is placed by its list's order, so a
     * fresh wait joins the end of the queue and a visitor writing again does not move a waiting row. A test that
     * closes stays in the `test` list, and so moves from Bot Testing's Tests to its Closed.
     */
    private applyRow(row: ChatConversation): void {
        const query = this.query();
        if (query.bindingId && row.binding_id !== query.bindingId) return;
        this.rowsSinceReload.set(row.id, row);
        if (query.search) {
            this.applySearchedRow(row, query);
            return;
        }
        this.lists.update((lists) => {
            const next = { ...lists };
            for (const list of LISTS) {
                const state = lists[list];
                const rows =
                    listsList(query, list) && belongsTo(row, list, query.holderId)
                        ? placeRow(state.rows, row, inboxOrder(list), state.boundary)
                        : state.rows.filter((item) => item.id !== row.id);
                next[list] = { ...state, rows };
            }
            return next;
        });
        this.changesSubject.next('live');
    }

    /**
     * While searching, the server decides what matches, and what it matches depends on the list (an operator's name
     * only in Waiting and In progress, a signed id never in Bot Testing). So a shown row is updated in place while it
     * keeps its list and holder, and leaves when either changes: it comes back with the next search load if it still
     * matches. A row not shown is never added.
     */
    private applySearchedRow(row: ChatConversation, query: ConversationListQuery): void {
        const lists = this.lists();
        const shownIn = LISTS.filter((list) => lists[list].rows.some((item) => item.id === row.id));
        if (!shownIn.length) return;
        const next = { ...lists };
        for (const list of shownIn) {
            const state = lists[list];
            const shown = state.rows.find((item) => item.id === row.id)!;
            const rows = keepsMatch(shown, row, list, query.holderId)
                ? placeRow(state.rows, row, inboxOrder(list), state.boundary)
                : state.rows.filter((item) => item.id !== row.id);
            next[list] = { ...state, rows };
        }
        this.lists.set(next);
        this.changesSubject.next('live');
    }

    private loadPage(section: ChatInboxSection, cursor: string | null): void {
        const query = this.query();
        const generation = this.generation();
        // A failed reload must not leave the previous query's cursor behind for the next page.
        this.patchList(section, cursor ? { isLoading: true } : { isLoading: true, nextCursor: null, boundary: null });
        // Only the latest request per section may land: an older response would overwrite fresher rows or the cursor.
        this.pageRequests[section]?.unsubscribe();
        this.pageRequests[section] = this.chatApi
            .getConversations({
                section,
                binding: query.bindingId,
                cursor,
                mine: query.holderId !== null,
                order: 'newest',
                q: query.search,
            })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (result) => {
                    if (this.generation() !== generation) return;
                    const boundary = result.next_cursor ? (result.results.at(-1) ?? null) : null;
                    // Later pages add to the rows already listed; a first page replaces them.
                    const listed = cursor ? this.lists()[section].rows : [];
                    const page: SectionPage = { section, query, listed, results: result.results, boundary };
                    const rows = query.search ? this.searchedPageRows(page) : this.pageRows(page);
                    this.patchList(section, {
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
                        this.patchList(section, { ...emptyList(), loadedFor: generation });
                        this.changesSubject.next('load');
                        return;
                    }
                    this.patchList(section, { isLoading: false });
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
        const order = inboxOrder(section);
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
        const order = inboxOrder(section);
        const pageIds = new Set(results.map((item) => item.id));
        const pageRows = results.flatMap((item) => {
            const newer = this.rowsSinceReload.get(item.id);
            if (!newer) return [item];
            const isInWindow = !boundary || order(newer, boundary) <= 0;
            return keepsMatch(item, newer, section, query.holderId) && isInWindow ? [newer] : [];
        });
        return [...listed.filter((item) => !pageIds.has(item.id)), ...pageRows].sort(order);
    }

    private patchList(list: ChatInboxSection, patch: Partial<ConversationSectionState>): void {
        this.lists.update((lists) => ({ ...lists, [list]: { ...lists[list], ...patch } }));
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
    sections: ReadonlySet<ConversationListSection>,
    section: ConversationListSection
): ReadonlySet<ConversationListSection> {
    return new Set([...sections].filter((item) => item !== section));
}
