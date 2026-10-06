import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, DestroyRef, effect, inject, input, output, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { ButtonComponent, CustomInputComponent, SelectComponent, SelectItem } from '@shared/components';
import { extractHttpErrorMessage } from '@shared/utils';

import { ToastService } from '../../../../services/notifications';
import { ChatBinding, ChatInboundAction } from '../../models/chat.model';
import { ChatApiService } from '../../services/chat-api.service';

interface InboundLogEntry {
    id: number;
    externalId: string;
    content: string;
    action: ChatInboundAction;
}

const LOG_SIZE = 6;

// Stands in for the end user's channel (widget / Telegram) so the router's decisions can be exercised by hand.
@Component({
    selector: 'app-simulate-end-user-panel',
    imports: [ReactiveFormsModule, ButtonComponent, CustomInputComponent, SelectComponent],
    templateUrl: './simulate-end-user-panel.component.html',
    styleUrls: ['./simulate-end-user-panel.component.scss'],
})
export class SimulateEndUserPanelComponent {
    readonly bindings = input.required<ChatBinding[]>();
    readonly conversationTouched = output<number>();

    readonly isSending = signal(false);
    readonly log = signal<InboundLogEntry[]>([]);
    readonly bindingItems = computed(() =>
        this.bindings().map((binding): SelectItem<number> => ({ name: binding.name, value: binding.id }))
    );

    // Picks the first binding once the list arrives, so the panel is usable without a click.
    readonly selectFirstBinding = effect(() => {
        const first = this.bindings()[0];
        if (first && this.form.controls.binding.value === null) this.form.controls.binding.setValue(first.id);
    });

    protected readonly form = new FormGroup({
        binding: new FormControl<number | null>(null, { validators: [Validators.required] }),
        external_id: new FormControl('visitor-1', { nonNullable: true, validators: [Validators.required] }),
        content: new FormControl('', { nonNullable: true, validators: [Validators.required] }),
    });

    private readonly chatApi = inject(ChatApiService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    send(): void {
        const { binding, external_id, content } = this.form.getRawValue();
        if (this.form.invalid || binding === null || this.isSending()) return;

        this.isSending.set(true);
        this.chatApi
            .sendInbound(binding, { external_id, content })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (response) => {
                    this.isSending.set(false);
                    this.form.controls.content.reset();
                    this.log.update((log) =>
                        [
                            { id: response.message_id, externalId: external_id, content, action: response.action },
                            ...log,
                        ].slice(0, LOG_SIZE)
                    );
                    this.conversationTouched.emit(response.conversation_id);
                },
                error: (error: HttpErrorResponse) => {
                    this.isSending.set(false);
                    this.toastService.error(extractHttpErrorMessage(error));
                },
            });
    }

    actionLabel(action: ChatInboundAction): string {
        return action.replaceAll('_', ' ');
    }
}
