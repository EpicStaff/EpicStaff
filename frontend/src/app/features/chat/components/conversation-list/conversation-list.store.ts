import { HttpErrorResponse } from '@angular/common/http';
import { computed, DestroyRef, inject, Injectable, linkedSignal, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { extractHttpErrorMessage } from '@shared/utils';
import { merge, Subscription } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { ChatConversation, ChatInboxSection } from '../../models/chat.model';
import { ChatApiService } from '../../services/chat-api.service';
import { ChatConversationActionsService } from '../../services/chat-conversation-actions.service';
import { ChatDesksStorageService } from '../../services/chat-desks-storage.service';
import { ChatInboxStreamService } from '../../services/chat-inbox-stream.service';
import { INBOX_ORDER, inboxSection, placeRow } from '../../utils/inbox-merge.util';

// The scope that lists every desk.
const ALL_DESKS = '';
// Pinned to the top of the column; every other collapsed section rests at the bottom.
const TOP_SECTION: ChatInboxSection = 'human';

export interface ConversationSectionState {
    rows: ChatConversation[];
    nextCursor: string | null;
    // Last row fetched while more pages remain; live rows sorting after it wait for Load more.
    boundary: ChatConversation | null;
    isLoading: boolean;
}

export interface ConversationSectionView {
    id: ChatInboxSection;
    label: string;
    icon: string;
    emptyTitle: string;
    emptyDescription: string;
}

export const CONVERSATION_SECTIONS: readonly ConversationSectionView[] = [
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
        emptyDescription: 'Start one with Test on a desk.',
    },
];

const emptySection = (): ConversationSectionState => ({ rows: [], nextCursor: null, boundary: null, isLoading: false });

/** A row is listed in its own section; the server hides bot and test conversations without messages. */
const belongsTo = (row: ChatConversation, section: ChatInboxSection): boolean =>
    inboxSection(row) === section && (section === 'human' || !!row.last_message_at);

/**
 * The conversations column's state, one per column: a section per inbox section, its pages, and live rows from the
 * stream and from this user's actions merged in. Provided on `ConversationListComponent`.
 */
@Injectable()
export class ConversationListStore {
    readonly sections = signal<Record<ChatInboxSection, ConversationSectionState>>({
        human: emptySection(),
        bot: emptySection(),
        test: emptySection(),
    });
    // Bot and Tests start collapsed: the human queue is the work; the others are there to look into.
    readonly expanded = signal<Record<ChatInboxSection, boolean>>({ human: true, bot: false, test: false });
    // The desk listed, or every desk.
    private readonly scope = signal(ALL_DESKS);
    // The scope whose first human page last landed: until then the human rows still belong to the previous scope.
    private readonly humanLoadedFor = signal<string | null>(null);
    /**
     * Without handoff a desk has no human queue, unless conversations handed off before it was turned off still wait
     * there: hiding those would leave them unreachable. Decided only once the human page for the current scope has
     * landed; meanwhile the previous decision stands, so a switch never flashes the section in and out.
     */
    private readonly showsHumanSection = linkedSignal<
        { scope: string; handoffEnabled: boolean; isLoaded: boolean; hasRows: boolean },
        boolean
    >({
        source: () => {
            const scope = this.scope();
            const desk = this.desksStorage.desks().find((item) => item.id === scope);
            return {
                scope,
                handoffEnabled: desk?.handoff_enabled !== false,
                isLoaded: this.humanLoadedFor() === scope,
                hasRows: this.sections().human.rows.length > 0,
            };
        },
        computation: (source, previous) => {
            if (!source.scope || source.handoffEnabled) return true;
            return source.isLoaded ? source.hasRows : (previous?.value ?? true);
        },
    });
    /**
     * Same layout as the agents explorer: the lowest expanded section fills the leftover height and scrolls, and the
     * first section below it is pushed to the bottom. The top section stays at the top.
     */
    readonly layout = computed(() => {
        const visible = CONVERSATION_SECTIONS.filter(({ id }) => id !== 'human' || this.showsHumanSection());
        const expanded = this.expanded();
        const lastExpanded = visible.reduce((last, { id }, index) => (expanded[id] ? index : last), -1);
        const bottomAnchor = visible.findIndex(({ id }, index) => index > lastExpanded && id !== TOP_SECTION);
        return visible.map((section, index) => ({
            section,
            fills: index === lastExpanded,
            anchorsBottom: index === bottomAnchor,
        }));
    });
    /** The rows as shown, top to bottom: those of the expanded sections, in order. What ↑/↓ moves through. */
    readonly visibleRows = computed(() => {
        const sections = this.sections();
        const expanded = this.expanded();
        return this.layout()
            .filter(({ section }) => expanded[section.id])
            .flatMap(({ section }) => sections[section.id].rows);
    });

    private readonly chatApi = inject(ChatApiService);
    private readonly toastService = inject(ToastService);
    private readonly desksStorage = inject(ChatDesksStorageService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly pageRequests: Partial<Record<ChatInboxSection, Subscription>> = {};
    // Rows streamed since the last reload: newer than any page fetched meanwhile, so they win over the first pages and
    // over Load more pages, in whichever section they now belong to.
    private rowsSinceReload = new Map<string, ChatConversation>();

    constructor() {
        merge(inject(ChatInboxStreamService).conversationUpdated$, inject(ChatConversationActionsService).changed$)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((row) => this.applyRow(row));
    }

    /** Lists one desk's conversations, or every desk's for null. The rows stay on screen until the first pages land. */
    reload(bindingId: string | null): void {
        this.scope.set(bindingId ?? ALL_DESKS);
        this.rowsSinceReload = new Map();
        for (const { id: section } of CONVERSATION_SECTIONS) this.loadPage(section, null);
    }

    loadMore(section: ChatInboxSection): void {
        const cursor = this.sections()[section].nextCursor;
        if (cursor) this.loadPage(section, cursor);
    }

    toggle(section: ChatInboxSection): void {
        this.expanded.update((state) => ({ ...state, [section]: !state[section] }));
    }

    expand(section: ChatInboxSection): void {
        this.expanded.update((state) => ({ ...state, [section]: true }));
    }

    findRow(id: string | null): ChatConversation | null {
        const sections = this.sections();
        return (
            CONVERSATION_SECTIONS.flatMap(({ id: section }) => sections[section].rows).find((row) => row.id === id) ??
            null
        );
    }

    /**
     * A stream or action row: newest state wins. It leaves the section it was in and is placed by its section's order,
     * so a handed-off row joins the end of the human queue and a reply on a human row does not move it.
     */
    private applyRow(row: ChatConversation): void {
        const scope = this.scope();
        if (scope && row.binding_id !== scope) return;
        this.rowsSinceReload.set(row.id, row);
        this.sections.update((sections) => {
            const next = { ...sections };
            for (const { id: section } of CONVERSATION_SECTIONS) {
                const state = sections[section];
                const rows = belongsTo(row, section)
                    ? placeRow(state.rows, row, INBOX_ORDER[section], state.boundary)
                    : state.rows.filter((item) => item.id !== row.id);
                next[section] = { ...state, rows };
            }
            return next;
        });
    }

    private loadPage(section: ChatInboxSection, cursor: string | null): void {
        const binding = this.scope() || null;
        // A failed reload must not leave the previous scope's cursor behind for Load more.
        this.patchSection(
            section,
            cursor ? { isLoading: true } : { isLoading: true, nextCursor: null, boundary: null }
        );
        // Only the latest request per section may land: an older response would overwrite fresher rows or the cursor.
        this.pageRequests[section]?.unsubscribe();
        this.pageRequests[section] = this.chatApi
            .getConversations({ section, binding, cursor })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (result) => {
                    if ((this.scope() || null) !== binding) return;
                    if (section === 'human' && !cursor) this.humanLoadedFor.set(binding ?? ALL_DESKS);
                    const order = INBOX_ORDER[section];
                    const boundary = result.next_cursor ? (result.results.at(-1) ?? null) : null;
                    const pageIds = new Set(result.results.map((item) => item.id));
                    // Rows the server returned unchanged are in its window by definition and are never filtered.
                    const serverRows = result.results.filter((item) => !this.rowsSinceReload.has(item.id));
                    // Everything else is ours: the rows already listed (Load more only) and every row streamed since the
                    // reload, which also covers a row dropped past the old boundary while this request was in flight.
                    // Streamed copies are newer and win; one that changed section is listed by the other.
                    const ours = new Map<string, ChatConversation>(
                        cursor ? this.sections()[section].rows.map((item) => [item.id, item]) : []
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

    private patchSection(section: ChatInboxSection, patch: Partial<ConversationSectionState>): void {
        this.sections.update((sections) => ({ ...sections, [section]: { ...sections[section], ...patch } }));
    }
}
