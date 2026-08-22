import { Clipboard, ClipboardModule } from '@angular/cdk/clipboard';
import { CommonModule } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    effect,
    inject,
    input,
    OnChanges,
    OnInit,
    signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import {
    ColumnResizeDividerComponent,
    createColumnWidthState,
    CustomInputComponent,
    SelectComponent,
    SelectItem,
} from '@shared/components';
import { NgrokConfigStorageService, SecretDeclarationIndexService, SecretsStorageService } from '@shared/services';
import { startWith } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { CodeEditorComponent } from '../../../../user-settings-page/tools/custom-tool-editor/code-editor/code-editor.component';
import { NodeType } from '../../../core/enums/node-type';
import { WebhookTriggerNodeModel } from '../../../core/models/node.model';
import { BaseSidePanel } from '../../../core/models/node-panel.abstract';
import { NodeSecretsFieldComponent } from '../../node-secrets-field/node-secrets-field.component';

export const WEBHOOK_NAME_PATTERN = /^[A-Za-z0-9\-._~/]*$/;

@Component({
    standalone: true,
    selector: 'app-webhook-trigger-node-panel',
    imports: [
        ReactiveFormsModule,
        CustomInputComponent,
        CodeEditorComponent,
        CommonModule,
        ClipboardModule,
        SelectComponent,
        MatTooltipModule,
        NodeSecretsFieldComponent,
        ColumnResizeDividerComponent,
    ],
    templateUrl: 'webhook-trigger-node-panel.component.html',
    styleUrls: ['webhook-trigger-node-panel.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class WebhookTriggerNodePanelComponent
    extends BaseSidePanel<WebhookTriggerNodeModel>
    implements OnInit, OnChanges
{
    private readonly ngrokStorageService = inject(NgrokConfigStorageService);
    private readonly clipboard = inject(Clipboard);
    private readonly toastService = inject(ToastService);
    private readonly secretDeclarationIndexService = inject(SecretDeclarationIndexService);
    private readonly secretsStorageService = inject(SecretsStorageService);
    private secretsRestoredForNodeId: string | null = null;

    public override readonly isExpanded = input<boolean>(false);
    public readonly graphId = input<number | null>(null);

    public readonly isCodeEditorFullWidth = signal<boolean>(true);
    protected readonly leftColumnWidth = createColumnWidthState('webhook-trigger-node', 400);
    ngrokConfigsLoading = signal<boolean>(false);
    webhookPath = signal<string | null>(null);
    ngrokConfigId = signal<number | null | undefined>(null);
    loadingTunnel = signal<boolean>(false);
    ngrokConfigs = this.ngrokStorageService.configs;

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

    selectedNgrokConfigUrl = computed<string | null>(() => {
        const config = this.ngrokConfigs().find((c) => c.id === this.ngrokConfigId());

        if (!config || !config.webhook_full_url) return null;

        return this.normalizeWebhookBase(config.webhook_full_url);
    });
    webhookUrlDisplay = computed<string | null>(() => {
        const configUrl = this.selectedNgrokConfigUrl();
        const path = this.webhookPath();

        if (!configUrl || !path) return null;

        return configUrl + path;
    });
    ngrokConfigSelectItems = computed<SelectItem[]>(() => {
        return this.ngrokStorageService.configs().map((c) => ({ name: c.name, value: c.id }));
    });

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

    onNgrokConfigChanged(value: unknown): void {
        if (value == null) {
            this.ngrokConfigId.set(null);
            return;
        }

        const numericValue = typeof value === 'number' ? value : Number(value);
        this.ngrokConfigId.set(Number.isFinite(numericValue) ? numericValue : null);
    }

    initializeForm(): FormGroup {
        const form = this.fb.group({
            node_name: [this.node().node_name, this.createNodeNameValidators()],
            libraries: [this.node().data.python_code.libraries?.join(', ') || ''],
            webhook_trigger_path: [
                this.node().data.webhook_trigger?.path || null,
                [Validators.required, Validators.pattern(WEBHOOK_NAME_PATTERN)],
            ],
            ngrok_webhook_config: [this.node().data.webhook_trigger?.ngrok_webhook_config || null],
        });
        form.get('webhook_trigger_path')
            ?.valueChanges.pipe(
                startWith(form.get('webhook_trigger_path')?.value ?? ''),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((value: string | null) => {
                this.webhookPath.set(value);
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
            input_map: {},
            output_variable_path: null,
            data: {
                ...this.node().data,
                webhook_trigger,
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

    private normalizeWebhookBase(tunnelUrl: string): string {
        if (!tunnelUrl) {
            return '';
        }
        const sanitized = tunnelUrl.endsWith('/') ? tunnelUrl.slice(0, -1) : tunnelUrl;
        return `${sanitized}/webhooks/`;
    }

    getWebhookNameErrorMessage(): string {
        const control = this.form?.get('webhookName');
        if (!control || control.valid || !control.errors) {
            return '';
        }
        if (control.errors['pattern']) {
            return 'Use only letters, numbers, "-", "_", ".", "~", or "/"';
        }
        return '';
    }

    copyWebhookUrl(): void {
        const url = this.webhookUrlDisplay();
        if (!url) return;

        this.clipboard.copy(url);
    }

    toggleCodeEditorFullWidth(): void {
        this.isCodeEditorFullWidth.update((value) => !value);
    }
}
