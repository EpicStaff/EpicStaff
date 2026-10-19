import { ChatBinding } from '../models/chat.model';

export type ChatBindingStatus = 'live' | 'paused' | 'broken';

export const CHAT_BINDING_STATUS_LABELS: Record<ChatBindingStatus, string> = {
    live: 'Live',
    paused: 'Paused',
    broken: 'Broken',
};

/** Broken (its flow went missing) wins over paused: it is what the operator has to fix first. */
export function bindingStatus(binding: ChatBinding): ChatBindingStatus {
    if (binding.broken_reason) return 'broken';
    return binding.is_active ? 'live' : 'paused';
}
