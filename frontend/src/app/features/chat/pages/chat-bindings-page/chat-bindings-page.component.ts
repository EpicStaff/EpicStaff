import { Dialog } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import {
    ButtonComponent,
    FetchErrorStateComponent,
    LoadingSpinnerComponent,
    SearchComponent,
} from '@shared/components';
import { HasPermissionDirective, HideInlineSubtitleOnOverflowDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import { extractHttpErrorMessage } from '@shared/utils';
import { catchError, EMPTY, filter, map, Observable } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { FlowsApiService } from '../../../flows/services/flows-api.service';
import {
    ChatBindingCardAction,
    ChatBindingCardComponent,
} from '../../components/chat-binding-card/chat-binding-card.component';
import {
    ChatBindingsDialogComponent,
    ChatBindingsDialogData,
} from '../../components/chat-bindings-dialog/chat-bindings-dialog.component';
import { ChatBinding } from '../../models/chat.model';
import { ChatApiService } from '../../services/chat-api.service';
import { ChatBindingActionsService } from '../../services/chat-binding-actions.service';
import { ChatInboxStreamService } from '../../services/chat-inbox-stream.service';

/** Every chat binding of the org as a card, plus the inbox across all of them. */
@Component({
    selector: 'app-chat-bindings-page',
    imports: [
        RouterLink,
        ButtonComponent,
        ChatBindingCardComponent,
        FetchErrorStateComponent,
        HasPermissionDirective,
        HideInlineSubtitleOnOverflowDirective,
        LoadingSpinnerComponent,
        SearchComponent,
    ],
    templateUrl: './chat-bindings-page.component.html',
    styleUrls: ['./chat-bindings-page.component.scss'],
})
export class ChatBindingsPageComponent {
    readonly bindings = signal<ChatBinding[]>([]);
    readonly isLoaded = signal(false);
    // Only a failed first load: it must not look like an org without bindings and invite duplicate creates.
    readonly loadFailed = signal(false);
    readonly searchTerm = signal('');
    // Flow names for the cards; a failed load only leaves them as "Flow #id".
    readonly flowNames = toSignal(
        inject(FlowsApiService)
            .getGraphsLight()
            .pipe(
                map((graphs) => new Map(graphs.map((graph) => [graph.id, graph.name]))),
                catchError(() => EMPTY)
            ),
        { initialValue: new Map<number, string>() }
    );
    readonly visibleBindings = computed(() => {
        const term = this.searchTerm().trim().toLowerCase();
        const flowNames = this.flowNames();
        return this.bindings()
            .filter(
                (binding) =>
                    !term ||
                    binding.name.toLowerCase().includes(term) ||
                    (flowNames.get(binding.graph_id) ?? '').toLowerCase().includes(term)
            )
            .sort((first, second) => first.name.localeCompare(second.name));
    });
    protected readonly waitingByBinding = inject(ChatInboxStreamService).awaitingByBinding;
    protected readonly totalWaiting = inject(ChatInboxStreamService).awaitingCount;

    protected readonly ActionCode = ActionCode;
    protected readonly ResourceCode = ResourceCode;

    private readonly chatApi = inject(ChatApiService);
    private readonly bindingActions = inject(ChatBindingActionsService);
    private readonly toastService = inject(ToastService);
    private readonly dialog = inject(Dialog);
    private readonly destroyRef = inject(DestroyRef);

    constructor() {
        this.loadBindings();
    }

    retryLoad(): void {
        this.isLoaded.set(false);
        this.loadFailed.set(false);
        this.loadBindings();
    }

    createBinding(): void {
        this.openDialog(null);
    }

    onCardAction(binding: ChatBinding, action: ChatBindingCardAction): void {
        switch (action) {
            case 'settings':
                this.openDialog(binding);
                return;
            case 'snippet':
                this.bindingActions.copySnippet(binding);
                return;
            case 'pause':
                this.reloadAfter(this.bindingActions.pause(binding));
                return;
            case 'resume':
                this.reloadAfter(this.bindingActions.resume(binding));
                return;
            case 'delete':
                this.reloadAfter(this.bindingActions.delete(binding));
                return;
        }
    }

    private openDialog(binding: ChatBinding | null): void {
        this.dialog
            .open<unknown, ChatBindingsDialogData>(ChatBindingsDialogComponent, { width: '720px', data: { binding } })
            .closed.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.loadBindings());
    }

    private reloadAfter(action$: Observable<boolean>): void {
        action$.pipe(filter(Boolean), takeUntilDestroyed(this.destroyRef)).subscribe(() => this.loadBindings());
    }

    private loadBindings(): void {
        this.chatApi
            .getBindings()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (bindings) => {
                    this.bindings.set(bindings);
                    this.isLoaded.set(true);
                },
                error: (error: HttpErrorResponse) => {
                    // A failed reload keeps the cards already shown and only says so.
                    if (this.isLoaded()) this.toastService.error(extractHttpErrorMessage(error));
                    else this.loadFailed.set(true);
                },
            });
    }
}
