import { HttpErrorResponse } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { ConfirmationDialogService } from '@shared/components';
import { copyWithFeedback, escapeHtml, extractHttpErrorMessage } from '@shared/utils';
import { catchError, EMPTY, filter, firstValueFrom, map, Observable, of, switchMap } from 'rxjs';

import { ToastService } from '../../../services/notifications';
import { ChatBinding, ChatErrorBody } from '../models/chat.model';
import { ChatApiService } from './chat-api.service';

const CONTRACT_REFUSALS = new Set(['contract_failed', 'unknown_flow']);

/**
 * The binding actions offered on the bindings list and in a binding's workspace, with their confirmations and
 * error toasts. Each returns an observable that emits `true` once the server changed the binding (the caller then
 * reloads it) and completes without emitting when the user cancelled or the request failed.
 */
@Injectable({ providedIn: 'root' })
export class ChatBindingActionsService {
    private readonly chatApi = inject(ChatApiService);
    private readonly confirmationDialogService = inject(ConfirmationDialogService);
    private readonly toastService = inject(ToastService);

    pause(binding: ChatBinding): Observable<boolean> {
        return this.confirmationDialogService
            .confirm({
                title: 'Pause the binding?',
                message: `The widget for <strong>${escapeHtml(binding.name)}</strong> stops answering. Test conversations keep working.`,
                confirmText: 'Pause',
                cancelText: 'Cancel',
                type: 'danger',
            })
            .pipe(
                filter((confirmed) => confirmed === true),
                switchMap(() => this.chatApi.pauseBinding(binding.id)),
                map(() => true),
                catchError((error: HttpErrorResponse) => this.fail(error))
            );
    }

    /**
     * Resume re-checks the contract. A contract refusal (`contract_failed`, `unknown_flow`) stored the fresh errors
     * or broken reason, so it counts as a change; any other failure changed nothing.
     */
    resume(binding: ChatBinding): Observable<boolean> {
        return this.chatApi.resumeBinding(binding.id).pipe(
            map(() => true),
            catchError((error: HttpErrorResponse) => {
                this.toastService.error(extractHttpErrorMessage(error));
                const code = (error.error as ChatErrorBody | null)?.code;
                return code && CONTRACT_REFUSALS.has(code) ? of(true) : EMPTY;
            })
        );
    }

    delete(binding: ChatBinding): Observable<boolean> {
        return this.confirmationDialogService.confirmDelete(binding.name).pipe(
            filter((confirmed) => confirmed === true),
            switchMap(() => this.chatApi.deleteBinding(binding.id)),
            map(() => true),
            catchError((error: HttpErrorResponse) => this.fail(error))
        );
    }

    copySnippet(binding: ChatBinding): void {
        // The promise is handed over inside the click, so Safari still allows the clipboard write.
        void copyWithFeedback(
            firstValueFrom(this.chatApi.getSnippet(binding.id)).then(({ snippet }) => snippet),
            this.toastService
        );
    }

    private fail(error: HttpErrorResponse): Observable<never> {
        this.toastService.error(extractHttpErrorMessage(error));
        return EMPTY;
    }
}
