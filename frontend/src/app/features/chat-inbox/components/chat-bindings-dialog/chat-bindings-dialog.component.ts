import { DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    AppSvgIconComponent,
    ButtonComponent,
    ConfirmationDialogService,
    CustomInputComponent,
    InputNumberComponent,
    SelectComponent,
    SelectItem,
    TextareaComponent,
    ToggleSwitchComponent,
} from '@shared/components';
import { escapeHtml, extractHttpErrorMessage } from '@shared/utils';
import { filter, map, Observable, switchMap } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { FlowsApiService } from '../../../flows/services/flows-api.service';
import {
    ChatBinding,
    ChatBindingRequest,
    ChatBudgetExhaustedBehaviour,
    ChatChannel,
    ChatConcurrencyPolicy,
} from '../../models/chat.model';
import { ChatApiService } from '../../services/chat-api.service';

const CHANNEL_ITEMS: SelectItem<ChatChannel>[] = [
    { name: 'Widget', value: 'widget' },
    { name: 'Telegram', value: 'telegram' },
];
const POLICY_ITEMS: SelectItem<ChatConcurrencyPolicy>[] = [
    { name: 'Interrupt — stop the running reply, answer everything', value: 'interrupt' },
    { name: 'Queue — finish the reply, then answer the rest', value: 'queue' },
];
const ON_EXHAUSTED_ITEMS: SelectItem<ChatBudgetExhaustedBehaviour>[] = [
    { name: 'Hand off to an operator', value: 'handoff' },
    { name: 'Reply with a fixed message', value: 'reply' },
];

// Closes with `true` when any binding was created, changed or deleted, so the inbox reloads.
@Component({
    selector: 'app-chat-bindings-dialog',
    imports: [
        ReactiveFormsModule,
        AppSvgIconComponent,
        ButtonComponent,
        CustomInputComponent,
        InputNumberComponent,
        SelectComponent,
        TextareaComponent,
        ToggleSwitchComponent,
    ],
    templateUrl: './chat-bindings-dialog.component.html',
    styleUrls: ['./chat-bindings-dialog.component.scss'],
})
export class ChatBindingsDialogComponent {
    readonly bindings = signal<ChatBinding[]>([]);
    // null = list view; 'new' or a binding = form view.
    readonly editing = signal<ChatBinding | 'new' | null>(null);
    readonly isSubmitting = signal(false);
    readonly errorMessage = signal<string | null>(null);
    readonly flowItems = toSignal(
        inject(FlowsApiService)
            .getGraphsLight()
            .pipe(map((graphs) => graphs.map((graph): SelectItem<number> => ({ name: graph.name, value: graph.id })))),
        { initialValue: [] }
    );
    readonly formTitle = computed(() => (this.editing() === 'new' ? 'New chat binding' : 'Edit chat binding'));

    protected readonly channelItems = CHANNEL_ITEMS;
    protected readonly policyItems = POLICY_ITEMS;
    protected readonly onExhaustedItems = ON_EXHAUSTED_ITEMS;
    protected readonly form = new FormGroup({
        name: new FormControl('', { nonNullable: true, validators: [Validators.required] }),
        graph: new FormControl<number | null>(null, { validators: [Validators.required] }),
        channel: new FormControl<ChatChannel>('widget', { nonNullable: true }),
        is_active: new FormControl(true, { nonNullable: true }),
        concurrency_policy: new FormControl<ChatConcurrencyPolicy>('interrupt', { nonNullable: true }),
        history_window: new FormControl<number | null>(20, { validators: [Validators.required, Validators.min(0)] }),
        token_budget_per_conversation: new FormControl<number | null>(null),
        on_budget_exhausted: new FormControl<ChatBudgetExhaustedBehaviour>('handoff', { nonNullable: true }),
        budget_exhausted_message: new FormControl('', { nonNullable: true }),
        handoff_enabled: new FormControl(true, { nonNullable: true }),
    });

    private readonly chatApi = inject(ChatApiService);
    private readonly dialogRef = inject<DialogRef<boolean>>(DialogRef);
    private readonly confirmationDialogService = inject(ConfirmationDialogService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);
    private changed = false;

    constructor() {
        this.loadBindings();
    }

    startCreate(): void {
        // Nullable controls reset to null, not to their initial value, so the spec default is restated.
        this.form.reset({ history_window: 20 });
        this.errorMessage.set(null);
        this.editing.set('new');
    }

    startEdit(binding: ChatBinding): void {
        // reset() only reads the keys the form has; id and graph_name are ignored.
        this.form.reset(binding);
        this.errorMessage.set(null);
        this.editing.set(binding);
    }

    backToList(): void {
        this.editing.set(null);
    }

    submit(): void {
        if (this.form.invalid) {
            this.form.markAllAsTouched();
            return;
        }
        if (this.isSubmitting()) return;
        const editing = this.editing();
        const values = this.form.getRawValue();
        // Validators.required guarantees graph and history_window are set.
        const body: ChatBindingRequest = {
            ...values,
            graph: values.graph as number,
            history_window: values.history_window as number,
        };
        const request$: Observable<ChatBinding> =
            editing && editing !== 'new'
                ? this.chatApi.updateBinding(editing.id, body)
                : this.chatApi.createBinding(body);

        this.isSubmitting.set(true);
        this.errorMessage.set(null);
        request$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
            next: () => {
                this.isSubmitting.set(false);
                this.changed = true;
                this.editing.set(null);
                this.loadBindings();
            },
            error: (error: HttpErrorResponse) => {
                this.isSubmitting.set(false);
                this.errorMessage.set(extractHttpErrorMessage(error));
            },
        });
    }

    delete(binding: ChatBinding): void {
        this.confirmationDialogService
            .confirmDelete(escapeHtml(binding.name))
            .pipe(
                filter((confirmed) => confirmed === true),
                switchMap(() => this.chatApi.deleteBinding(binding.id)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: () => {
                    this.changed = true;
                    this.loadBindings();
                },
                error: (error: HttpErrorResponse) => this.toastService.error(extractHttpErrorMessage(error)),
            });
    }

    close(): void {
        this.dialogRef.close(this.changed);
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
