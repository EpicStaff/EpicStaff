import { HttpErrorResponse } from '@angular/common/http';
import { inject, Injectable, signal } from '@angular/core';
import { ConfirmationDialogService } from '@shared/components';
import { extractHttpErrorMessage } from '@shared/utils';
import { filter, Observable, Subject, switchMap } from 'rxjs';

import { ProfileService } from '../../../services/auth/profile.service';
import { ToastService } from '../../../services/notifications';
import { ChatConversation, ChatErrorBody } from '../models/chat.model';
import { isConversationClosed } from '../utils/conversation-close.util';
import { ChatApiService } from './chat-api.service';

// Claim, release and reply on a closed conversation answer 409 `conversation_closed`: the row shown was stale (the
// stream missed the close), so it is fetched again too.
const CONVERSATION_CLOSED_MESSAGE = 'This conversation is closed.';

/** The confirm that asks before an action takes a conversation from the operator who holds it. */
interface HolderConfirm {
    title: string;
    message: string;
    confirmText: string;
}

/**
 * Taking over a conversation, releasing it to the bot and closing it, wherever they are asked for (a row, the thread
 * header, its ⋯ menu, the composer). One at a time across all of them; failures are toasted.
 */
@Injectable({ providedIn: 'root' })
export class ChatConversationActionsService {
    private readonly isPendingSignal = signal(false);
    private readonly changedSubject = new Subject<ChatConversation>();

    readonly isPending = this.isPendingSignal.asReadonly();
    /**
     * Every conversation an action changed, as the server returned it. The list and the thread apply it at once
     * rather than waiting for its stream event.
     */
    readonly changed$: Observable<ChatConversation> = this.changedSubject.asObservable();

    private readonly chatApi = inject(ChatApiService);
    private readonly confirmationDialogService = inject(ConfirmationDialogService);
    private readonly toastService = inject(ToastService);
    private readonly profileService = inject(ProfileService);

    /** Makes the conversation the current operator's; held by another operator, it asks before taking it from them. */
    takeOver(conversation: ChatConversation): void {
        this.run(
            conversation.id,
            () => this.chatApi.claim(conversation.id),
            (error) =>
                this.confirmOverHolder(
                    error,
                    {
                        title: 'Take over conversation',
                        message: 'Another operator holds this conversation. Take it over?',
                        confirmText: 'Take over',
                    },
                    () => this.chatApi.claim(conversation.id, true)
                )
        );
    }

    /** Hands the conversation back to the bot; it stays open (Ongoing's Done). */
    release(conversation: ChatConversation): void {
        this.run(conversation.id, () => this.chatApi.release(conversation.id));
    }

    /**
     * Support's Resolve: closes the conversation without asking, as finishing a case is routine. Held by another
     * operator, it asks before closing it on them.
     */
    resolve(conversation: ChatConversation): void {
        this.run(
            conversation.id,
            () => this.chatApi.close(conversation.id),
            (error) =>
                this.confirmOverHolder(
                    error,
                    {
                        title: 'Resolve conversation',
                        message: 'Another operator holds this conversation. Resolve it anyway?',
                        confirmText: 'Resolve',
                    },
                    () => this.chatApi.close(conversation.id, true)
                )
        );
    }

    /**
     * Ongoing's Close conversation, for the rare case (spam, a fresh start the visitor asked for): it ends a thread that
     * would otherwise go on, so it always asks first. The confirm names another operator's hold when the row shows one
     * and then closes over it; a hold that only the server knows of asks once more.
     */
    closeConversation(conversation: ChatConversation): void {
        if (this.isPendingSignal()) return;
        const isHeldByOther = this.isHeldByOther(conversation);
        const ending = "The visitor's next message starts a new conversation. A closed one cannot be reopened.";
        this.confirmationDialogService
            .confirm({
                title: 'Close conversation',
                message: isHeldByOther ? `Another operator holds this conversation. ${ending}` : ending,
                confirmText: 'Close conversation',
                cancelText: 'Cancel',
                type: 'danger',
            })
            .pipe(filter((confirmed) => confirmed === true))
            .subscribe(() =>
                this.run(
                    conversation.id,
                    () => this.chatApi.close(conversation.id, isHeldByOther),
                    (error) =>
                        this.confirmOverHolder(
                            error,
                            {
                                title: 'Close conversation',
                                message: 'Another operator holds this conversation. Close it anyway?',
                                confirmText: 'Close conversation',
                            },
                            () => this.chatApi.close(conversation.id, true)
                        )
                )
            );
    }

    /**
     * Fetches a conversation the server says is not as shown (a 409 `conversation_closed`) and publishes it, so the
     * list and the thread follow the server. A failure keeps what is shown: the stream's next event or `ready` fixes it.
     */
    refresh(conversationId: string): void {
        this.chatApi.getConversation(conversationId).subscribe({
            next: (conversation) => this.changedSubject.next(conversation),
            error: () => undefined,
        });
    }

    /**
     * Builds and sends the request only when no other action runs. `recover` may turn an error into a follow-up request
     * (a forced take-over or close); a follow-up that completes without emitting (the operator cancelled the confirm)
     * just ends the action.
     */
    private run(
        conversationId: string,
        request: () => Observable<ChatConversation>,
        recover?: (error: HttpErrorResponse) => Observable<ChatConversation> | null
    ): void {
        if (this.isPendingSignal()) return;
        this.isPendingSignal.set(true);
        request().subscribe({
            next: (conversation) => this.changedSubject.next(conversation),
            error: (error: HttpErrorResponse) => {
                this.isPendingSignal.set(false);
                const followUp = recover?.(error) ?? null;
                if (followUp) {
                    this.run(conversationId, () => followUp);
                    return;
                }
                this.toastService.error(failureMessage(error));
                if (isConversationClosed(error)) this.refresh(conversationId);
            },
            complete: () => this.isPendingSignal.set(false),
        });
    }

    /** A 409 `claimed_by_other` becomes `forced` once the operator confirms; any other error is not recovered. */
    private confirmOverHolder(
        error: HttpErrorResponse,
        confirm: HolderConfirm,
        forced: () => Observable<ChatConversation>
    ): Observable<ChatConversation> | null {
        if (errorCode(error) !== 'claimed_by_other') return null;
        return this.confirmationDialogService.confirm({ ...confirm, cancelText: 'Cancel', type: 'danger' }).pipe(
            filter((confirmed) => confirmed === true),
            switchMap(forced)
        );
    }

    private isHeldByOther(conversation: ChatConversation): boolean {
        const holderId = conversation.assigned_operator_id;
        return holderId !== null && holderId !== this.profileService.currentUserSignal()?.id;
    }
}

function errorCode(error: HttpErrorResponse): string | null {
    return (error.error as ChatErrorBody | null)?.code ?? null;
}

function failureMessage(error: HttpErrorResponse): string {
    return isConversationClosed(error) ? CONVERSATION_CLOSED_MESSAGE : extractHttpErrorMessage(error);
}
