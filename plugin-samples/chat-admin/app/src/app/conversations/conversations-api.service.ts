import { inject, Injectable } from '@angular/core';

import { isNotFound } from '../core/describe-error';
import { PluginBridgeService } from '../core/plugin-bridge.service';
import {
    CHAT_FLOW_ALIAS,
    type Conversation,
    type ConversationListQuery,
    type ConversationPage,
    CONVERSATIONS_PAGE_SIZE,
    CONVERSATIONS_TABLE_ALIAS,
    parseConversation,
    summarizePreview,
    validTimestamp,
} from './conversation.model';

/** A stored value that is not a conversation record, shown as raw JSON. */
export interface UnreadableConversation {
    key: string;
    value: unknown;
}

export type ConversationLookup =
    | { kind: 'found'; conversation: Conversation }
    | { kind: 'unreadable'; entry: UnreadableConversation }
    | { kind: 'missing' };

/**
 * Bridge calls for conversations; no state. Reads the plugin's key-value table and asks the
 * plugin's chat flow. The flow writes the transcript itself, so asking sends only the id and the
 * question (a whole transcript would soon exceed the bridge's 64 KB request limit).
 */
@Injectable({ providedIn: 'root' })
export class ConversationsApiService {
    private readonly bridgeService = inject(PluginBridgeService);

    async list(query: ConversationListQuery, signal?: AbortSignal): Promise<ConversationPage> {
        const result = await this.bridgeService.bridge.call(
            'kv.list',
            {
                table: CONVERSATIONS_TABLE_ALIAS,
                ordering: query.ordering,
                limit: CONVERSATIONS_PAGE_SIZE,
                offset: (query.page - 1) * CONVERSATIONS_PAGE_SIZE,
                ...(query.search ? { search: query.search } : {}),
            },
            signal ? { signal } : {}
        );
        return {
            count: result.count,
            items: result.items.map((item) => ({
                key: item.key,
                ...summarizePreview(item.value_preview),
                updatedAt: validTimestamp(item.updated_at),
            })),
        };
    }

    async get(key: string): Promise<ConversationLookup> {
        try {
            const entry = await this.bridgeService.bridge.kv.get(CONVERSATIONS_TABLE_ALIAS, key);
            const conversation = parseConversation(entry.key, entry.value);
            return conversation
                ? { kind: 'found', conversation }
                : { kind: 'unreadable', entry: { key: entry.key, value: entry.value } };
        } catch (error) {
            if (isNotFound(error)) return { kind: 'missing' };
            throw error;
        }
    }

    /** Runs the chat flow for one turn and resolves with the assistant's answer. */
    async ask(conversationId: string, question: string): Promise<string> {
        const output = await this.bridgeService.bridge.flows.runAndWait<unknown>(CHAT_FLOW_ALIAS, {
            conversation_id: conversationId,
            question,
        });
        const answer =
            typeof output === 'object' && output !== null ? (output as Record<string, unknown>)['answer'] : null;
        return typeof answer === 'string' && answer.trim() !== ''
            ? answer.trim()
            : 'The assistant did not return an answer.';
    }
}
