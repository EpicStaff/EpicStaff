import { DestroyRef, inject, Injectable, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { ChatApiService } from './chat-api.service';
import { OpenConversationService } from './open-conversation.service';

const TOKEN_ERROR = "Couldn't get a visitor token. Select the conversation again to retry.";

/**
 * The visitor tokens of the test conversations the chat page writes to as their visitor. The server issues one only
 * on create (Test seeds it here) or on request (a test started elsewhere, or before a reload). Kept for the page's
 * life: a token stays valid for its conversation, so returning to one mints nothing new. Provided by the chat page,
 * beside the `OpenConversationService` it reads.
 */
@Injectable()
export class ChatVisitorTokensStore {
    private readonly tokensSignal = signal<Record<string, string>>({});
    // The test conversation a token is being fetched for, and the ones whose fetch failed (until reselected).
    private readonly pendingForSignal = signal<string | null>(null);
    private readonly errorsSignal = signal<Record<string, string>>({});

    readonly tokens = this.tokensSignal.asReadonly();
    readonly pendingFor = this.pendingForSignal.asReadonly();
    readonly errors = this.errorsSignal.asReadonly();

    private readonly chatApi = inject(ChatApiService);
    private readonly openConversation = inject(OpenConversationService);
    private readonly destroyRef = inject(DestroyRef);

    remember(conversationId: string, token: string): void {
        this.tokensSignal.update((tokens) => ({ ...tokens, [conversationId]: token }));
    }

    /** Forgets a failed fetch, so the next `ensure` tries again; says whether there was one. */
    clearError(conversationId: string): boolean {
        if (!this.errorsSignal()[conversationId]) return false;
        this.errorsSignal.update((errors) => {
            const rest = { ...errors };
            delete rest[conversationId];
            return rest;
        });
        return true;
    }

    /** Fetches a token for the conversation unless it has one, one is on its way, or the last fetch failed. */
    ensure(conversationId: string): void {
        if (this.tokensSignal()[conversationId] || this.errorsSignal()[conversationId]) return;
        if (this.pendingForSignal() === conversationId) return;
        this.pendingForSignal.set(conversationId);
        this.chatApi
            .issueVisitorToken(conversationId)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                // Kept even after the operator moved on; the composer only shows the open conversation's token.
                next: ({ visitor_token }) => this.remember(conversationId, visitor_token),
                error: () => {
                    if (this.pendingForSignal() === conversationId) this.pendingForSignal.set(null);
                    if (this.openConversation.id() !== conversationId) return;
                    this.errorsSignal.update((errors) => ({ ...errors, [conversationId]: TOKEN_ERROR }));
                },
                complete: () => {
                    if (this.pendingForSignal() === conversationId) this.pendingForSignal.set(null);
                },
            });
    }
}
