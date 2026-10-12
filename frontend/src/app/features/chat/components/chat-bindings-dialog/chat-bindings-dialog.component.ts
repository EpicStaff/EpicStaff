import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { formatNumber } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, DestroyRef, effect, inject, LOCALE_ID, signal, untracked } from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import {
    AbstractControl,
    FormControl,
    FormGroup,
    ReactiveFormsModule,
    ValidationErrors,
    ValidatorFn,
    Validators,
} from '@angular/forms';
import {
    AppSvgIconComponent,
    ButtonComponent,
    ChipsInputComponent,
    ConfirmationDialogService,
    CopyFieldComponent,
    CustomInputComponent,
    InputNumberComponent,
    SelectComponent,
    SelectItem,
    TabButtonComponent,
    TextareaComponent,
    ToggleSwitchComponent,
} from '@shared/components';
import { ActionCode, ResourceCode } from '@shared/models';
import { escapeHtml, extractHttpErrorMessage } from '@shared/utils';
import { catchError, EMPTY, filter, map, Observable, of, switchMap } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { FlowsApiService } from '../../../flows/services/flows-api.service';
import {
    CHAT_BINDING_DEFAULTS,
    CHAT_DISPLAY_NAME_MAX,
    ChatBinding,
    ChatBindingInput,
    ChatBindingWithSecret,
    ChatBudgetExhaustedBehaviour,
    ChatErrorBody,
    ChatIdentityMode,
} from '../../models/chat.model';
import { ChatApiService } from '../../services/chat-api.service';
import { bindingPatch } from '../../utils/binding-patch.util';

const IDENTITY_ITEMS: SelectItem<ChatIdentityMode>[] = [
    { name: 'Anonymous visitors', value: 'anonymous' },
    { name: 'Signed identity token from your backend', value: 'signed' },
];
const ON_EXHAUSTED_ITEMS: SelectItem<ChatBudgetExhaustedBehaviour>[] = [
    { name: 'Reply with a fixed message', value: 'reply' },
    { name: 'Hand off to an operator', value: 'handoff' },
];

type BudgetField = 'token_budget_per_conversation' | 'daily_token_budget';
const BUDGET_FIELDS: BudgetField[] = ['token_budget_per_conversation', 'daily_token_budget'];
const BUDGET_DESCRIPTIONS: Record<BudgetField, string> = {
    token_budget_per_conversation:
        'No run starts once a conversation has spent this many tokens in the current UTC day.',
    daily_token_budget: 'Across every conversation of this binding, per UTC day.',
};

type TextField = 'name' | 'bot_display_name' | 'operator_display_name';
const PAUSED_ON_SAVE_MESSAGE = 'Saved but paused: the flow does not meet the chat contract.';
// The server strips the names and refuses an empty one.
const displayNameValidators = [
    Validators.required,
    Validators.pattern(/\S/),
    Validators.maxLength(CHAT_DISPLAY_NAME_MAX),
];

type BindingTab = 'general' | 'limits' | 'handoff';
type BindingControl = keyof ChatBindingsDialogComponent['form']['controls'];
const BINDING_TABS: { id: BindingTab; label: string; controls: BindingControl[] }[] = [
    {
        id: 'general',
        label: 'General',
        controls: ['name', 'bot_display_name', 'graph_id', 'allowed_origins', 'identity_mode'],
    },
    {
        id: 'limits',
        label: 'Limits',
        controls: [
            'history_window',
            'max_message_length',
            'max_turns',
            'messages_per_minute',
            'token_budget_per_conversation',
            'daily_token_budget',
            'on_budget_exhausted',
            'budget_exhausted_message',
        ],
    },
    { id: 'handoff', label: 'Handoff', controls: ['handoff_enabled', 'operator_display_name'] },
];

/** No binding = create mode; a binding = its settings. */
export interface ChatBindingsDialogData {
    binding: ChatBinding | null;
}

/**
 * Creates a chat binding or edits one's settings. Closes without a result: callers reload their bindings on every
 * close. An identity secret the server issues on save is shown here once before the dialog closes.
 */
@Component({
    selector: 'app-chat-bindings-dialog',
    imports: [
        ReactiveFormsModule,
        AppSvgIconComponent,
        ButtonComponent,
        ChipsInputComponent,
        CopyFieldComponent,
        CustomInputComponent,
        InputNumberComponent,
        SelectComponent,
        TabButtonComponent,
        TextareaComponent,
        ToggleSwitchComponent,
    ],
    templateUrl: './chat-bindings-dialog.component.html',
    styleUrls: ['./chat-bindings-dialog.component.scss'],
})
export class ChatBindingsDialogComponent {
    // The binding as last saved: rotating the key replaces it, so a later save diffs against the server's copy.
    readonly binding = signal<ChatBinding | null>(
        inject<ChatBindingsDialogData | null>(DIALOG_DATA, { optional: true })?.binding ?? null
    );
    readonly isSubmitting = signal(false);
    readonly activeTab = signal<BindingTab>('general');
    readonly errorMessage = signal<string | null>(null);
    readonly contractErrors = signal<string[]>([]);
    /** The identity secret the last save issued; shown once instead of the form, gone when the dialog closes. */
    readonly revealedSecret = signal<string | null>(null);
    readonly flowItems = toSignal(
        inject(FlowsApiService)
            .getGraphsLight()
            .pipe(map((graphs) => graphs.map((graph): SelectItem<number> => ({ name: graph.name, value: graph.id })))),
        { initialValue: [] }
    );
    readonly isCreating = computed(() => this.binding() === null);
    readonly formTitle = computed(() => (this.isCreating() ? 'New chat binding' : 'Edit chat binding'));
    readonly budgetTooltips = computed((): Record<BudgetField, string> => {
        const limits = this.limits();
        const describe = (field: BudgetField): string =>
            limits
                ? `${BUDGET_DESCRIPTIONS[field]} Default ${formatNumber(limits.defaults[field], this.locale)}, ` +
                  `at most ${formatNumber(limits.caps[field], this.locale)} on this deployment.`
                : BUDGET_DESCRIPTIONS[field];
        return {
            token_budget_per_conversation: describe('token_budget_per_conversation'),
            daily_token_budget: describe('daily_token_budget'),
        };
    });
    readonly budgetCaps = computed((): Record<BudgetField, number | null> => {
        const caps = this.limits()?.caps;
        return {
            token_budget_per_conversation: caps?.token_budget_per_conversation ?? null,
            daily_token_budget: caps?.daily_token_budget ?? null,
        };
    });

    readonly canUpdate = computed(() => this.permissionsService.can(ResourceCode.Chats, ActionCode.Update));

    protected readonly tabs = BINDING_TABS;
    protected readonly identityItems = IDENTITY_ITEMS;
    protected readonly onExhaustedItems = ON_EXHAUSTED_ITEMS;
    // Public because the spec drives it; the template binds it too.
    readonly form = new FormGroup({
        name: new FormControl('', { nonNullable: true, validators: [Validators.required, Validators.pattern(/\S/)] }),
        bot_display_name: new FormControl('', { nonNullable: true, validators: displayNameValidators }),
        operator_display_name: new FormControl(CHAT_BINDING_DEFAULTS.operator_display_name, {
            nonNullable: true,
            validators: displayNameValidators,
        }),
        graph_id: new FormControl<number | null>(null, { validators: [Validators.required] }),
        allowed_origins: new FormControl<string[]>([], { nonNullable: true }),
        identity_mode: new FormControl<ChatIdentityMode>('anonymous', { nonNullable: true }),
        history_window: new FormControl<number | null>(20, { validators: [Validators.required, Validators.min(0)] }),
        max_message_length: new FormControl<number | null>(4000, {
            validators: [Validators.required, Validators.min(1)],
        }),
        max_turns: new FormControl<number | null>(200, { validators: [Validators.required, Validators.min(0)] }),
        token_budget_per_conversation: new FormControl<number | null>(null, {
            validators: [Validators.required, Validators.min(1), this.withinCap('token_budget_per_conversation')],
        }),
        daily_token_budget: new FormControl<number | null>(null, {
            validators: [Validators.required, Validators.min(1), this.withinCap('daily_token_budget')],
        }),
        messages_per_minute: new FormControl<number | null>(10, {
            validators: [Validators.required, Validators.min(0)],
        }),
        on_budget_exhausted: new FormControl<ChatBudgetExhaustedBehaviour>('reply', { nonNullable: true }),
        budget_exhausted_message: new FormControl(CHAT_BINDING_DEFAULTS.budget_exhausted_message, {
            nonNullable: true,
        }),
        handoff_enabled: new FormControl(true, { nonNullable: true }),
    });

    private readonly chatApi = inject(ChatApiService);
    private readonly permissionsService = inject(PermissionsService);
    private readonly dialogRef = inject(DialogRef);
    private readonly confirmationDialogService = inject(ConfirmationDialogService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly locale = inject(LOCALE_ID);
    /** The server's budget defaults and caps; null until loaded (or on failure), leaving the budgets to type in. */
    // Declared after the injected fields on purpose: its initializer uses chatApi and toastService.
    readonly limits = toSignal(
        this.chatApi.getBindingLimits().pipe(
            catchError((error: HttpErrorResponse) => {
                this.toastService.error(extractHttpErrorMessage(error));
                return EMPTY;
            })
        ),
        { initialValue: null }
    );
    // A form opened before the limits arrived is checked against the caps once they do; on create, budgets the
    // user has not typed yet take the server's defaults.
    private readonly applyLimits = effect(() => {
        const defaults = this.limits()?.defaults;
        untracked(() =>
            BUDGET_FIELDS.forEach((field) => {
                const control = this.form.controls[field];
                if (defaults && this.isCreating() && control.pristine && control.value === null) {
                    control.setValue(defaults[field]);
                }
                control.updateValueAndValidity();
            })
        );
    });

    constructor() {
        // On create the bot name follows the binding name until the user edits it.
        this.form.controls.name.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((name) => {
            const botName = this.form.controls.bot_display_name;
            if (this.isCreating() && botName.pristine) botName.setValue(name.slice(0, CHAT_DISPLAY_NAME_MAX));
        });
        // The contract of the picked flow, checked live; a newer pick or a cleared flow cancels the pending check.
        this.form.controls.graph_id.valueChanges
            .pipe(
                switchMap((graphId) => (graphId === null ? of([]) : this.checkContract(graphId))),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((errors) => this.contractErrors.set(errors));
        const binding = this.binding();
        if (binding) this.fillFrom(binding);
        else this.fillDefaults();
    }

    submit(): void {
        if (this.form.invalid) {
            this.form.markAllAsTouched();
            this.showFirstInvalidTab();
            return;
        }
        if (this.isSubmitting()) return;
        const editing = this.binding();
        const values = this.formValues();
        const request$: Observable<ChatBinding | ChatBindingWithSecret> = editing
            ? this.chatApi.updateBinding(editing.id, bindingPatch(editing, values))
            : this.chatApi.createBinding(values);

        this.isSubmitting.set(true);
        this.errorMessage.set(null);
        request$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
            next: (binding) => {
                this.isSubmitting.set(false);
                if (!binding.is_active && binding.contract_errors.length)
                    this.toastService.warning(PAUSED_ON_SAVE_MESSAGE);
                const secret = 'identity_secret' in binding ? binding.identity_secret : null;
                if (secret) this.revealedSecret.set(secret);
                else this.close();
            },
            error: (error: HttpErrorResponse) => {
                this.isSubmitting.set(false);
                const body = error.error as ChatErrorBody | null;
                const capField = BUDGET_FIELDS.find((field) => field === body?.field);
                // A malformed body (unknown field, missing or non-numeric max) falls back to the banner.
                if (body?.code === 'budget_above_cap' && capField && typeof body.max === 'number') {
                    // A control error clears itself on the next edit of that field.
                    this.form.controls[capField].setErrors({ budgetAboveCap: body.max });
                    this.showFirstInvalidTab();
                    return;
                }
                this.errorMessage.set(extractHttpErrorMessage(error));
            },
        });
    }

    rotateKey(): void {
        const binding = this.binding();
        if (!binding) return;
        this.confirmationDialogService
            .confirm({
                title: 'Rotate public key',
                message: `Embeds using the current key of <strong>${escapeHtml(binding.name)}</strong> stop working until updated. Existing conversations keep working.`,
                confirmText: 'Rotate',
                cancelText: 'Cancel',
                type: 'danger',
            })
            .pipe(
                filter((confirmed) => confirmed === true),
                switchMap(() => this.chatApi.rotateKey(binding.id)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (updated) => {
                    this.binding.set(updated);
                    this.toastService.success('Public key rotated');
                },
                error: (error: HttpErrorResponse) => this.toastService.error(extractHttpErrorMessage(error)),
            });
    }

    close(): void {
        this.dialogRef.close();
    }

    textFieldError(field: TextField): string {
        const control = this.form.controls[field];
        if (!control.touched) return '';
        if (control.hasError('maxlength')) return `At most ${CHAT_DISPLAY_NAME_MAX} characters`;
        return control.invalid ? 'Required' : '';
    }

    // Not a signal: the template re-reads it because the error callback also writes isSubmitting.
    budgetCapMessage(field: BudgetField): string {
        const max: unknown = this.form.controls[field].errors?.['budgetAboveCap'];
        return typeof max === 'number' ? `At most ${formatNumber(max, this.locale)} on this deployment` : '';
    }

    // A field on a hidden tab would block Save without the user seeing why.
    private showFirstInvalidTab(): void {
        const tab = BINDING_TABS.find(({ controls }) => controls.some((name) => this.form.controls[name].invalid));
        if (tab) this.activeTab.set(tab.id);
    }

    private fillDefaults(): void {
        // Nullable controls reset to null, so the defaults are restated here; budgets come from the server.
        const budgets = this.limits()?.defaults;
        this.form.reset({
            ...CHAT_BINDING_DEFAULTS,
            name: '',
            bot_display_name: '',
            graph_id: null,
            token_budget_per_conversation: budgets?.token_budget_per_conversation ?? null,
            daily_token_budget: budgets?.daily_token_budget ?? null,
        });
    }

    private fillFrom(binding: ChatBinding): void {
        // Stored errors first: the reset re-checks the flow live and replaces them with the current ones.
        this.contractErrors.set(binding.contract_errors);
        // reset() reads only the keys the form has; id, public_key and the rest are ignored.
        this.form.reset(binding);
    }

    /** Contract errors of a flow; a missing flow is one error, any other failure is a toast and keeps the shown ones. */
    private checkContract(graphId: number): Observable<string[]> {
        return this.chatApi.checkContract(graphId).pipe(
            map(({ contract_errors }) => contract_errors),
            catchError((error: HttpErrorResponse) => {
                const body = error.error as ChatErrorBody | null;
                if (body?.code === 'unknown_flow') return of([body.message || 'The flow no longer exists.']);
                this.toastService.error(extractHttpErrorMessage(error));
                return EMPTY;
            })
        );
    }

    private formValues(): ChatBindingInput {
        const raw = this.form.getRawValue();
        // Validators.required guarantees the numeric controls and graph_id are set.
        return {
            ...raw,
            graph_id: raw.graph_id as number,
            history_window: raw.history_window as number,
            max_message_length: raw.max_message_length as number,
            max_turns: raw.max_turns as number,
            messages_per_minute: raw.messages_per_minute as number,
            token_budget_per_conversation: raw.token_budget_per_conversation as number,
            daily_token_budget: raw.daily_token_budget as number,
        };
    }

    /** Same error key as the server's `budget_above_cap`, so `budgetCapMessage` shows both. */
    private withinCap(field: BudgetField): ValidatorFn {
        return (control: AbstractControl<number | null>): ValidationErrors | null => {
            // Only a typed budget is checked: the PATCH never sends an untouched one, so a stored budget above a
            // lowered cap must not block other edits. Runs during form construction too, before `limits` exists.
            if (!control.dirty || typeof control.value !== 'number') return null;
            const cap = this.limits()?.caps[field];
            return cap !== undefined && control.value > cap ? { budgetAboveCap: cap } : null;
        };
    }
}
