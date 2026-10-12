import { ChatBinding, ChatBindingInput, ChatBindingPatch } from '../models/chat.model';

/** The server applies `exclude_unset`: send only what changed. Budgets are always finite numbers (decision 13). */
export function bindingPatch(original: ChatBinding, values: ChatBindingInput): ChatBindingPatch {
    const patch: Record<string, unknown> = {};
    for (const key of Object.keys(values) as (keyof ChatBindingInput)[]) {
        if (JSON.stringify(original[key]) !== JSON.stringify(values[key])) patch[key] = values[key];
    }
    return patch as ChatBindingPatch;
}
