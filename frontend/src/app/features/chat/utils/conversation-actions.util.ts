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
    // Phones have no room for the main action's button: it leads the ⋯ menu instead.
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
 * The conversation's main action, the filled button in the header (on phones, the first item of the ⋯ menu). On a
 * Support desk it is Resolve whoever holds the conversation (the user, another operator or nobody, test or not). For
 * the holder elsewhere: Done (back to the bot, still open) on an Ongoing desk, Release while the desk is not known.
 * Null for anyone else there, and on a closed conversation.
 */
export function primaryConversationAction(context: ConversationActionContext): ConversationActionItem | null {
    if (!context.canUse || context.isClosed) return null;
    if (context.style === 'support') return { id: 'resolve', label: 'Resolve' };
    if (context.holder !== 'me') return null;
    return context.style === 'ongoing' ? { id: 'release', label: 'Done' } : { id: 'release', label: 'Release' };
}

/**
 * The open conversation's other actions, in its ⋯ menu; none once it is closed. On a phone the main action (see
 * `primaryConversationAction`) leads the menu, as it has no button there. Then, the holder: Hand Back to Bot on a
 * Support desk, Close conversation on an Ongoing one. Another operator's: Take over, Hand Back to Bot and, on an
 * Ongoing desk, Close conversation. Unclaimed or the bot's: Close conversation on an Ongoing desk. Support's close,
 * Resolve, is always the main action, so never here; no close is offered while the desk is not known.
 */
export function conversationMenuItems(context: ConversationActionContext): ConversationActionItem[] {
    if (!context.canUse || context.isClosed) return [];
    const disabled = context.isPending;
    const primary = primaryConversationAction(context);
    const leading: ConversationActionItem[] = context.isPhone && primary ? [{ ...primary, disabled }] : [];
    const handBackToBot: ConversationActionItem = { id: 'release', label: 'Hand Back to Bot', disabled };
    const closeItems = closeMenuItems(context.style, disabled);
    switch (context.holder) {
        case 'me':
            return [...leading, ...(context.style === 'support' ? [handBackToBot] : closeItems)];
        case 'other':
            return [...leading, { id: 'take-over', label: 'Take over', disabled }, handBackToBot, ...closeItems];
        case 'none':
            return [...leading, ...closeItems];
    }
}

/** The close as a menu item: only Ongoing's Close conversation, as Support's Resolve is the main action. */
function closeMenuItems(style: ChatConversationStyle | null, disabled: boolean): ConversationActionItem[] {
    return style === 'ongoing' ? [{ id: 'close', label: 'Close conversation', disabled }] : [];
}
