import { HttpErrorResponse } from '@angular/common/http';
import { inject, Injectable, signal } from '@angular/core';
import { ConfirmationDialogService } from '@shared/components';
import { extractHttpErrorMessage } from '@shared/utils';
import { filter, Observable, Subject, switchMap } from 'rxjs';

import { ToastService } from '../../../services/notifications';
import { ChatConversation, ChatErrorBody } from '../models/chat.model';
import { ChatApiService } from './chat-api.service';

/**
 * Taking over a conversation and releasing it to the bot, wherever they are asked for (a row, the thread header, the
 * composer). One at a time across all of them; failures are toasted.
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

    /** Makes the conversation the current operator's; held by another operator, it asks before taking it from them. */
    takeOver(conversation: ChatConversation): void {
        this.run(
            () => this.chatApi.claim(conversation.id),
            (error) => {
                if ((error.error as ChatErrorBody | null)?.code !== 'claimed_by_other') return null;
                return this.confirmationDialogService
                    .confirm({
                        title: 'Take over conversation',
                        message: 'Another operator holds this conversation. Take it over?',
                        confirmText: 'Take over',
                        cancelText: 'Cancel',
                        type: 'danger',
                    })
                    .pipe(
                        filter((confirmed) => confirmed === true),
                        switchMap(() => this.chatApi.claim(conversation.id, true))
                    );
            }
        );
    }

    /** Hands the conversation back to the bot. */
    release(conversation: ChatConversation): void {
        this.run(() => this.chatApi.release(conversation.id));
    }

    /**
     * Builds and sends the request only when no other action runs. `recover` may turn an error into a follow-up request
     * (the forced take-over); a follow-up that completes without emitting (the operator cancelled the confirm) just ends
     * the action.
     */
    private run(
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
                if (followUp) this.run(() => followUp);
                else this.toastService.error(extractHttpErrorMessage(error));
            },
            complete: () => this.isPendingSignal.set(false),
        });
    }
}
