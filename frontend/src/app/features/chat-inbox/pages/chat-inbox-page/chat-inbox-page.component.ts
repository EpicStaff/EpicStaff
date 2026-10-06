import { Dialog } from '@angular/cdk/dialog';
import { DatePipe, DecimalPipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, DestroyRef, effect, inject, signal } from '@angular/core';
import { takeUntilDestroyed, toObservable, toSignal } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ButtonComponent, CustomInputComponent, SelectComponent, SelectItem } from '@shared/components';
import { extractHttpErrorMessage } from '@shared/utils';
import { catchError, EMPTY, Observable, of, switchMap, timer } from 'rxjs';

import { ProfileService } from '../../../../services/auth/profile.service';
import { ToastService } from '../../../../services/notifications';
import { ChatBindingsDialogComponent } from '../../components/chat-bindings-dialog/chat-bindings-dialog.component';
import { SimulateEndUserPanelComponent } from '../../components/simulate-end-user-panel/simulate-end-user-panel.component';
import { ChatBinding, ChatConversation, ChatConversationMode, ChatMessage } from '../../models/chat.model';
import { ChatApiService } from '../../services/chat-api.service';

// PROTO: polling; the real version pushes conversation and message changes over SSE.
const POLL_INTERVAL_MS = 2000;
const ALL_BINDINGS = 0;

const MODE_LABELS: Record<ChatConversationMode, string> = {
    bot: 'Bot',
    awaiting_human: 'Awaiting human',
    human: 'Human',
    closed: 'Closed',
};

// PROTO: page-held state with no storage service; the real version splits a chat-inbox storage service out.
@Component({
    selector: 'app-chat-inbox-page',
    imports: [
        DatePipe,
        DecimalPipe,
        ReactiveFormsModule,
        RouterLink,
        ButtonComponent,
        CustomInputComponent,
        SelectComponent,
        SimulateEndUserPanelComponent,
    ],
    templateUrl: './chat-inbox-page.component.html',
    styleUrls: ['./chat-inbox-page.component.scss'],
})
export class ChatInboxPageComponent {
    readonly bindings = signal<ChatBinding[]>([]);
    readonly bindingFilter = signal<number>(ALL_BINDINGS);
    readonly selectedConversationId = signal<number | null>(null);
    readonly isActionPending = signal(false);
    // Bumped after every change made from this page, so the polls refetch at once instead of within 2 s.
    readonly refreshTick = signal(0);

    readonly bindingFilterItems = computed((): SelectItem<number>[] => [
        { name: 'All bindings', value: ALL_BINDINGS },
        ...this.bindings().map((binding) => ({ name: binding.name, value: binding.id })),
    ]);
    readonly conversations = toSignal(
        toObservable(computed(() => ({ binding: this.bindingFilter(), tick: this.refreshTick() }))).pipe(
            switchMap(({ binding }) =>
                this.poll(() => this.chatApi.getConversations(binding === ALL_BINDINGS ? null : binding))
            )
        ),
        { initialValue: [] }
    );
    readonly messages = toSignal(
        toObservable(computed(() => ({ id: this.selectedConversationId(), tick: this.refreshTick() }))).pipe(
            switchMap(({ id }) => (id === null ? of([]) : this.poll(() => this.chatApi.getMessages(id))))
        ),
        { initialValue: [] }
    );
    readonly selected = computed(
        () => this.conversations().find((conversation) => conversation.id === this.selectedConversationId()) ?? null
    );
    readonly isClaimedByMe = computed(() => {
        const conversation = this.selected();
        const me = this.profileService.currentUserSignal();
        return conversation?.mode === 'human' && !!me && conversation.assigned_operator === me.id;
    });
    readonly tokenPercent = computed(() => {
        const conversation = this.selected();
        if (!conversation?.token_budget) return 0;
        return Math.min(100, (conversation.tokens_used / conversation.token_budget) * 100);
    });

    // The composer is a reactive control, so its enabled state follows the claim through the control API.
    readonly syncComposerEnabled = effect(() => {
        if (this.isClaimedByMe()) this.operatorReply.enable();
        else this.operatorReply.disable();
    });

    protected readonly modeLabels = MODE_LABELS;
    protected readonly operatorReply = new FormControl('', { nonNullable: true, validators: [Validators.required] });

    private readonly chatApi = inject(ChatApiService);
    private readonly profileService = inject(ProfileService);
    private readonly dialog = inject(Dialog);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    constructor() {
        this.loadBindings();
    }

    selectConversation(id: number): void {
        this.selectedConversationId.set(id);
    }

    onBindingFilterChange(value: unknown): void {
        this.bindingFilter.set(value as number);
    }

    onSimulatedMessage(conversationId: number): void {
        this.selectedConversationId.set(conversationId);
        this.refresh();
    }

    openBindingsDialog(): void {
        this.dialog
            .open<boolean>(ChatBindingsDialogComponent, { width: '640px' })
            .closed.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((changed) => {
                if (changed) this.loadBindings();
            });
    }

    claim(conversation: ChatConversation): void {
        this.runAction(this.chatApi.claim(conversation.id));
    }

    release(conversation: ChatConversation): void {
        this.runAction(this.chatApi.release(conversation.id));
    }

    close(conversation: ChatConversation): void {
        this.runAction(this.chatApi.close(conversation.id));
    }

    sendOperatorReply(conversation: ChatConversation): void {
        if (this.operatorReply.invalid) return;
        this.runAction(this.chatApi.sendOperatorMessage(conversation.id, this.operatorReply.value), () =>
            this.operatorReply.reset()
        );
    }

    messageAuthor(message: ChatMessage): string {
        if (message.role === 'operator') return message.author_name ?? 'Operator';
        return message.role;
    }

    private runAction(request$: Observable<unknown>, onDone?: () => void): void {
        if (this.isActionPending()) return;
        this.isActionPending.set(true);
        request$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
            next: () => {
                this.isActionPending.set(false);
                onDone?.();
                this.refresh();
            },
            error: (error: HttpErrorResponse) => {
                this.isActionPending.set(false);
                this.toastService.error(extractHttpErrorMessage(error));
            },
        });
    }

    private refresh(): void {
        this.refreshTick.update((tick) => tick + 1);
    }

    // PROTO: a failed poll is skipped silently; the next tick retries.
    private poll<T>(request: () => Observable<T>): Observable<T> {
        return timer(0, POLL_INTERVAL_MS).pipe(switchMap(() => request().pipe(catchError(() => EMPTY))));
    }

    private loadBindings(): void {
        this.chatApi
            .getBindings()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (bindings) => this.bindings.set(bindings),
                error: (error: HttpErrorResponse) => this.toastService.error(extractHttpErrorMessage(error)),
            });
    }
}
