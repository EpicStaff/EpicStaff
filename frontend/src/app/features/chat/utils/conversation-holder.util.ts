import { ChatConversation } from '../models/chat.model';
import { isClosed } from './conversation-close.util';
import { operatorName } from './conversation-row.util';

type HeldConversation = Pick<ChatConversation, 'assigned_operator_id' | 'assigned_operator_name' | 'status'>;

/**
 * Who holds a conversation, as the list's row and the thread's header name them: "you", the operator's name, or
 * "Operator #7" while it is not known. Null while nobody does, and on a closed one: nobody is on it any more.
 */
export function holderName(conversation: HeldConversation, myUserId: number | null): string | null {
    // An older payload may lack the fields: read as nobody, and no name yet.
    const operatorId = conversation.assigned_operator_id ?? null;
    if (operatorId === null || isClosed(conversation)) return null;
    return operatorId === myUserId ? 'you' : operatorName(operatorId, conversation.assigned_operator_name ?? null);
}
