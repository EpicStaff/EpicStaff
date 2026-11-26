import { ChatConversation, ChatInboxSection } from '../models/chat.model';
import { isClosed } from './conversation-close.util';
import { ConversationListSection } from './conversation-list-tab.util';
import { belongsTo } from './inbox-merge.util';

/**
 * A section the column shows. Its rows come from one server list (`list`): all of them for Inbox's sections, which
 * the server lists one by one, and a part of them (`shows`) for Bot Testing's, which share the server's one `test`
 * list. Paging and loading belong to the list, so two sections of one list page together. Its icon is in
 * `CONVERSATION_SECTION_ICONS`, as the rows it lists show it too.
 */
export interface ConversationSectionView {
    id: ConversationListSection;
    list: ChatInboxSection;
    // The part of the list this section shows; all of it when absent.
    shows?: (row: ChatConversation) => boolean;
    label: string;
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
 * Top to bottom. Inbox: the queue first, then what operators are on, what the bot is on, and Closed last — there to
 * look into, not to work through, and an endless history, so it goes below the live ones.
 * Bot Testing the same way: Tests (the ones still open), then the closed ones; both by the latest message, as the
 * server sorts them.
 */
export const CONVERSATION_SECTIONS: readonly ConversationSectionView[] = [
    {
        id: 'waiting',
        list: 'waiting',
        label: 'Waiting for a person',
        emptyTitle: 'Nobody is waiting',
        emptyDescription: 'Visitors the bot hands over, or who write after an operator took over, line up here.',
        mineEmptyTitle: 'Nobody is waiting for you',
        orderNote: 'Longest wait first',
    },
    {
        id: 'in_progress',
        list: 'in_progress',
        label: 'In progress',
        emptyTitle: 'Nothing in progress',
        emptyDescription: 'Conversations an operator took over and answered last show up here.',
        mineEmptyTitle: 'None of yours in progress',
    },
    {
        id: 'bot',
        list: 'bot',
        label: 'Bot',
        emptyTitle: 'No conversations yet',
        emptyDescription: 'Conversations from your website the bot is answering show up here.',
        pinnedBelow: 1,
    },
    {
        id: 'closed',
        list: 'closed',
        label: 'Closed',
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
        emptyTitle: 'No closed tests',
        emptyDescription: 'Test conversations that were closed or went quiet end up here.',
        pinnedBelow: 0,
    },
];

/** A section's view, by its id. */
export const sectionView = (section: ConversationListSection): ConversationSectionView =>
    CONVERSATION_SECTIONS.find(({ id }) => id === section)!;

/** Whether `section` shows `row` (with `holderId`, under Mine): the server lists it there, and it is this part. */
export const sectionHolds = (
    section: ConversationListSection,
    row: ChatConversation,
    holderId: number | null
): boolean => {
    const view = sectionView(section);
    return belongsTo(row, view.list, holderId) && (view.shows?.(row) ?? true);
};

/**
 * The section a conversation is in, whoever holds it: the first, top to bottom, that shows it. Null for one no section
 * shows: a conversation without a message yet, outside Waiting (the server lists it nowhere until its first message).
 */
export const sectionOfConversation = (row: ChatConversation): ConversationListSection | null =>
    CONVERSATION_SECTIONS.find(({ id }) => sectionHolds(id, row, null))?.id ?? null;
