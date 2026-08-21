import { Clipboard, ClipboardModule } from '@angular/cdk/clipboard';
import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, effect, inject, input, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormGroup, ReactiveFormsModule } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import {
    ColumnResizeDividerComponent,
    createColumnWidthState,
    CustomInputComponent,
    WebhookTriggerSelectComponent,
} from '@shared/components';
import { SecretDeclarationIndexService, SecretsStorageService } from '@shared/services';

import { CodeEditorComponent } from '../../../../user-settings-page/tools/custom-tool-editor/code-editor/code-editor.component';
import { NodeType } from '../../../core/enums/node-type';
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
        CommonModule,
        ClipboardModule,
        MatTooltipModule,
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
    private readonly secretDeclarationIndexService = inject(SecretDeclarationIndexService);
    private readonly secretsStorageService = inject(SecretsStorageService);
    private secretsRestoredForNodeId: string | null = null;

    public override readonly isExpanded = input<boolean>(false);
    public readonly graphId = input<number | null>(null);

    public readonly isCodeEditorFullWidth = signal<boolean>(true);
    protected readonly leftColumnWidth = createColumnWidthState('webhook-trigger-node', 400);

    pythonCode: string = '';
    initialPythonCode: string = '';
    codeEditorHasError: boolean = false;
    public readonly selectedSecretIds = signal<number[]>([]);
    public readonly secretNames = computed(() => {
        const selected = new Set(this.selectedSecretIds());
        return this.secretsStorageService
            .secrets()
            .filter((secret) => selected.has(secret.id))
            .map((secret) => secret.name);
    });

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
        effect(() => {
            const graphId = this.graphId();
            const node = this.node();
            if (graphId == null || this.secretsRestoredForNodeId === node.id) return;
            this.secretsRestoredForNodeId = node.id;
            if (node.data.python_code.secret_ids !== undefined) return;

            const nodeId = node.id;
            const nodeName = node.node_name;
            this.secretDeclarationIndexService
                .getIndex()
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe((index) => {
                    if (this.node().id !== nodeId) return;
                    const declared = this.secretDeclarationIndexService.lookup(
                        index,
                        graphId,
                        nodeName,
                        NodeType.WEBHOOK_TRIGGER,
                        'python_code'
                    );
                    if (declared.length) {
                        this.selectedSecretIds.set(declared);
                        // Patch only secret_ids into the baseline — resetBaseline() would
                        // recompute the whole node snapshot and bake in any other field the
                        // user edited while this async lookup was in flight.
                        if (this.initialNodeSnapshot) {
                            const snapshot = JSON.parse(this.initialNodeSnapshot);
                            snapshot.data.python_code.secret_ids = [...declared].sort();
                            this.initialNodeSnapshot = JSON.stringify(snapshot);
                            this.notifyExternalChange();
                        }
                    }
                });
        });
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
