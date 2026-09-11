import { Clipboard, ClipboardModule } from '@angular/cdk/clipboard';
import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { FormGroup, ReactiveFormsModule } from '@angular/forms';
import {
    ColumnResizeDividerComponent,
    createColumnWidthState,
    CustomInputComponent,
    WebhookTriggerSelectComponent,
} from '@shared/components';
import { ResourceCode } from '@shared/models';
import { SecretsStorageService } from '@shared/services';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { CodeEditorComponent } from '../../../../user-settings-page/tools/custom-tool-editor/code-editor/code-editor.component';
import { WebhookTriggerNodeModel } from '../../../core/models/node.model';
import { BaseSidePanel } from '../../../core/models/node-panel.abstract';
import { WebhookTriggerModel } from '../../../core/models/webhook-trigger.model';
import { NodeSecretsFieldComponent } from '../../node-secrets-field/node-secrets-field.component';

@Component({
    selector: 'app-webhook-trigger-node-panel',
    imports: [
        ReactiveFormsModule,
        CustomInputComponent,
        CodeEditorComponent,
        ClipboardModule,
        NodeSecretsFieldComponent,
        WebhookTriggerSelectComponent,
        ColumnResizeDividerComponent,
    ],
    templateUrl: 'webhook-trigger-node-panel.component.html',
    styleUrls: ['webhook-trigger-node-panel.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class WebhookTriggerNodePanelComponent extends BaseSidePanel<WebhookTriggerNodeModel> {
    private readonly clipboard = inject(Clipboard);
    private readonly secretsStorageService = inject(SecretsStorageService);
    private readonly permissionsService = inject(PermissionsService);

    public override readonly isExpanded = input<boolean>(false);
    public readonly graphId = input<number | null>(null);

    public readonly isFormCollapsed = signal<boolean>(false);
    protected readonly leftColumnWidth = createColumnWidthState('webhook-trigger-node', 406);

    pythonCode: string = '';
    initialPythonCode: string = '';
    codeEditorHasError: boolean = false;
    public readonly canEditSecrets = computed(() => this.permissionsService.canEditSecrets(ResourceCode.Flows));
    public readonly secretsTooltip = computed(() =>
        this.canEditSecrets()
            ? "Secrets this webhook's code can access at runtime — create and manage secrets under Settings → Secrets. Press Ctrl+Space in the code editor to insert get_secret('name')."
            : "Secrets already assigned to this webhook's code. You don't have permission to change which secrets are selected."
    );
    public readonly selectedSecretIds = signal<number[]>([]);
    public readonly secretNames = computed(() =>
        this.canEditSecrets()
            ? this.secretsStorageService.namesForIds(this.selectedSecretIds())
            : (this.node().data.python_code.secret_names ?? [])
    );

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

    // Fixed to the accent purple regardless of the node's own (green) identity color --
    // this panel's field highlights aren't meant to track the node's canvas color.
    get activeColor(): string {
        return 'var(--accent-color)';
    }

    onPythonCodeChange(code: string): void {
        this.pythonCode = code;
        this.notifyExternalChange();
    }

    onCodeErrorChange(hasError: boolean): void {
        this.codeEditorHasError = hasError;
    }

    onSecretsChange(values: number[]): void {
        this.selectedSecretIds.set(values);
        this.notifyExternalChange();
    }

    initializeForm(): FormGroup {
        const form = this.fb.group({
            node_name: [this.node().node_name, this.createNodeNameValidators()],
            libraries: [this.node().data.python_code.libraries?.join(', ') || ''],
            webhook_trigger: [this.node().data.webhook_trigger ?? null],
        });
        this.pythonCode = this.node().data.python_code.code || '';
        this.initialPythonCode = this.pythonCode;
        this.selectedSecretIds.set(this.node().data.python_code.secret_ids ?? []);
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
                    secret_ids: this.selectedSecretIds(),
                    secret_names: this.secretNames(),
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
}
