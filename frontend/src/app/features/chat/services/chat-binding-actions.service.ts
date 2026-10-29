import { Dialog, DialogConfig } from '@angular/cdk/dialog';
import { createGlobalPositionStrategy } from '@angular/cdk/overlay';
import { HttpErrorResponse } from '@angular/common/http';
import { inject, Injectable, Injector } from '@angular/core';
import { ConfirmationDialogService } from '@shared/components';
import { copyWithFeedback, escapeHtml, extractHttpErrorMessage } from '@shared/utils';
import { catchError, EMPTY, filter, firstValueFrom, map, Observable, of, switchMap } from 'rxjs';

import { PhoneLayoutService } from '../../../core/services/phone-layout.service';
import { ToastService } from '../../../services/notifications';
import {
    ChatBindingsDialogComponent,
    ChatBindingsDialogData,
} from '../components/chat-bindings-dialog/chat-bindings-dialog.component';
import {
    MY_DESK_ALIAS_TITLE_ID,
    MyDeskAliasDialogComponent,
    MyDeskAliasDialogData,
} from '../components/my-desk-alias-dialog/my-desk-alias-dialog.component';
import { ChatBinding, ChatErrorBody, ChatMyAliasResult } from '../models/chat.model';
import { ChatApiService } from './chat-api.service';

const CONTRACT_REFUSALS = new Set(['contract_failed', 'unknown_flow']);

type DialogSize = Pick<DialogConfig, 'width' | 'maxWidth' | 'positionStrategy'>;

/**
 * The desk actions offered by the desk rail and a desk's header, with their confirmations and error toasts. Pause,
 * resume and delete return an observable that emits `true` once the server changed the desk (the caller then reloads
 * it) and completes without emitting when the user cancelled or the request failed. The dialog actions emit once,
 * when the dialog closes.
 */
@Injectable({ providedIn: 'root' })
export class ChatBindingActionsService {
    private readonly chatApi = inject(ChatApiService);
    private readonly confirmationDialogService = inject(ConfirmationDialogService);
    private readonly toastService = inject(ToastService);
    private readonly dialog = inject(Dialog);
    private readonly isPhone = inject(PhoneLayoutService).isPhone;
    private readonly injector = inject(Injector);

    /**
     * Opens the dialog that creates a desk. Emits once when it closes: the created desk, or null when none was
     * created. Reload on every close all the same: Escape or a backdrop click after a create that showed an identity
     * secret closes without a result.
     */
    create(): Observable<ChatBinding | null> {
        return this.openDialog(null);
    }

    /** Opens a desk's settings. Emits once when the dialog closes; the caller reloads, as edits may have been saved. */
    openSettings(binding: ChatBinding): Observable<void> {
        return this.openDialog(binding).pipe(map(() => undefined));
    }

    /**
     * Opens the name the user goes by on a desk. The dialog stores a saved name itself; this emits once when it
     * closes: the server's answer, or null when nothing was saved.
     */
    editMyAlias(binding: ChatBinding): Observable<ChatMyAliasResult | null> {
        return this.dialog
            .open<ChatMyAliasResult, MyDeskAliasDialogData>(MyDeskAliasDialogComponent, {
                ...this.dialogSize('480px'),
                data: { binding },
                ariaLabelledBy: MY_DESK_ALIAS_TITLE_ID,
            })
            .closed.pipe(map((saved) => saved ?? null));
    }

    pause(binding: ChatBinding): Observable<boolean> {
        return this.confirmationDialogService
            .confirm({
                title: 'Pause the desk?',
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

    private openDialog(binding: ChatBinding | null): Observable<ChatBinding | null> {
        return this.dialog
            .open<
                ChatBinding,
                ChatBindingsDialogData
            >(ChatBindingsDialogComponent, { ...this.dialogSize('720px'), data: { binding } })
            .closed.pipe(map((saved) => saved ?? null));
    }

    /**
     * A dialog's width; on phones a sheet instead: the screen's whole width, rising from its bottom edge, the dialog
     * scrolling inside (its own styles cap its height). Decided as it opens.
     */
    private dialogSize(width: string): DialogSize {
        if (!this.isPhone()) return { width };
        return {
            width: '100vw',
            maxWidth: '100vw',
            positionStrategy: createGlobalPositionStrategy(this.injector).bottom('0').centerHorizontally(),
        };
    }

    private fail(error: HttpErrorResponse): Observable<never> {
        this.toastService.error(extractHttpErrorMessage(error));
        return EMPTY;
    }
}
