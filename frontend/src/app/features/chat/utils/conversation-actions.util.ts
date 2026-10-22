import { ChatActionMenuItem } from '../components/chat-action-menu/chat-action-menu.component';
import { ChatConversation, ChatConversationStyle } from '../models/chat.model';

// `release` is Done on an Ongoing desk; `resolve` and `close` are one close, worded by the desk's style.
export type ConversationAction = 'take-over' | 'release' | 'resolve' | 'close';
export type ConversationActionItem = ChatActionMenuItem<ConversationAction>;

/** Who holds a conversation, as its actions see it: the user, another operator, or nobody (unclaimed, the bot's). */
export type ConversationHolder = 'me' | 'other' | 'none';

/** Everything the open conversation's actions depend on. */
export interface ConversationActionContext {
    // The desk's style; null while the desk is not known.
    style: ChatConversationStyle | null;
    holder: ConversationHolder;
    isClosed: boolean;
    // Phones have no room for the main action's button beside the title.
    isPhone: boolean;
    // Chats use: without it there is no action at all.
    canUse: boolean;
    // Another action is running: the menu's items are disabled.
    isPending: boolean;
}

/** A taken conversation is the user's or another operator's; any other is nobody's. */
export function conversationHolder(
    conversation: Pick<ChatConversation, 'mode' | 'assigned_operator_id'>,
    myUserId: number | null
): ConversationHolder {
    if (conversation.mode !== 'human') return 'none';
    return myUserId !== null && conversation.assigned_operator_id === myUserId ? 'me' : 'other';
}

/**
 * The holder's main action, a button beside the title: Resolve on a Support desk, Done (back to the bot, still open) on
 * an Ongoing one, Release while the desk is not known. Null for anyone else and on a closed conversation.
 */
export function primaryConversationAction(context: ConversationActionContext): ConversationActionItem | null {
    if (!context.canUse || context.isClosed || context.holder !== 'me') return null;
    switch (context.style) {
        case 'support':
            return { id: 'resolve', label: 'Resolve' };
        case 'ongoing':
            return { id: 'release', label: 'Done' };
        default:
            return { id: 'release', label: 'Release' };
    }
}

/**
 * The open conversation's other actions, in its ⋯ menu; none once it is closed. The holder: Release to bot on a Support
 * desk, Close conversation on an Ongoing one; on a phone the main action leads the menu. Another operator's: Take over,
 * Release to bot and the close. Unclaimed or the bot's: the close. The close is Resolve (Support) or Close conversation
 * (Ongoing), and is not offered while the desk is not known.
 */
export function conversationMenuItems(context: ConversationActionContext): ConversationActionItem[] {
    if (!context.canUse || context.isClosed) return [];
    const disabled = context.isPending;
    const releaseToBot: ConversationActionItem = { id: 'release', label: 'Release to bot', disabled };
    const closeItems = closeMenuItems(context.style, disabled);
    switch (context.holder) {
        case 'me': {
            const others = context.style === 'support' ? [releaseToBot] : closeItems;
            const primary = primaryConversationAction(context);
            return context.isPhone && primary ? [{ ...primary, disabled }, ...others] : others;
        }
        case 'other':
            return [{ id: 'take-over', label: 'Take over', disabled }, releaseToBot, ...closeItems];
        case 'none':
            return closeItems;
    }
}

function closeMenuItems(style: ChatConversationStyle | null, disabled: boolean): ConversationActionItem[] {
    switch (style) {
        case 'support':
            return [{ id: 'resolve', label: 'Resolve', disabled }];
        case 'ongoing':
            return [{ id: 'close', label: 'Close conversation', disabled }];
        default:
            return [];
    }
}
