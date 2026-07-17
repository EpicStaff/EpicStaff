import { Dialog } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, computed, inject, input, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    ButtonComponent,
    CustomInputComponent,
    JsonEditorComponent,
    WebhookTriggerFieldComponent,
} from '@shared/components';
import { MATERIAL_FORMS } from '@shared/material-forms';
import { startWith } from 'rxjs';
import { tap } from 'rxjs/operators';

import {
    DisplayedTelegramField,
    TelegramTriggerNodeField,
} from '../../../../pages/flows-page/components/flow-visual-programming/models/telegram-trigger.model';
import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { HelpTooltipComponent } from '../../../../shared/components/help-tooltip/help-tooltip.component';
import { TELEGRAM_TRIGGER_FIELDS } from '../../../core/constants/telegram-trigger-fields';
import { TelegramTriggerNodeModel } from '../../../core/models/node.model';
import { BaseSidePanel } from '../../../core/models/node-panel.abstract';
import { WebhookTriggerWrite } from '../../../core/models/webhook-trigger.model';
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
        MATERIAL_FORMS,
        JsonEditorComponent,
        WebhookTriggerFieldComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TelegramTriggerNodePanelComponent extends BaseSidePanel<TelegramTriggerNodeModel> implements OnInit {
    public override readonly isExpanded = input<boolean>(false);

    private dialog = inject(Dialog);

    selectedFields = signal<DisplayedTelegramField[]>([]);
    webhookConfigured = signal<boolean>(false);

    webhookStatusDisplay = computed<WebhookStatus>(() =>
        this.webhookConfigured() ? WebhookStatus.SUCCESS : WebhookStatus.FAIL
    );

    jsonValues = computed(() => {
        const checkedItemsObj = this.selectedFields().reduce<Record<string, unknown>>((acc, field) => {
            acc[field.field_name] = field.model;
            return acc;
        }, {});

        return JSON.stringify(checkedItemsObj, null, 2);
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
        this.webhookConfigured.set(this.isConfigured(this.node().data.webhook_trigger));
    }

    private isConfigured(value: WebhookTriggerWrite | null): boolean {
        if (value == null) return false;
        if (typeof value === 'number') return true;
        return !!value.path && !!value.provider_type;
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
            webhook_trigger: [this.node().data.webhook_trigger ?? null],
            fields: [this.node().data.fields || []],
        });
        form.get('webhook_trigger')
            ?.valueChanges.pipe(
                startWith(form.get('webhook_trigger')?.value ?? null),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((value) => this.webhookConfigured.set(this.isConfigured(value as WebhookTriggerWrite | null)));

        return form;
    }

    createUpdatedNode(): TelegramTriggerNodeModel {
        return {
            ...this.node(),
            node_name: this.form.value.node_name,

            data: {
                ...this.node().data,
                telegram_bot_api_key: this.form.value.telegram_bot_api_key,
                webhook_trigger: this.form.value.webhook_trigger ?? null,
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

    get activeColor(): string {
        return this.node().color || '#685fff';
    }

    protected readonly WebhookStatus = WebhookStatus;
}
