import { Dialog } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, computed, inject, input, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    AppSvgIconComponent,
    ButtonComponent,
    ColumnResizeDividerComponent,
    createColumnWidthState,
    CustomInputComponent,
    HelpTooltipComponent,
    HintMessageComponent,
    JsonEditorComponent,
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
import { TelegramTriggerEditingDialogComponent } from '../../telegram-trigger-editing-dialog/telegram-trigger-editing-dialog.component';
import { TelegramWebhookRegistrationComponent } from './telegram-webhook-registration/telegram-webhook-registration.component';
import { WebhookStatus } from './webhook-status.model';

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
        JsonEditorComponent,
        SelectComponent,
        ValidationErrorsComponent,
        HintMessageComponent,
        WebhookTriggerSelectComponent,
        ColumnResizeDividerComponent,
        IfFlowEditableDirective,
        TelegramWebhookRegistrationComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TelegramTriggerNodePanelComponent extends BaseSidePanel<TelegramTriggerNodeModel> implements OnInit {
    public override readonly isExpanded = input<boolean>(false);

    private dialog = inject(Dialog);
    private secretsStorageService = inject(SecretsStorageService);
    private toastService = inject(ToastService);
    private readonly savedFlowStateService = inject(SavedFlowStateService);

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

    jsonValues = computed(() => {
        const checkedItemsObj = this.selectedFields().reduce<Record<string, unknown>>((acc, field) => {
            acc[field.field_name] = field.model;
            return acc;
        }, {});

        return JSON.stringify(checkedItemsObj, null, 2);
    });

    secretItems = computed<SelectItem[]>(() =>
        this.secretsStorageService.secrets().map((secret) => ({
            name: secret.name,
            value: secret.id,
            tip: this.secretsStorageService.maskTail(secret.tail),
        }))
    );

    editorOptions: Record<string, unknown> = {
        lineNumbers: 'off',
        theme: 'vs-dark',
        language: 'json',
        automaticLayout: true,
        minimap: { enabled: false },
        scrollBeyondLastLine: false,
        wordWrap: 'on',
        wrappingIndent: 'indent',
        wordWrapBreakAfterCharacters: ',',
        wordWrapBreakBeforeCharacters: '}]',
        tabSize: 2,
        readOnly: true,
    };

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
            },
        };
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
                }),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe();
    }

    onTriggerResolved(trigger: WebhookTriggerModel | null): void {
        this.webhookRegistered.set(!!trigger?.live_url);
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
