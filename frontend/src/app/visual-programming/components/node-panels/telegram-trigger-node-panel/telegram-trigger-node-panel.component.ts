import { Dialog } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, computed, inject, input, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    ButtonComponent,
    ColumnResizeDividerComponent,
    createColumnWidthState,
    CustomInputComponent,
    HintMessageComponent,
    JsonEditorComponent,
    SelectComponent,
    SelectItem,
    ValidationErrorsComponent,
    WebhookTriggerSelectComponent,
} from '@shared/components';
import { SecretsStorageService } from '@shared/services';
import { tap } from 'rxjs/operators';

import {
    DisplayedTelegramField,
    TelegramTriggerNodeField,
} from '../../../../pages/flows-page/components/flow-visual-programming/models/telegram-trigger.model';
import { ProfileService } from '../../../../services/auth/profile.service';
import { ToastService } from '../../../../services/notifications';
import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { HelpTooltipComponent } from '../../../../shared/components/help-tooltip/help-tooltip.component';
import { TELEGRAM_TRIGGER_FIELDS } from '../../../core/constants/telegram-trigger-fields';
import { TelegramTriggerNodeModel } from '../../../core/models/node.model';
import { BaseSidePanel } from '../../../core/models/node-panel.abstract';
import { WebhookTriggerModel } from '../../../core/models/webhook-trigger.model';
import { LockableFieldComponent } from '../../lockable-field/lockable-field.component';
import { TelegramTriggerEditingDialogComponent } from '../../telegram-trigger-editing-dialog/telegram-trigger-editing-dialog.component';
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
        LockableFieldComponent,
        ValidationErrorsComponent,
        HintMessageComponent,
        WebhookTriggerSelectComponent,
        ColumnResizeDividerComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TelegramTriggerNodePanelComponent extends BaseSidePanel<TelegramTriggerNodeModel> implements OnInit {
    public override readonly isExpanded = input<boolean>(false);
    public readonly graphId = input<number | null>(null);

    private dialog = inject(Dialog);
    private profileService = inject(ProfileService);
    private secretsStorageService = inject(SecretsStorageService);
    private toastService = inject(ToastService);

    protected readonly leftColumnWidth = createColumnWidthState('telegram-trigger-node', 550);

    selectedFields = signal<DisplayedTelegramField[]>([]);
    webhookRegistered = signal<boolean>(false);

    webhookStatusDisplay = computed<WebhookStatus>(() =>
        this.webhookRegistered() ? WebhookStatus.SUCCESS : WebhookStatus.FAIL
    );

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

    readonly secretsReadForbidden = computed(() => this.secretsStorageService.readForbidden());

    secretPlaceholder(): string {
        if (!this.secretsReadForbidden()) return 'Select a secret';
        return this.form?.get('telegram_bot_api_key_secret_id')?.value
            ? 'Secret set — no access'
            : 'No access to secrets';
    }

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
        this.refreshSecrets();
    }

    refreshSecrets(): void {
        this.secretsStorageService
            .getSecrets(true)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => this.clearDeletedSecret(),
                error: () => this.toastService.error('Failed to load secrets.'),
            });
    }

    private clearDeletedSecret(): void {
        if (this.secretsReadForbidden()) return;
        const control = this.form?.get('telegram_bot_api_key_secret_id');
        const id = control?.value;
        if (id == null) return;
        if (this.secretsStorageService.secrets().some((secret) => secret.id === id)) return;
        control?.setValue(null);
        this.toastService.error('The selected secret no longer exists — pick another one.', 5000, 'bottom-right');
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
        const nodeId = this.node().id;
        const lock = this.wsService.lockedNodeFields().get(nodeId)?.get('editing');
        if (lock && lock.user_id !== this.profileService.currentUserSignal()?.id) {
            this.toastService.warning(
                `Fields are being edited by ${lock.display_name ?? 'another user'}`,
                4000,
                'bottom-right'
            );
            return;
        }

        this.wsService.sendNodeLocked(nodeId, 'editing');

        const dialog = this.dialog.open(TelegramTriggerEditingDialogComponent, {
            width: 'calc(100vw - 2rem)',
            height: 'calc(100vh - 2rem)',
            autoFocus: true,
            disableClose: true,
            data: { selectedFields: this.selectedFields(), nodeId },
        });

        dialog.closed
            .pipe(
                tap((selectedFields) => {
                    this.wsService.sendNodeUnlocked(nodeId, 'editing');
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
        return this.node().color || '#685fff';
    }

    protected readonly WebhookStatus = WebhookStatus;
}
