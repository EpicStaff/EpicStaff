import { HttpErrorResponse } from '@angular/common/http';
import { DestroyRef, effect, inject, Injectable, untracked } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { extractHttpErrorMessage } from '@shared/utils';
import { merge, Subscription } from 'rxjs';

import { ToastService } from '../../../services/notifications';
import { ChatConversation } from '../models/chat.model';
import { ChatApiService } from './chat-api.service';
import { ChatConversationActionsService } from './chat-conversation-actions.service';
import { ChatInboxStreamService } from './chat-inbox-stream.service';
import { OpenConversationService } from './open-conversation.service';

/**
 * Keeps the open conversation's row as the server has it, for the chat page; `OpenConversationService` holds that row
 * and the URL, and stays free of requests. The row comes from:
 * - the stream and this user's actions, live;
 * - the conversations column, or the server by id when the column cannot list it (`resolve`);
 * - the server again after every stream `ready` but the first: the stream may have missed changes while it was down.
 *
 * Only the rows of the page's desk are taken (`setScope`). Provided by the chat page, next to `OpenConversationService`.
 */
@Injectable()
export class OpenConversationSyncService {
    /**
     * On every `ready` but the first: the open conversation is fetched again (closed meanwhile, the column's reload may
     * list it nowhere open), and a lookup that failed for no reason of its own may try again.
     */
    private readonly refreshOnReady = effect(() => {
        const epoch = this.chatInboxStream.readyEpoch();
        untracked(() => {
            const isFirst = this.readyEpochSeen === null;
            this.readyEpochSeen = epoch;
            if (isFirst) return;
            if (!this.lookupRequest || this.lookupRequest.closed) this.lookupId = null;
            const id = this.openConversation.row()?.id;
            if (id) this.refreshOpen(id);
        });
    });

    private readonly openConversation = inject(OpenConversationService);
    private readonly chatApi = inject(ChatApiService);
    private readonly chatInboxStream = inject(ChatInboxStreamService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);
    // The desk the page shows; null on All desks.
    private bindingId: string | null = null;
    // The id `resolve` asked the server for: while its answer is on the way, and after a failure that said nothing
    // about the conversation, until the next `ready`.
    private lookupId: string | null = null;
    private lookupRequest: Subscription | null = null;
    // The `ready` seen last; null before the first.
    private readyEpochSeen: number | null = null;
    // The open conversation fetched again after a `ready`.
    private refreshRequest: Subscription | null = null;
    // Counts the open conversation's rows that arrived live: a refetch older than one is dropped.
    private liveRowCount = 0;

    constructor() {
        merge(this.chatInboxStream.conversationUpdated$, inject(ChatConversationActionsService).changed$)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((row) => {
                if (!this.isOfThisDesk(row)) return;
                if (row.id === this.openConversation.id()) this.liveRowCount++;
                this.openConversation.remember(row);
            });
    }

    /**
     * The desk the page shows (null: All desks). The stream and the actions report every desk's rows, so an id of
     * another desk's conversation in the URL (a hand-made link) must not open here. Moving to another desk drops a
     * refetch still on its way.
     */
    setScope(bindingId: string | null): void {
        if (bindingId !== this.bindingId) this.cancelRefresh();
        this.bindingId = bindingId;
    }

    /** Drops a refetch still on its way: the page has moved on (another org, a logout). */
    cancelRefresh(): void {
        this.refreshRequest?.unsubscribe();
        this.refreshRequest = null;
    }

    /**
     * What the conversations column said about the open id it was asked for: its row, which opens if it is this desk's;
     * or `missing`, as the column lists only the first pages of each section (an older closed conversation is past
     * them). A missing id is asked for once: it opens if it is this desk's. Another desk's, or a 404, leaves the URL
     * with a message. Any other failure says nothing about the conversation (a network blip on a phone's reload): the
     * link stays, the failure is toasted, and the next `ready` lets it ask again.
     */
    resolve(id: string, found: ChatConversation | 'missing'): void {
        if (found !== 'missing') {
            if (this.isOfThisDesk(found)) this.openConversation.remember(found);
            else this.dropMissing();
            return;
        }
        if (this.lookupId === id) return;
        this.lookupId = id;
        const isStillWanted = (): boolean => this.openConversation.id() === id && !this.openConversation.row();
        this.lookupRequest = this.chatApi
            .getConversation(id)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (row) => {
                    this.lookupId = null;
                    if (!isStillWanted()) return;
                    if (this.isOfThisDesk(row)) this.openConversation.remember(row);
                    else this.dropMissing();
                },
                error: (error: HttpErrorResponse) => {
                    if (!isStillWanted()) {
                        this.lookupId = null;
                    } else if (error.status === 404) {
                        this.lookupId = null;
                        this.dropMissing();
                    } else {
                        this.toastService.error(extractHttpErrorMessage(error));
                    }
                },
            });
    }

    private isOfThisDesk(row: ChatConversation): boolean {
        return !this.bindingId || row.binding_id === this.bindingId;
    }

    private dropMissing(): void {
        this.toastService.error("Couldn't open that conversation.");
        this.openConversation.drop();
    }

    /** Fetches the open conversation again; kept only while it is this desk's and nothing newer came live. */
    private refreshOpen(id: string): void {
        this.cancelRefresh();
        const liveRowCount = this.liveRowCount;
        this.refreshRequest = this.chatApi
            .getConversation(id)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (row) => {
                    if (liveRowCount !== this.liveRowCount || !this.isOfThisDesk(row)) return;
                    this.openConversation.remember(row);
                },
                // The thread keeps the row it holds; the next `ready` tries again.
                error: () => undefined,
            });
    }
}
