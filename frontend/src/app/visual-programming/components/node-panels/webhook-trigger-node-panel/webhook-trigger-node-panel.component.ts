import { Clipboard, ClipboardModule } from '@angular/cdk/clipboard';
import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { FormGroup, ReactiveFormsModule } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import { CustomInputComponent, WebhookTriggerSelectComponent } from '@shared/components';

import { CodeEditorComponent } from '../../../../user-settings-page/tools/custom-tool-editor/code-editor/code-editor.component';
import { WebhookTriggerNodeModel } from '../../../core/models/node.model';
import { BaseSidePanel } from '../../../core/models/node-panel.abstract';
import { WebhookTriggerModel } from '../../../core/models/webhook-trigger.model';

@Component({
    standalone: true,
    selector: 'app-webhook-trigger-node-panel',
    imports: [
        ReactiveFormsModule,
        CustomInputComponent,
        CodeEditorComponent,
        CommonModule,
        ClipboardModule,
        MatTooltipModule,
        WebhookTriggerSelectComponent,
    ],
    templateUrl: 'webhook-trigger-node-panel.component.html',
    styleUrls: ['webhook-trigger-node-panel.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class WebhookTriggerNodePanelComponent extends BaseSidePanel<WebhookTriggerNodeModel> {
    private readonly clipboard = inject(Clipboard);

    public override readonly isExpanded = input<boolean>(false);

    public readonly isCodeEditorFullWidth = signal<boolean>(true);

    pythonCode: string = '';
    initialPythonCode: string = '';
    codeEditorHasError: boolean = false;

    copied = signal<boolean>(false);
    selectedTrigger = signal<WebhookTriggerModel | null>(null);
    fullUrl = computed<string | null>(() => this.selectedTrigger()?.live_url ?? null);
    webhookInvalid = computed<boolean>(() => {
        const t = this.selectedTrigger();
        return !!t && !t.live_url;
    });

    onTriggerResolved(trigger: WebhookTriggerModel | null): void {
        this.selectedTrigger.set(trigger);
    }

    constructor() {
        super();
    }

    get activeColor(): string {
        return this.node().color || '#685fff';
    }

    onPythonCodeChange(code: string): void {
        this.pythonCode = code;
        this.notifyExternalChange();
    }

    onCodeErrorChange(hasError: boolean): void {
        this.codeEditorHasError = hasError;
    }

    initializeForm(): FormGroup {
        const form = this.fb.group({
            node_name: [this.node().node_name, this.createNodeNameValidators()],
            libraries: [this.node().data.python_code.libraries?.join(', ') || ''],
            webhook_trigger: [this.node().data.webhook_trigger ?? null],
        });
        this.pythonCode = this.node().data.python_code.code || '';
        this.initialPythonCode = this.pythonCode;
        return form;
    }

    createUpdatedNode(): WebhookTriggerNodeModel {
        const librariesArray = this.form.value.libraries
            ? this.form.value.libraries
                  .split(',')
                  .map((lib: string) => lib.trim())
                  .filter((lib: string) => lib.length > 0)
            : [];

        return {
            ...this.node(),
            node_name: this.form.value.node_name,
            input_map: {},
            output_variable_path: null,
            data: {
                ...this.node().data,
                webhook_trigger: this.form.value.webhook_trigger ?? null,
                python_code: {
                    name: this.node().data.python_code.name || 'Python Code',
                    code: this.pythonCode,
                    entrypoint: 'main',
                    libraries: librariesArray,
                },
            },
        };
    }

    copyWebhookUrl(): void {
        const url = this.fullUrl();
        if (!url) return;

        this.clipboard.copy(url);
        this.copied.set(true);
    }

    toggleCodeEditorFullWidth(): void {
        this.isCodeEditorFullWidth.update((value) => !value);
    }
}
