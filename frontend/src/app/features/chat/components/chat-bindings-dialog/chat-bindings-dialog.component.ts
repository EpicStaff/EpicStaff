import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { formatNumber, NgTemplateOutlet } from '@angular/common';
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
import { MatTooltip } from '@angular/material/tooltip';
import {
    AppSvgIconComponent,
    ButtonComponent,
    ChipsInputComponent,
    ConfirmationDialogService,
    CopyFieldComponent,
    CustomInputComponent,
    HintMessageComponent,
    InputNumberComponent,
    SelectComponent,
    SelectItem,
    TabButtonComponent,
    TextareaComponent,
    ToggleSwitchComponent,
    ValidationErrorsComponent,
} from '@shared/components';
import { notWhitespaceValidator } from '@shared/form-validators';
import { ActionCode, ResourceCode } from '@shared/models';
import { escapeHtml, extractHttpErrorMessage } from '@shared/utils';
import { catchError, EMPTY, filter, map, Observable, of, switchMap, tap } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { FlowsApiService } from '../../../flows/services/flows-api.service';
import {
    CHAT_BINDING_DEFAULTS,
    CHAT_DISPLAY_NAME_MAX,
    ChatBinding,
    ChatBindingInput,
    ChatBindingLimits,
    ChatBindingWithSecret,
    ChatBudgetExhaustedBehaviour,
    ChatContractMissing,
    ChatConversationStyle,
    ChatErrorBody,
    ChatIdentityMode,
    ChatResponseTimeoutAction,
} from '../../models/chat.model';
import { ChatApiService } from '../../services/chat-api.service';
import { bindingPatch } from '../../utils/binding-patch.util';
import { hasContractGaps } from '../../utils/contract-fix.util';
import { normalizePublicName, publicNameError, validationReason } from '../../utils/public-name.util';
import { ChatContractFixComponent } from '../chat-contract-fix/chat-contract-fix.component';

const IDENTITY_ITEMS: SelectItem<ChatIdentityMode>[] = [
    { name: 'Anonymous visitors', value: 'anonymous' },
    { name: 'Signed identity token from your backend', value: 'signed' },
];
const ON_EXHAUSTED_ITEMS: SelectItem<ChatBudgetExhaustedBehaviour>[] = [
    { name: 'Reply with a fixed message', value: 'reply' },
    { name: 'Hand off to an operator', value: 'handoff' },
];
const ON_RESPONSE_TIMEOUT_ITEMS: SelectItem<ChatResponseTimeoutAction>[] = [
    { name: 'Hand back to the bot', value: 'handback' },
    { name: 'Mark as overdue', value: 'overdue' },
    { name: 'Keep waiting', value: 'wait' },
];
const STYLE_OPTIONS: { value: ChatConversationStyle; label: string; description: string }[] = [
    {
        value: 'support',
        label: 'Support',
        description: 'Each conversation closes once resolved or quiet; the bot starts fresh in the next one.',
    },
    {
        value: 'ongoing',
        label: 'Ongoing',
        description: 'One long-lived conversation per visitor that never closes by itself; the bot keeps the context.',
    },
];

type BudgetField = 'token_budget_per_conversation' | 'daily_token_budget';
const BUDGET_FIELDS: BudgetField[] = ['token_budget_per_conversation', 'daily_token_budget'];
const BUDGET_DESCRIPTIONS: Record<BudgetField, string> = {
    token_budget_per_conversation:
        'No run starts once a conversation has spent this many tokens in the current UTC day.',
    daily_token_budget: 'Across every conversation of this desk, per UTC day.',
};

// The inactivity durations are typed in whole minutes or hours; the server stores seconds.
type DurationField = 'response_time_seconds' | 'close_after_seconds';
type DurationControl = 'response_time_minutes' | 'close_after_hours';
interface DurationUnit {
    control: DurationControl;
    seconds: number;
    // "at most 1,440 minutes", "longer than 1 minute".
    name: string;
    singularName: string;
    description: string;
}
const DURATION_FIELDS: DurationField[] = ['response_time_seconds', 'close_after_seconds'];
const DURATION_UNITS: Record<DurationField, DurationUnit> = {
    response_time_seconds: {
        control: 'response_time_minutes',
        seconds: 60,
        name: 'minutes',
        singularName: 'minute',
        description: 'How long a visitor may wait for a person before the action below.',
    },
    close_after_seconds: {
        control: 'close_after_hours',
        seconds: 3600,
        name: 'hours',
        singularName: 'hour',
        description: 'A Support conversation closes after this long without a message.',
    },
};
// The number fields checked against a deployment cap.
const CAPPED_CONTROLS: (BudgetField | DurationControl)[] = [
    ...BUDGET_FIELDS,
    ...DURATION_FIELDS.map((field) => DURATION_UNITS[field].control),
];

type TextField = 'name' | 'bot_display_name' | 'operator_display_name';
const TEXT_FIELD_LABELS: Record<TextField, string> = {
    name: 'Name',
    bot_display_name: 'Displayed bot name',
    operator_display_name: 'Displayed operator name',
};
const TEXT_FIELDS = Object.keys(TEXT_FIELD_LABELS) as TextField[];
const DEFAULTS_MISSING_MESSAGE = "Couldn't fill in this desk's default settings. Close the dialog and try again.";
const PAUSED_ON_SAVE_MESSAGE = 'Saved but paused: the flow does not meet the chat contract.';

/** What a checked flow lacks for the chat contract; `gaps` is null when it lacks nothing (or was not found). */
interface CheckedContract {
    errors: string[];
    gaps: { graphId: number; missing: ChatContractMissing } | null;
}
const NO_CONTRACT_CHECK: CheckedContract = { errors: [], gaps: null };

let nextDialogId = 0;

type BindingTab = 'general' | 'limits' | 'handoff' | 'inactivity';
type BindingControl = keyof ChatBindingsDialogComponent['form']['controls'];
// What a new desk is set up with; fixed once it exists.
const GENERAL_CONTROLS: BindingControl[] = [
    'name',
    'bot_display_name',
    'graph_id',
    'style',
    'allowed_origins',
    'identity_mode',
];
const BINDING_TABS: { id: BindingTab; label: string; controls: BindingControl[] }[] = [
    {
        id: 'general',
        label: 'General',
        controls: GENERAL_CONTROLS,
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
    {
        id: 'inactivity',
        label: 'Inactivity',
        controls: ['response_time_minutes', 'on_response_timeout', 'handback_message', 'close_after_hours'],
    },
];

/**
 * No binding = create mode; a binding = its settings. `canDelete` offers Delete desk in the settings: the opener
 * deletes the desk, so only an opener that handles the request passes it.
 */
export interface ChatBindingsDialogData {
    binding: ChatBinding | null;
    canDelete?: boolean;
}

/** The settings' Delete desk: the dialog deletes nothing, the opener deletes the desk with its own confirmation. */
export interface ChatBindingDeleteRequest {
    readonly deleteRequested: true;
}

export type ChatBindingsDialogResult = ChatBinding | ChatBindingDeleteRequest;

export const isChatBindingDeleteRequest = (
    result: ChatBindingsDialogResult | null | undefined
): result is ChatBindingDeleteRequest => !!result && 'deleteRequested' in result;

/**
 * Creates a chat binding or edits one's settings. Closes with the binding as it last saved it (without the identity
 * secret), or without a result when it saved nothing; Escape and a backdrop click always close without one. Delete
 * desk closes with a `ChatBindingDeleteRequest` instead. An identity secret the server issues on save is shown here
 * once before the dialog closes.
 */
@Component({
    selector: 'app-chat-bindings-dialog',
    imports: [
        NgTemplateOutlet,
        ReactiveFormsModule,
        MatTooltip,
        AppSvgIconComponent,
        ButtonComponent,
        ChipsInputComponent,
        ChatContractFixComponent,
        CopyFieldComponent,
        CustomInputComponent,
        HintMessageComponent,
        InputNumberComponent,
        SelectComponent,
        TabButtonComponent,
        TextareaComponent,
        ToggleSwitchComponent,
        ValidationErrorsComponent,
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
    // A new desk is set up on General alone; an existing one opens on the first of its settings tabs.
    readonly activeTab = signal<BindingTab>(this.binding() === null ? 'general' : 'limits');
    readonly errorMessage = signal<string | null>(null);
    /** The server's refusals of named fields, said once for screen readers; each also shows under its field. */
    readonly fieldRefusalAnnouncement = signal('');
    readonly contractErrors = signal<string[]>([]);
    readonly contractGaps = signal<CheckedContract['gaps']>(null);
    /** The identity secret the last save issued; shown once instead of the form, gone when the dialog closes. */
    readonly revealedSecret = signal<string | null>(null);
    readonly flowItems = toSignal(
        inject(FlowsApiService)
            .getGraphsLight()
            .pipe(map((graphs) => graphs.map((graph): SelectItem<number> => ({ name: graph.name, value: graph.id })))),
        { initialValue: [] }
    );
    readonly isCreating = computed(() => this.binding() === null);
    readonly formTitle = computed(() => (this.isCreating() ? 'New desk' : 'Desk settings'));
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
    /** The inactivity durations' default and cap, in the unit each is typed in. */
    readonly durationTooltips = computed((): Record<DurationField, string> => {
        const limits = this.limits();
        const describe = (field: DurationField): string => {
            const { description, seconds } = DURATION_UNITS[field];
            if (!limits) return description;
            const defaultUnits = toUnits(limits.defaults[field], seconds);
            const capUnits = Math.floor(limits.caps[field] / seconds);
            return (
                `${description} Default ${formatNumber(defaultUnits, this.locale)}, ` +
                `at most ${formatNumber(capUnits, this.locale)} on this deployment.`
            );
        };
        return {
            response_time_seconds: describe('response_time_seconds'),
            close_after_seconds: describe('close_after_seconds'),
        };
    });
    readonly durationCaps = computed((): Record<DurationField, number | null> => {
        const caps = this.limits()?.caps;
        const inUnits = (field: DurationField): number | null =>
            caps ? Math.floor(caps[field] / DURATION_UNITS[field].seconds) : null;
        return {
            response_time_seconds: inUnits('response_time_seconds'),
            close_after_seconds: inUnits('close_after_seconds'),
        };
    });

    readonly canUpdate = computed(() => this.permissionsService.can(ResourceCode.Chats, ActionCode.Update));

    // Creating shows General alone (with no tab row); the settings show the other tabs.
    protected readonly tabs = computed(() => BINDING_TABS.filter(({ id }) => (id === 'general') === this.isCreating()));
    // Delete desk: only an existing desk, and only when the opener offers it (it checked chats:delete).
    protected readonly canRequestDelete =
        !this.isCreating() && !!inject<ChatBindingsDialogData | null>(DIALOG_DATA, { optional: true })?.canDelete;
    protected readonly identityItems = IDENTITY_ITEMS;
    protected readonly onExhaustedItems = ON_EXHAUSTED_ITEMS;
    protected readonly onResponseTimeoutItems = ON_RESPONSE_TIMEOUT_ITEMS;
    protected readonly styleOptions = STYLE_OPTIONS;
    // Public because the spec drives it; the template binds it too.
    readonly form = new FormGroup({
        name: new FormControl('', { nonNullable: true, validators: [Validators.required, notWhitespaceValidator()] }),
        bot_display_name: new FormControl('', { nonNullable: true, validators: this.publicName() }),
        operator_display_name: new FormControl(CHAT_BINDING_DEFAULTS.operator_display_name, {
            nonNullable: true,
            validators: this.publicName(),
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
        style: new FormControl<ChatConversationStyle>(CHAT_BINDING_DEFAULTS.style, { nonNullable: true }),
        // The inactivity rules; on create they come from the server's defaults (`applyLimits`).
        response_time_minutes: new FormControl<number | null>(null, {
            validators: [Validators.required, Validators.min(1), this.withinDurationCap('response_time_seconds')],
        }),
        on_response_timeout: new FormControl<ChatResponseTimeoutAction | null>(null, {
            validators: [Validators.required],
        }),
        handback_message: new FormControl<string | null>(null),
        // Support only: disabled on an Ongoing desk, where it shows as Never.
        close_after_hours: new FormControl<number | null>(null, {
            validators: [Validators.required, Validators.min(1), this.withinDurationCap('close_after_seconds')],
        }),
    });
    // Declared after the form on purpose: they follow its controls.
    readonly isOngoing = toSignal(this.form.controls.style.valueChanges.pipe(map((style) => style === 'ongoing')), {
        initialValue: false,
    });
    readonly responseTimeoutAction = toSignal(this.form.controls.on_response_timeout.valueChanges, {
        initialValue: null,
    });
    // Every edit, disabled controls included.
    private readonly formValue = toSignal(this.form.valueChanges.pipe(map(() => this.form.getRawValue())), {
        initialValue: this.form.getRawValue(),
    });
    /**
     * What saving the edited rules does to the desk's existing conversations, said before the save: the chat service
     * applies changed rules to them on its next timer passes. Only a change that acts on them counts, so only on a
     * desk's settings (where the style is fixed): a shorter close after on a Support desk closes the conversations
     * silent for longer; switching to hand back, or a shorter response time with hand back, hands back visitors who
     * have waited longer. A shorter response time with mark overdue only marks rows in this UI, and keep waiting does
     * nothing.
     */
    readonly backlogEffects = computed((): string[] => {
        const values = this.formValue();
        const saved = this.binding();
        if (!saved) return [];
        const effects: string[] = [];
        const closeAfter = this.durationSeconds('close_after_seconds');
        if (values.style === 'support' && closeAfter !== null && closeAfter < saved.close_after_seconds) {
            const silence = this.durationText('close_after_seconds', closeAfter);
            effects.push(`Conversations with no message for more than ${silence} close.`);
        }
        const responseTime = this.durationSeconds('response_time_seconds');
        if (values.on_response_timeout === 'handback' && responseTime !== null) {
            if (saved.on_response_timeout !== 'handback' || responseTime < saved.response_time_seconds) {
                const waited = this.durationText('response_time_seconds', responseTime);
                const notice = values.handback_message?.trim() ? ', with the hand-back notice' : '';
                // The waiting set includes taken conversations whose visitor wrote again: a hand back ends the hold.
                effects.push(
                    `Visitors who have waited for a person for more than ${waited} go back to the bot, including ones ` +
                        `an operator has taken over${notice}.`
                );
            }
        }
        return effects;
    });

    private readonly chatApi = inject(ChatApiService);
    private readonly permissionsService = inject(PermissionsService);
    private readonly dialogRef = inject<DialogRef<ChatBindingsDialogResult>>(DialogRef);
    private readonly confirmationDialogService = inject(ConfirmationDialogService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly locale = inject(LOCALE_ID);
    private readonly idPrefix = `bindings-dialog-${nextDialogId++}`;
    // What this dialog last saved, handed to the opener on close.
    private saved: ChatBinding | null = null;
    /**
     * The seconds each duration control was filled with (the desk's, or the server's default on create). An untouched
     * control sends them as they are, so a value that is no whole number of units is never rounded into the PATCH.
     */
    private readonly filledSeconds: Partial<Record<DurationField, number>> = {};
    /**
     * The server's create defaults and caps (budgets, inactivity rules); null until loaded (or on failure), leaving
     * those fields to fill in.
     */
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
    // A form opened before the limits arrived is checked against the caps once they do; on create, every field they
    // have a default for that the user has not filled in yet takes it.
    private readonly applyLimits = effect(() => {
        const defaults = this.limits()?.defaults;
        untracked(() => {
            if (defaults && this.isCreating()) this.fillUntouched(defaults);
            CAPPED_CONTROLS.forEach((name) => this.form.controls[name].updateValueAndValidity());
        });
    });

    constructor() {
        // A number field turns red while a typed value is out of its range, so its reason shows then too, not on blur.
        for (const name of CAPPED_CONTROLS) {
            const control = this.form.controls[name];
            control.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => {
                if (control.dirty) control.markAsTouched();
            });
        }
        // On create the bot name follows the binding name until the user edits it.
        this.form.controls.name.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((name) => {
            const botName = this.form.controls.bot_display_name;
            // Characters, not UTF-16 units: a cut through an emoji would leave half of it.
            if (this.isCreating() && botName.pristine) {
                botName.setValue([...name].slice(0, CHAT_DISPLAY_NAME_MAX).join(''));
            }
        });
        // Close after applies to Support only: on Ongoing it is out of the form's checks and shows as Never.
        this.form.controls.style.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((style) => {
            const closeAfter = this.form.controls.close_after_hours;
            if (style === 'ongoing') closeAfter.disable({ emitEvent: false });
            else closeAfter.enable({ emitEvent: false });
        });
        // The contract of the picked flow, checked live; a newer pick or a cleared flow cancels the pending check. Only
        // a new desk picks its flow: the settings never show it, so they ask nothing.
        this.form.controls.graph_id.valueChanges
            .pipe(
                filter(() => this.isCreating()),
                // The fix belongs to the flow it was checked for. A check of the same flow again (after a fix) keeps
                // it, so a failed check leaves the errors and the fix of the last one that answered, together.
                tap((graphId) => {
                    if (this.contractGaps()?.graphId !== graphId) this.contractGaps.set(null);
                }),
                switchMap((graphId) => (graphId === null ? of(NO_CONTRACT_CHECK) : this.checkContract(graphId))),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe(({ errors, gaps }) => {
                this.contractErrors.set(errors);
                this.contractGaps.set(gaps);
            });
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
        this.fieldRefusalAnnouncement.set('');
        request$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
            next: (binding) => {
                this.isSubmitting.set(false);
                this.remember(binding);
                if (!binding.is_active && binding.contract_errors.length)
                    this.toastService.warning(PAUSED_ON_SAVE_MESSAGE);
                const secret = 'identity_secret' in binding ? binding.identity_secret : null;
                if (secret) this.revealedSecret.set(secret);
                else this.close();
            },
            error: (error: HttpErrorResponse) => {
                this.isSubmitting.set(false);
                const body = error.error as ChatErrorBody | null;
                if (this.showCapRefusal(body)) return;
                const { byField, rest } = fieldRefusals(body);
                if (byField.size) {
                    this.showFieldRefusals(byField);
                    // Refusals the dialog cannot place on a field still show, in the banner.
                    if (rest.length) this.errorMessage.set(rest.join(' '));
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
                    this.remember(updated);
                    this.toastService.success('Public key rotated');
                },
                error: (error: HttpErrorResponse) => this.toastService.error(extractHttpErrorMessage(error)),
            });
    }

    close(): void {
        this.dialogRef.close(this.saved ?? undefined);
    }

    /** Closes asking the opener to delete the desk; the opener confirms and deletes it. */
    requestDelete(): void {
        this.dialogRef.close({ deleteRequested: true });
    }

    /** Checks the picked flow's contract again, through the live check (the same flow, emitted once more). */
    recheckContract(): void {
        this.form.controls.graph_id.updateValueAndValidity();
    }

    /**
     * Whether a field shows its invalid state: when `app-validation-errors` says its errors under it. Not a signal:
     * the template re-reads it, as the control's state is not one.
     */
    protected showsError(name: BindingControl): boolean {
        const control = this.form.controls[name];
        return control.invalid && control.touched;
    }

    /** The id of the warning about existing conversations, which describes Save while it applies. */
    protected backlogWarningId(): string {
        return `${this.idPrefix}-backlog`;
    }

    /** The id of a style card's title (which names its radio) or its line (which describes it). */
    protected styleTextId(style: ChatConversationStyle, part: 'name' | 'description'): string {
        return `${this.idPrefix}-style-${style}-${part}`;
    }

    // "24 hours", "1 minute": a duration in the unit it is typed in.
    private durationText(field: DurationField, seconds: number): string {
        const { seconds: unitSeconds, name, singularName } = DURATION_UNITS[field];
        const units = toUnits(seconds, unitSeconds);
        return `${formatNumber(units, this.locale)} ${units === 1 ? singularName : name}`;
    }

    // The secret is shown once, here: the opener gets the binding without it.
    private remember(binding: ChatBinding | ChatBindingWithSecret): void {
        const saved: Partial<ChatBindingWithSecret> = { ...binding };
        delete saved.identity_secret;
        this.saved = saved as ChatBinding;
    }

    /**
     * A `budget_above_cap` or `duration_above_cap` refusal on the field it names, with the deployment's max (a
     * duration's in its unit); false for any other body, and for a malformed one (unknown field, no numeric max), which
     * the banner says instead. A control error clears itself on the next edit of that field; touched, so it shows.
     */
    private showCapRefusal(body: ChatErrorBody | null): boolean {
        if (typeof body?.max !== 'number') return false;
        const budgetField = BUDGET_FIELDS.find((field) => field === body.field);
        const durationField = DURATION_FIELDS.find((field) => field === body.field);
        if (body.code === 'budget_above_cap' && budgetField) {
            const control = this.form.controls[budgetField];
            control.setErrors({ budgetAboveCap: this.budgetCapError(body.max) });
            control.markAsTouched();
        } else if (body.code === 'duration_above_cap' && durationField) {
            const { control: name, seconds } = DURATION_UNITS[durationField];
            const control = this.form.controls[name];
            control.setErrors({
                durationAboveCap: this.durationCapError(durationField, Math.floor(body.max / seconds)),
            });
            control.markAsTouched();
        } else {
            return false;
        }
        this.showFirstInvalidTab();
        return true;
    }

    /** Each refusal under its field (on its tab), said once for screen readers; the dialog stays open. */
    private showFieldRefusals(byField: ReadonlyMap<TextField, string>): void {
        byField.forEach((message, field) => {
            const control = this.form.controls[field];
            // The server's word on what was sent, said under the field; clears itself on the next edit of that field.
            control.setErrors({ serverRefusal: message });
            control.markAsTouched();
        });
        this.showFirstInvalidTab();
        this.fieldRefusalAnnouncement.set(
            [...byField].map(([field, message]) => `${TEXT_FIELD_LABELS[field]}: ${message}`).join(' ')
        );
    }

    // A field on a hidden tab would block Save without the user seeing why. Creating shows General alone, so an invalid
    // field elsewhere is a default that never arrived (the limits failed to load) or was refused: said above the form.
    private showFirstInvalidTab(): void {
        const tab = this.tabs().find(({ controls }) => controls.some((name) => this.form.controls[name].invalid));
        if (tab) this.activeTab.set(tab.id);
        else if (this.form.invalid && this.isCreating()) this.errorMessage.set(DEFAULTS_MISSING_MESSAGE);
    }

    private fillDefaults(): void {
        // Nullable controls reset to null, so the defaults are restated here; the server's come in `applyLimits`.
        this.form.reset({
            ...CHAT_BINDING_DEFAULTS,
            name: '',
            bot_display_name: '',
            graph_id: null,
        });
    }

    private fillFrom(binding: ChatBinding): void {
        // reset() reads only the keys the form has; id, public_key and the rest are ignored. The durations are typed
        // in other units than the binding's seconds.
        this.form.reset(binding);
        for (const field of DURATION_FIELDS) this.fillDuration(field, binding[field]);
        // Set on create and not shown in the settings: out of the checks, so a value saved before a validator was
        // tightened cannot block a save the user has no field to fix. Still read by the backlog rules and the diff.
        for (const name of GENERAL_CONTROLS) this.form.controls[name].disable({ emitEvent: false });
    }

    // On create, what the user has not filled in yet takes the server's default.
    private fillUntouched(defaults: ChatBindingLimits['defaults']): void {
        for (const field of BUDGET_FIELDS) {
            const control = this.form.controls[field];
            if (control.pristine && control.value === null) control.setValue(defaults[field]);
        }
        for (const field of DURATION_FIELDS) {
            const control = this.form.controls[DURATION_UNITS[field].control];
            if (control.pristine && control.value === null) this.fillDuration(field, defaults[field]);
        }
        const { on_response_timeout: action, handback_message: notice, style } = this.form.controls;
        if (action.pristine && action.value === null) action.setValue(defaults.on_response_timeout);
        if (notice.pristine && notice.value === null) notice.setValue(defaults.handback_message);
        // Never null, so pristine alone: a style the user picked before the limits arrived stays.
        if (style.pristine) style.setValue(defaults.style);
    }

    // Shown in whole units, at least one; the seconds are kept for an untouched control (see `filledSeconds`).
    private fillDuration(field: DurationField, seconds: number): void {
        const { control, seconds: unitSeconds } = DURATION_UNITS[field];
        this.filledSeconds[field] = seconds;
        this.form.controls[control].setValue(toUnits(seconds, unitSeconds));
    }

    /**
     * A duration in seconds: as filled while untouched or not in use (close after on Ongoing), else as typed. Null
     * when neither is known (an Ongoing desk created while the limits failed to load).
     */
    private durationSeconds(field: DurationField): number | null {
        const { control: name, seconds } = DURATION_UNITS[field];
        const control = this.form.controls[name];
        const filled = this.filledSeconds[field];
        if (filled !== undefined && (control.pristine || control.disabled)) return filled;
        return control.disabled || control.value === null ? (filled ?? null) : control.value * seconds;
    }

    /** Contract errors of a flow; a missing flow is one error, any other failure is a toast and keeps the shown ones. */
    private checkContract(graphId: number): Observable<CheckedContract> {
        return this.chatApi.checkContract(graphId).pipe(
            map(({ contract_errors, contract_missing }) => ({
                errors: contract_errors,
                gaps: hasContractGaps(contract_missing) ? { graphId, missing: contract_missing } : null,
            })),
            catchError((error: HttpErrorResponse) => {
                const body = error.error as ChatErrorBody | null;
                if (body?.code === 'unknown_flow') {
                    return of({ errors: [body.message || 'The flow no longer exists.'], gaps: null });
                }
                this.toastService.error(extractHttpErrorMessage(error));
                return EMPTY;
            })
        );
    }

    /** The binding fields, one by one: the duration controls are typed in other units and go out as seconds. */
    private formValues(): ChatBindingInput {
        const raw = this.form.getRawValue();
        const closeAfter = this.durationSeconds('close_after_seconds');
        // Validators.required guarantees the numeric controls, graph_id, the action and the response time are set.
        return {
            name: raw.name,
            bot_display_name: raw.bot_display_name,
            operator_display_name: raw.operator_display_name,
            graph_id: raw.graph_id as number,
            allowed_origins: raw.allowed_origins,
            identity_mode: raw.identity_mode,
            history_window: raw.history_window as number,
            max_message_length: raw.max_message_length as number,
            max_turns: raw.max_turns as number,
            messages_per_minute: raw.messages_per_minute as number,
            token_budget_per_conversation: raw.token_budget_per_conversation as number,
            daily_token_budget: raw.daily_token_budget as number,
            on_budget_exhausted: raw.on_budget_exhausted,
            budget_exhausted_message: raw.budget_exhausted_message,
            handoff_enabled: raw.handoff_enabled,
            style: raw.style,
            response_time_seconds: this.durationSeconds('response_time_seconds') as number,
            on_response_timeout: raw.on_response_timeout as ChatResponseTimeoutAction,
            // Never filled (a create while the limits failed to load): left out, as an empty one would post nothing.
            ...(raw.handback_message === null ? {} : { handback_message: raw.handback_message }),
            ...(closeAfter === null ? {} : { close_after_seconds: closeAfter }),
        };
    }

    /**
     * The chat service's rules for a name visitors see, checked on the name as it will store it (NFC, then stripped):
     * blank is refused (`required`); too long or with a refused character, the reason is `publicName`. The service
     * still decides. While editing, only a typed name is checked against the rules: the PATCH never sends an untouched
     * one, so a name stored before them must not block other edits.
     */
    private publicName(): ValidatorFn {
        return (control: AbstractControl<string>): ValidationErrors | null => {
            const name = normalizePublicName(control.value ?? '');
            if (!name) return { required: true };
            if (!control.dirty && !this.isCreating()) return null;
            const error = publicNameError(name);
            return error ? { publicName: error } : null;
        };
    }

    /** A typed duration above the deployment cap, as `withinCap` does for budgets, worded in the control's unit. */
    private withinDurationCap(field: DurationField): ValidatorFn {
        return (control: AbstractControl<number | null>): ValidationErrors | null => {
            if (!control.dirty || typeof control.value !== 'number') return null;
            const cap = this.limits()?.caps[field];
            if (cap === undefined) return null;
            const max = Math.floor(cap / DURATION_UNITS[field].seconds);
            return control.value > max ? { durationAboveCap: this.durationCapError(field, max) } : null;
        };
    }

    /** Same error as `showCapRefusal` puts for the server's `budget_above_cap`. */
    private withinCap(field: BudgetField): ValidatorFn {
        return (control: AbstractControl<number | null>): ValidationErrors | null => {
            // Only a typed budget is checked: the PATCH never sends an untouched one, so a stored budget above a
            // lowered cap must not block other edits. Runs during form construction too, before `limits` exists.
            if (!control.dirty || typeof control.value !== 'number') return null;
            const cap = this.limits()?.caps[field];
            return cap !== undefined && control.value > cap ? { budgetAboveCap: this.budgetCapError(cap) } : null;
        };
    }

    // Worded here, so `app-validation-errors` says it as it is.
    private budgetCapError(max: number): string {
        return `At most ${formatNumber(max, this.locale)} on this deployment.`;
    }

    // Same as `budgetCapError`, in the unit the duration is typed in.
    private durationCapError(field: DurationField, max: number): string {
        return `At most ${formatNumber(max, this.locale)} ${DURATION_UNITS[field].name} on this deployment.`;
    }
}

// Whole units, at least one: a duration is never shown as zero.
function toUnits(seconds: number, unitSeconds: number): number {
    return Math.max(1, Math.round(seconds / unitSeconds));
}

/**
 * The server's refusals that name one of the dialog's text fields: `bot_name_taken` (the bot name is an operator's
 * alias on the desk) and the `validation_error` entries keyed by a field (a refused character, a name too long).
 * `rest` is every other validation entry, to say in the banner.
 */
function fieldRefusals(body: ChatErrorBody | null): { byField: Map<TextField, string>; rest: string[] } {
    const byField = new Map<TextField, string>();
    const rest: string[] = [];
    if (body?.code === 'bot_name_taken' && body.field === 'bot_display_name') {
        byField.set('bot_display_name', body.message);
    }
    if (body?.code === 'validation_error') {
        for (const { message, key } of body.errors ?? []) {
            // Keyed by the field, or by a path ending in it ("data.bot_display_name").
            const field = TEXT_FIELDS.find((name) => name === key?.split('.').at(-1));
            const text = validationReason(message);
            if (field && !byField.has(field)) byField.set(field, text);
            else if (!field && text) rest.push(text);
        }
    }
    return { byField, rest };
}
