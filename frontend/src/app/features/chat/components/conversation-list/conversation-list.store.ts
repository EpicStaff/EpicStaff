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
import {
    ConversationListSection,
    ConversationListTab,
    isTestingSection,
    tabOfSection,
} from '../../utils/conversation-list-tab.util';
import { CONVERSATION_SECTIONS, sectionView } from '../../utils/conversation-section.util';
import { belongsTo, inboxOrder, placeRow } from '../../utils/inbox-merge.util';

/**
 * Why the rows changed: `live` for a stream event or an action result, `load` for anything that loads or re-arranges
 * them (first pages, paging, reloads, another desk, search, Mine, folding or opening a section). Only live changes
 * animate.
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
    // The query (by generation) whose first page failed here, until it is asked for again: nothing more is coming.
    failedFor: number | null;
}
// The server lists, each fetched once however many sections show it.
const LISTS: readonly ChatInboxSection[] = ['waiting', 'in_progress', 'closed', 'bot', 'test'];

// Mine lists what the user holds: the bot holds nothing, tests are not work to pick up, and closed conversations are
// done.
const MINE_LISTS: ReadonlySet<ChatInboxSection> = new Set(['waiting', 'in_progress']);

/** Whether a query lists a server list at all: only its tab's, and on Inbox, Mine hides Bot and Closed. */
const listsList = (query: ConversationListQuery, list: ChatInboxSection): boolean =>
    list === 'test'
        ? query.tab === 'testing'
        : query.tab === 'inbox' && (query.holderId === null || MINE_LISTS.has(list));

/** Whether a query shows a section at all: one of its tab's, whose list the query lists. */
export const listsSection = (query: ConversationListQuery, section: ConversationListSection): boolean =>
    tabOfSection(section) === query.tab && listsList(query, sectionView(section).list);

const emptyList = (): ConversationSectionState => ({
    rows: [],
    nextCursor: null,
    boundary: null,
    isLoading: false,
    loadedFor: null,
    failedFor: null,
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
     * Sections opened for this column only, beside each tab's remembered ones: to look for a conversation the page was
     * asked to open, or for a test that started. Folding one ends its opening.
     */
    private readonly openedForColumn = signal<ReadonlySet<ConversationListSection>>(new Set());
    /**
     * The sections open while a search runs, for this column only: every one as it starts, then as the user folds and
     * opens them. Clearing the search returns to the remembered ones. Nothing of it is remembered.
     */
    private readonly openedForSearch = signal<ReadonlySet<ConversationListSection>>(new Set());
    // Open as shown: the search's own while searching, else the tab's remembered sections and those opened for this
    // column.
    private readonly expanded = computed((): ReadonlySet<ConversationListSection> => {
        if (this.isSearching()) return this.openedForSearch();
        return new Set([...this.rememberedIn(this.query().tab), ...this.openedForColumn()]);
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
     * Some section is open and every open one's list has settled for the current query: its first page landed, or
     * failed (toasted), so nothing more is coming to wait for. A conversation such a list would have held is then just
     * not listed, which the page answers by fetching it by id. A column with every section collapsed keeps it false:
     * it shows nothing to conclude from.
     */
    readonly isSettled = computed(() => {
        const generation = this.generation();
        const open = this.view().filter(({ isExpanded }) => isExpanded);
        return (
            open.length > 0 &&
            open.every(({ state }) => state.loadedFor === generation || state.failedFor === generation)
        );
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
     * section; clearing it returns to the ones open before.
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
        const list = sectionView(section).list;
        const state = this.lists()[list];
        if (state.isLoading || !state.nextCursor || !this.isShown(list)) return;
        this.loadPage(list, state.nextCursor);
    }

    /**
     * Folds or opens one section; the others stay as they are. Outside a search the choice is remembered for its tab;
     * folding one opened for this column ends that opening too.
     */
    toggle(section: ConversationListSection): void {
        if (this.isSearching()) {
            this.openedForSearch.update((sections) => withSection(sections, section, !sections.has(section)));
        } else {
            const isOpening = !this.expanded().has(section);
            if (!isOpening) this.openedForColumn.update((sections) => withSection(sections, section, false));
            this.remember(section, isOpening);
        }
        this.showChange(section);
    }

    /** Opens a collapsed section in this column only; the remembered choice stays as it is. */
    openForColumn(section: ConversationListSection): void {
        if (this.rememberedIn(tabOfSection(section)).includes(section) || this.openedForColumn().has(section)) return;
        this.openedForColumn.update((sections) => withSection(sections, section, true));
        this.showChange(section);
    }

    findRow(id: string | null): ChatConversation | null {
        const lists = this.lists();
        return LISTS.flatMap((list) => lists[list].rows).find((row) => row.id === id) ?? null;
    }

    // Each tab remembers its own open sections.
    private rememberedIn(tab: ConversationListTab): readonly ConversationListSection[] {
        return tab === 'inbox' ? this.preferences.openSections() : this.preferences.openTestingSections();
    }

    // Remembers `section` open or folded in its tab, beside the tab's other remembered sections.
    private remember(section: ConversationListSection, isOpen: boolean): void {
        if (isTestingSection(section)) {
            const sections = this.preferences.openTestingSections();
            this.preferences.setOpenTestingSections(
                isOpen ? [...sections, section] : sections.filter((item) => item !== section)
            );
        } else {
            const sections = this.preferences.openSections();
            this.preferences.setOpenSections(
                isOpen ? [...sections, section] : sections.filter((item) => item !== section)
            );
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
        const list = sectionView(section).list;
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
        this.patchList(
            section,
            cursor ? { isLoading: true } : { isLoading: true, nextCursor: null, boundary: null, failedFor: null }
        );
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
                    // A first page that failed settles the list for this query; a later one leaves the pages listed.
                    this.patchList(
                        section,
                        cursor ? { isLoading: false } : { isLoading: false, failedFor: generation }
                    );
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

function withSection(
    sections: ReadonlySet<ConversationListSection>,
    section: ConversationListSection,
    isIncluded: boolean
): ReadonlySet<ConversationListSection> {
    const next = new Set(sections);
    if (isIncluded) next.add(section);
    else next.delete(section);
    return next;
}
