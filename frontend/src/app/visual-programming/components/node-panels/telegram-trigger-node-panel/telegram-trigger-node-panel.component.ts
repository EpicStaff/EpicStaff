import { Dialog } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    ButtonComponent,
    ColumnResizeDividerComponent,
    createColumnWidthState,
    CustomInputComponent,
    JsonEditorComponent,
    WebhookTriggerSelectComponent,
} from '@shared/components';
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
import { WebhookTriggerModel } from '../../../core/models/webhook-trigger.model';
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
        WebhookTriggerSelectComponent,
        ColumnResizeDividerComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TelegramTriggerNodePanelComponent extends BaseSidePanel<TelegramTriggerNodeModel> {
    public override readonly isExpanded = input<boolean>(false);

    private dialog = inject(Dialog);

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

    onTriggerResolved(trigger: WebhookTriggerModel | null): void {
        this.webhookRegistered.set(!!trigger?.live_url);
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
            telegram_bot_api_key: [this.node().data.telegram_bot_api_key || '', Validators.required],
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
