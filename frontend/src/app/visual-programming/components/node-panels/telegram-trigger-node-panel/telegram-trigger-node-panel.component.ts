import { Dialog } from '@angular/cdk/dialog';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    inject,
    input,
    OnInit,
    signal,
    TemplateRef,
    viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    AppSvgIconComponent,
    ButtonComponent,
    ColumnResizeDividerComponent,
    ConfirmationDialogService,
    createColumnWidthState,
    CustomInputComponent,
    HelpTooltipComponent,
    HintMessageComponent,
    SelectComponent,
    SelectItem,
    ValidationErrorsComponent,
    WebhookTriggerSelectComponent,
} from '@shared/components';
import { NodeType, WebhookTriggerModel, WebhookTriggerWrite } from '@shared/models';
import { SecretsStorageService } from '@shared/services';
import { tap } from 'rxjs/operators';

import { ToastService } from '../../../../services/notifications';
import { TELEGRAM_TRIGGER_FIELDS } from '../../../core/constants/telegram-trigger-fields';
import { IfFlowEditableDirective } from '../../../core/directives/if-flow-editable.directive';
import { TelegramTriggerNodeModel } from '../../../core/models/node.model';
import { BaseSidePanel } from '../../../core/models/node-panel.abstract';
import { DisplayedTelegramField, TelegramTriggerNodeField } from '../../../core/models/telegram-trigger.model';
import { SavedFlowStateService } from '../../../services/saved-flow-state.service';
import { SidePanelService } from '../../../services/side-panel.service';
import {
    buildTelegramSamplePayload,
    formatTestPayload,
    TestPayloadValidator,
    validateTelegramTestPayload,
} from '../../../utils/test-run';
import { TelegramTriggerEditingDialogComponent } from '../../telegram-trigger-editing-dialog/telegram-trigger-editing-dialog.component';
import { RunTestPayloadButtonComponent } from '../shared/run-test-payload-button/run-test-payload-button.component';
import { TestPayloadSectionComponent } from '../shared/test-payload-section/test-payload-section.component';
import { TriggerTestPayloadState, withTestPayload } from '../shared/test-payload-section/trigger-test-payload.state';
import { TelegramWebhookRegistrationComponent } from './telegram-webhook-registration/telegram-webhook-registration.component';
import { WebhookStatus } from './webhook-status.model';

/** aria-label and tooltip of the icon-only action in the payload editor header. */
export const INSERT_EXAMPLE_PAYLOAD_LABEL = 'Insert example from selected fields';
export const INSERT_EXAMPLE_PAYLOAD_ICON = 'create-doc';
export const INSERT_EXAMPLE_NO_FIELDS_REASON = 'Select fields first';

@Component({
    selector: 'app-telegram-trigger-node-panel',
    templateUrl: './telegram-trigger-node-panel.component.html',
    styleUrls: ['./telegram-trigger-node-panel.component.scss'],
    imports: [
        CustomInputComponent,
        ReactiveFormsModule,
        ButtonComponent,
        HelpTooltipComponent,
        AppSvgIconComponent,
        SelectComponent,
        ValidationErrorsComponent,
        HintMessageComponent,
        WebhookTriggerSelectComponent,
        ColumnResizeDividerComponent,
        IfFlowEditableDirective,
        TelegramWebhookRegistrationComponent,
        TestPayloadSectionComponent,
        RunTestPayloadButtonComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TelegramTriggerNodePanelComponent extends BaseSidePanel<TelegramTriggerNodeModel> implements OnInit {
    public override readonly isExpanded = input<boolean>(false);

    /** Rendered by the panel shell in its header. */
    public readonly headerActionsTemplate = viewChild<TemplateRef<unknown>>('headerActionsTpl');

    private dialog = inject(Dialog);
    private secretsStorageService = inject(SecretsStorageService);
    private toastService = inject(ToastService);
    private readonly savedFlowStateService = inject(SavedFlowStateService);
    private readonly sidePanelService = inject(SidePanelService);
    private readonly confirmationDialogService = inject(ConfirmationDialogService);

    protected readonly leftColumnWidth = createColumnWidthState('telegram-trigger-node', 550);

    selectedFields = signal<DisplayedTelegramField[]>([]);
    webhookRegistered = signal<boolean>(false);

    webhookStatusDisplay = computed<WebhookStatus>(() =>
        this.webhookRegistered() ? WebhookStatus.SUCCESS : WebhookStatus.FAIL
    );

    /**
     * This node as last saved to the backend; null until its first save. Not `node()`: switching
     * panels autosaves the form into the canvas node without sending it to the backend.
     */
    protected readonly savedNode = computed<TelegramTriggerNodeModel | null>(() => {
        const savedNode = this.savedFlowStateService.savedNode(this.node().id);
        return savedNode?.type === NodeType.TELEGRAM_TRIGGER ? savedNode : null;
    });
    /**
     * A version preview has no saved state of its own (its SavedFlowStateService is never written),
     * and the live Telegram registration says nothing about an old version, so the check is hidden.
     */
    protected readonly showsWebhookRegistration = !this.flowReadOnly.isPreview;
    protected readonly savedBackendId = computed(() => this.savedNode()?.backendId ?? null);
    protected readonly savedBotKeySecretId = computed(
        () => this.savedNode()?.data.telegram_bot_api_key_secret_id ?? null
    );

    /** The Telegram registration check reads the saved node, so flag edits it cannot reflect yet. */
    protected readonly hasUnsavedConnectionChanges = computed(() => {
        this.dirtyCheckTick();
        const savedNode = this.savedNode();
        if (!this.form || !savedNode) return false;
        const formBotKeySecretId = this.form.get('telegram_bot_api_key_secret_id')?.value ?? null;
        const formWebhookTrigger = this.form.get('webhook_trigger')?.value ?? null;
        return (
            formBotKeySecretId !== (savedNode.data.telegram_bot_api_key_secret_id ?? null) ||
            toWebhookTriggerId(formWebhookTrigger) !== toWebhookTriggerId(savedNode.data.webhook_trigger)
        );
    });

    /**
     * Mirrors the backend's check of a test payload against the fields picked on this node. None in
     * read-only mode (viewer, version preview): nothing can be run or fixed there, so only JSON errors show.
     */
    protected readonly testPayloadValidator = computed<TestPayloadValidator | null>(() => {
        if (this.isReadOnly()) return null;
        const pickedFields = this.selectedFields();
        return (payload) => validateTelegramTestPayload(payload, pickedFields);
    });
    protected readonly testPayload = new TriggerTestPayloadState(
        'telegram-trigger',
        computed(() => this.node().id),
        this.testPayloadValidator
    );

    /** An example of no fields would be `{}`. */
    protected readonly insertExampleDisabledReason = computed(() =>
        this.selectedFields().length === 0 ? INSERT_EXAMPLE_NO_FIELDS_REASON : null
    );

    protected readonly insertExampleLabel = INSERT_EXAMPLE_PAYLOAD_LABEL;
    protected readonly insertExampleIcon = INSERT_EXAMPLE_PAYLOAD_ICON;

    secretItems = computed<SelectItem[]>(() =>
        this.secretsStorageService.secrets().map((secret) => ({
            name: secret.name,
            value: secret.id,
            tip: this.secretsStorageService.maskTail(secret.tail),
        }))
    );

    constructor() {
        super();
    }

    ngOnInit() {
        this.secretsStorageService
            .getSecrets()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                error: () => this.toastService.error('Failed to load secrets.'),
            });
    }

    private setSelectedFields(nodeFields: TelegramTriggerNodeField[]): void {
        const selectedFields = nodeFields.map((nodeField: TelegramTriggerNodeField) => {
            const parentFields = TELEGRAM_TRIGGER_FIELDS[nodeField.parent];
            const fieldWithModel = parentFields.find((f) => f.field_name === nodeField.field_name)!;

            return {
                ...fieldWithModel,
                parent: nodeField.parent,
                variable_path: nodeField.variable_path,
            };
        });

        this.selectedFields.set(selectedFields);
    }

    initializeForm(): FormGroup {
        this.setSelectedFields(this.node().data.fields);
        this.testPayload.reset(this.initialTestPayloadText());
        return this.fb.group({
            node_name: [this.node().node_name, this.createNodeNameValidators()],
            telegram_bot_api_key_secret_id: [
                this.node().data.telegram_bot_api_key_secret_id ?? null,
                Validators.required,
            ],
            webhook_trigger: [this.node().data.webhook_trigger ?? null],
            fields: [this.node().data.fields || []],
        });
    }

    createUpdatedNode(): TelegramTriggerNodeModel {
        return {
            ...this.node(),
            node_name: this.form.value.node_name,

            data: {
                ...this.node().data,
                telegram_bot_api_key_secret_id: this.form.value.telegram_bot_api_key_secret_id,
                webhook_trigger: this.form.value.webhook_trigger ?? null,
                fields: this.form.value.fields,
                test_payload: this.testPayload.payloadToSave(this.node().data.test_payload),
            },
        };
    }

    /** An invalid test payload edit was left out of the saved node (on close, autosave or Ctrl+S), so say so. */
    protected override afterNodeSaved(): void {
        this.testPayload.reportInvalidEditNotSaved();
    }

    /**
     * On close / autosave the payload does not depend on the other fields: an edit of it is saved
     * alone, the rest stays unsaved.
     */
    protected override saveWhenFormInvalid(): TelegramTriggerNodeModel | null {
        const payload = this.testPayload.editToSaveAlone(this.baselineNode().data.test_payload);
        if (payload === null) return null;
        this.updateBaseline((baseline) => withTestPayload(baseline, payload));
        this.testPayload.reportSavedAlone(this.isDirty());
        return withTestPayload(this.node(), payload);
    }

    protected override hasUnsavedEditsOutsideNode(): boolean {
        return this.testPayload.hasUnsavedInvalidEdit();
    }

    protected onTestPayloadTextChange(text: string): void {
        this.testPayload.edit(text);
        this.notifyExternalChange();
    }

    /**
     * Replaces the payload with an example of the picked fields, nested as the runtime update is. Asks
     * first when that would drop a payload the user wrote (edited now or saved before).
     */
    protected insertExamplePayload(): void {
        if (this.isReadOnly() || this.insertExampleDisabledReason() !== null) return;
        if (!this.wouldReplaceUserPayload(this.examplePayloadText())) {
            this.applyExamplePayload();
            return;
        }
        this.confirmationDialogService
            .confirm({
                title: 'Replace the test payload?',
                message: 'The current test payload will be replaced with an example built from the selected fields.',
                confirmText: 'Replace',
                cancelText: 'Cancel',
                type: 'warning',
            })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((result) => {
                if (result === true) this.applyExamplePayload();
            });
    }

    protected expandPanel(): void {
        this.sidePanelService.requestExpand();
    }

    onEditing(): void {
        const dialog = this.dialog.open(TelegramTriggerEditingDialogComponent, {
            width: 'calc(100vw - 2rem)',
            height: 'calc(100vh - 2rem)',
            autoFocus: true,
            disableClose: true,
            data: this.selectedFields(),
        });

        dialog.closed
            .pipe(
                tap((selectedFields) => {
                    if (!selectedFields) return;

                    const fields = selectedFields as TelegramTriggerNodeField[];
                    this.setSelectedFields(fields);
                    this.updateFieldsControl(fields);
                    // A sample that was never edited follows the picked fields.
                    if (!this.testPayload.isEdited()) {
                        this.testPayload.reset(this.initialTestPayloadText());
                    }
                }),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe();
    }

    onTriggerResolved(trigger: WebhookTriggerModel | null): void {
        this.webhookRegistered.set(!!trigger?.live_url);
    }

    /** The saved payload, or a sample of the picked fields while none is saved. */
    private initialTestPayloadText(): string {
        // A deliberately saved `{}` is indistinguishable from "never set", so the sample shows again.
        const savedPayload = this.node().data.test_payload ?? {};
        const shownPayload =
            Object.keys(savedPayload).length > 0 ? savedPayload : buildTelegramSamplePayload(this.selectedFields());
        return formatTestPayload(shownPayload);
    }

    private examplePayloadText(): string {
        return formatTestPayload(buildTelegramSamplePayload(this.selectedFields()));
    }

    private applyExamplePayload(): void {
        this.testPayload.replace(this.examplePayloadText());
        this.notifyExternalChange();
    }

    /** Anything but an empty payload or this very example is the user's: replacing it needs a yes. */
    private wouldReplaceUserPayload(exampleText: string): boolean {
        const text = this.testPayload.text();
        if (text.trim() === '' || text === exampleText) return false;
        const payload = this.testPayload.check().payload;
        if (payload === null) return true;
        return Object.keys(payload).length > 0 && formatTestPayload(payload) !== exampleText;
    }

    private updateFieldsControl(items: TelegramTriggerNodeField[]) {
        const control = this.form.get('fields');
        control?.setValue(items);
    }

    get activeColor(): string {
        return 'var(--accent-color)';
    }

    protected readonly WebhookStatus = WebhookStatus;
}

/** Loaded nodes may carry the nested trigger object instead of its id. */
function toWebhookTriggerId(webhookTrigger: WebhookTriggerWrite | null): number | null {
    if (webhookTrigger == null) return null;
    return typeof webhookTrigger === 'number' ? webhookTrigger : (webhookTrigger.id ?? null);
}
