import { computed, inject, Injectable, signal } from '@angular/core';

import { ConversationsApiService } from '../conversations/conversations-api.service';
import { type ConversationMessage, isTableKey, newConversationId } from '../conversations/conversation.model';
import { describeError } from '../core/describe-error';

type ChatStatus = 'idle' | 'loading' | 'asking';

/**
 * The conversation open in the Chat tab. Lives at the root so it survives switching tabs and the
 * `/chat` → `/chat/:id` navigation after the first question (two routes, two component instances).
 */
@Injectable({ providedIn: 'root' })
export class ChatStore {
    private readonly conversationIdSignal = signal(newConversationId());
    private readonly messagesSignal = signal<readonly ConversationMessage[]>([]);
    private readonly statusSignal = signal<ChatStatus>('idle');
    private readonly errorSignal = signal<string | null>(null);
    private readonly savedSignal = signal(false);

    readonly conversationId = this.conversationIdSignal.asReadonly();
    readonly messages = this.messagesSignal.asReadonly();
    readonly error = this.errorSignal.asReadonly();
    readonly loading = computed(() => this.statusSignal() === 'loading');
    readonly asking = computed(() => this.statusSignal() === 'asking');
    /** True once the conversation exists in the table (loaded, or the flow answered at least once). */
    readonly saved = this.savedSignal.asReadonly();
    readonly isEmpty = computed(() => this.messagesSignal().length === 0 && this.statusSignal() === 'idle');
    /** False for a `/chat/<id>` whose id the key-value table can't hold: the flow could not save it. */
    readonly acceptsQuestions = computed(() => isTableKey(this.conversationIdSignal()));
    readonly title = computed(() => {
        const question = this.messagesSignal().find((message) => message.role === 'user')?.content;
        if (!question) return 'New conversation';
        return question.length > 80 ? `${question.slice(0, 79)}…` : question;
    });

    private readonly api = inject(ConversationsApiService);
    /** Bumped whenever another conversation opens, so late answers for the old one are dropped. */
    private generation = 0;

    /** `/chat`: a new conversation, unless the current one is still empty. */
    startNew(): void {
        if (this.isEmpty() && !this.savedSignal()) return;
        this.reset(newConversationId());
    }

    /** `/chat/:id`: continues a stored conversation, loading its transcript once. */
    open(id: string): void {
        if (id === this.conversationIdSignal()) return;
        const generation = this.reset(id);
        if (!isTableKey(id)) {
            this.errorSignal.set(`"${id.slice(0, 80)}" is not a conversation id.`);
            return;
        }
        this.statusSignal.set('loading');
        this.api.get(id).then(
            (lookup) => {
                if (generation !== this.generation) return;
                this.statusSignal.set('idle');
                if (lookup.kind === 'found') {
                    this.messagesSignal.set(lookup.conversation.messages);
                    this.savedSignal.set(true);
                } else if (lookup.kind === 'unreadable') {
                    this.errorSignal.set('This entry is not a conversation record; it cannot be continued here.');
                }
            },
            (error: unknown) => {
                if (generation !== this.generation) return;
                this.statusSignal.set('idle');
                this.errorSignal.set(describeError(error));
            }
        );
    }

    /** Asks the flow; the flow appends the turn to the stored conversation itself. */
    async ask(question: string): Promise<void> {
        if (this.statusSignal() !== 'idle' || !this.acceptsQuestions()) return;
        const generation = this.generation;
        const conversationId = this.conversationIdSignal();
        this.errorSignal.set(null);
        this.append({ role: 'user', content: question, at: new Date().toISOString() });
        this.statusSignal.set('asking');
        try {
            const answer = await this.api.ask(conversationId, question);
            if (generation !== this.generation) return;
            this.append({ role: 'assistant', content: answer, at: new Date().toISOString() });
            this.savedSignal.set(true);
        } catch (error) {
            if (generation !== this.generation) return;
            this.errorSignal.set(describeError(error));
        } finally {
            if (generation === this.generation) this.statusSignal.set('idle');
        }
    }

    private reset(conversationId: string): number {
        this.generation++;
        this.conversationIdSignal.set(conversationId);
        this.messagesSignal.set([]);
        this.statusSignal.set('idle');
        this.errorSignal.set(null);
        this.savedSignal.set(false);
        return this.generation;
    }

    private append(message: ConversationMessage): void {
        this.messagesSignal.update((messages) => [...messages, message]);
    }
}
