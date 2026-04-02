import { Dialog } from '@angular/cdk/dialog';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    inject,
    input,
    OnChanges,
    OnInit,
    signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    AppIconComponent,
    ButtonComponent,
    CustomInputComponent,
    JsonEditorComponent,
    SelectComponent,
    SelectItem,
} from '@shared/components';
import { MATERIAL_FORMS } from '@shared/material-forms';
import { startWith } from 'rxjs';
import { tap } from 'rxjs/operators';

import { NgrokConfigStorageService } from '../../../../features/settings-dialog/services/ngrok-config/ngrok-config-storage.service';
import {
    DisplayedTelegramField,
    TelegramTriggerNodeField,
} from '../../../../pages/flows-page/components/flow-visual-programming/models/telegram-trigger.model';
import { WebhookStatus } from '../../../../pages/flows-page/components/flow-visual-programming/models/webhook.model';
import { ToastService } from '../../../../services/notifications';
import { TELEGRAM_TRIGGER_FIELDS } from '../../../core/constants/telegram-trigger-fields';
import { TelegramTriggerNodeModel } from '../../../core/models/node.model';
import { BaseSidePanel } from '../../../core/models/node-panel.abstract';
import { TelegramTriggerEditingDialogComponent } from '../../telegram-trigger-editing-dialog/telegram-trigger-editing-dialog.component';
import { WEBHOOK_NAME_PATTERN } from '../webhook-trigger-node-panel/webhook-trigger-node-panel.component';

@Component({
    selector: 'app-telegram-trigger-node-panel',
    templateUrl: './telegram-trigger-node-panel.component.html',
    styleUrls: ['./telegram-trigger-node-panel.component.scss'],
    imports: [
        CustomInputComponent,
        ReactiveFormsModule,
        ButtonComponent,
        AppIconComponent,
        MATERIAL_FORMS,
        JsonEditorComponent,
        SelectComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TelegramTriggerNodePanelComponent
    extends BaseSidePanel<TelegramTriggerNodeModel>
    implements OnInit, OnChanges
{
    public readonly isExpanded = input<boolean>(false);

    private dialog = inject(Dialog);
    private destroyRef = inject(DestroyRef);
    private toastService = inject(ToastService);
    private ngrokStorageService = inject(NgrokConfigStorageService);

    ngrokConfigs = this.ngrokStorageService.configs;
    ngrokConfigsLoading = signal<boolean>(false);
    ngrokConfigId = signal<number | null | undefined>(null);
    selectedFields = signal<DisplayedTelegramField[]>([]);
    webhookPath = signal<string | null>(null);

    selectedNgrokConfigValid = computed<boolean>(() => {
        const config = this.ngrokConfigs().find((c) => c.id === this.ngrokConfigId());

        if (!config || !config.webhook_full_url) return false;

        return true;
    });
    webhookStatusDisplay = computed<WebhookStatus>(() => {
        const configValid = this.selectedNgrokConfigValid();
        const path = this.webhookPath();
        if (!configValid || !path) return WebhookStatus.FAIL;
        return WebhookStatus.SUCCESS;
    });

    jsonValues = computed(() => {
        const checkedItemsObj = this.selectedFields().reduce<Record<string, unknown>>((acc, field) => {
            acc[field.field_name] = field.model;
            return acc;
        }, {});

        return JSON.stringify(checkedItemsObj, null, 2);
    });
    ngrokConfigSelectItems = computed<SelectItem[]>(() => {
        return this.ngrokStorageService.configs().map((c) => ({ name: c.name, value: c.id }));
    });

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
        this.getNgrokConfigs();
    }

    ngOnChanges() {
        const id = this.node().data.webhook_trigger?.ngrok_webhook_config;
        this.ngrokConfigId.set(id);
    }

    private getNgrokConfigs(): void {
        this.ngrokConfigsLoading.set(true);
        this.ngrokStorageService
            .getConfigs()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => {},
                error: () => this.toastService.error('Failed to load Ngrok configs.'),
                complete: () => this.ngrokConfigsLoading.set(false),
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
        const form = this.fb.group({
            node_name: [this.node().node_name, this.createNodeNameValidators()],
            telegram_bot_api_key: [this.node().data.telegram_bot_api_key || '', Validators.required],
            webhook_trigger_path: [
                this.node().data.webhook_trigger?.path || null,
                [Validators.required, Validators.pattern(WEBHOOK_NAME_PATTERN)],
            ],
            ngrok_webhook_config: [this.node().data.webhook_trigger?.ngrok_webhook_config || null],
            fields: [this.node().data.fields || []],
        });
        form.get('webhook_trigger_path')
            ?.valueChanges.pipe(
                startWith(form.get('webhook_trigger_path')?.value ?? ''),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((value: string | null) => {
                this.webhookPath.set(value);
            });

        return form;
    }

    createUpdatedNode(): TelegramTriggerNodeModel {
        const webhookTriggerPath = this.form.value.webhook_trigger_path;

        const webhook_trigger = webhookTriggerPath
            ? {
                  path: webhookTriggerPath,
                  ngrok_webhook_config: this.form.value.ngrok_webhook_config,
              }
            : null;

        return {
            ...this.node(),
            node_name: this.form.value.node_name,

            data: {
                ...this.node().data,
                telegram_bot_api_key: this.form.value.telegram_bot_api_key,
                webhook_trigger,
                fields: this.form.value.fields,
            },
        };
    }

    getTelegramKeyErrorMessage(): string {
        const control = this.form?.get('telegram_bot_api_key');
        if (!control || control.valid || !control.errors) {
            return '';
        }
        if (control.errors['required']) {
            return 'This field is required';
        }
        return '';
    }

    onEditing(): void {
        this.form.value.fields;
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

    private updateFieldsControl(items: TelegramTriggerNodeField[]) {
        const control = this.form.get('fields');
        control?.setValue(items);
    }

    onNgrokConfigChanged(value: unknown): void {
        if (value == null) {
            this.ngrokConfigId.set(null);
            return;
        }

        const numericValue = typeof value === 'number' ? value : Number(value);
        this.ngrokConfigId.set(Number.isFinite(numericValue) ? numericValue : null);
    }

    get activeColor(): string {
        return this.node().color || '#685fff';
    }

    protected readonly WebhookStatus = WebhookStatus;
}
