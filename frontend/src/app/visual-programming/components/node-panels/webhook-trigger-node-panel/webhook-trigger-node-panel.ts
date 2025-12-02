import { ChangeDetectionStrategy, ChangeDetectorRef, Component, DestroyRef, inject, input } from '@angular/core';
import { ReactiveFormsModule, FormGroup, Validators } from '@angular/forms';
import { WebhookTriggerNodeModel } from '../../../core/models/node.model';
import { BaseSidePanel } from '../../../core/models/node-panel.abstract';
import { CustomInputComponent } from '../../../../shared/components/form-input/form-input.component';
import { CodeEditorComponent } from '../../../../user-settings-page/tools/custom-tool-editor/code-editor/code-editor.component';
import { CommonModule } from '@angular/common';
import { WebhookTriggerNodeService } from '../../../../pages/flows-page/components/flow-visual-programming/services/webhook-trigger.service';
import { Clipboard, ClipboardModule } from '@angular/cdk/clipboard';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { startWith } from 'rxjs';

const WEBHOOK_NAME_PATTERN = /^[A-Za-z0-9\-._~/]*$/;

@Component({
    standalone: true,
    selector: 'app-webhook-trigger-node-panel',
    imports: [
        ReactiveFormsModule,
        CustomInputComponent,
        CodeEditorComponent,
        CommonModule,
        ClipboardModule,
    ],
    template: `
        <div class="panel-container">
            <div class="panel-content">
                <form [formGroup]="form" class="form-container">
                    <div class="form-layout" [class.expanded]="isExpanded()" [class.collapsed]="!isExpanded()">
                        <div class="form-fields">
                            <app-custom-input
                                label="Node Name"
                                tooltipText="The unique identifier used to reference this Python node. This name must be unique within the flow."
                                formControlName="node_name"
                                placeholder="Enter node name"
                                [activeColor]="activeColor"
                                [errorMessage]="getNodeNameErrorMessage()"
                            ></app-custom-input>

                            <app-custom-input
                                label="Webhook Name"
                                tooltipText="Only enter the webhook name. The base URL is shown below."
                                formControlName="webhookName"
                                placeholder="Enter webhook name"
                                [activeColor]="activeColor"
                                [errorMessage]="getWebhookNameErrorMessage()"
                            ></app-custom-input>
                            <div class="webhook-url-display">
                                @if (webhookUrlDisplay; as url) {
                                    <span class="webhook-url-text" [style.color]="activeColor">
                                        {{ url }}
                                    </span>
                                    <button
                                        type="button"
                                        class="copy-button"
                                        (click)="copyWebhookUrl()"
                                        [disabled]="!url"
                                        aria-label="Copy webhook URL"
                                    >
                                        <span class="copy-icon" aria-hidden="true"></span>
                                        <span>Copy</span>
                                    </button>
                                } @else {
                                    @if (tunnelErrorMessage) {
                                        <div class="webhook-url-error">
                                            {{ tunnelErrorMessage }}
                                        </div>
                                    } @else {
                                        <div class="webhook-url-placeholder">Fetching tunnel URL...</div>
                                    }
                                }
                            </div>
                            <app-custom-input
                                label="Libraries"
                                tooltipText="Python libraries required by this code (comma-separated). For example: requests, pandas, numpy"
                                formControlName="libraries"
                                placeholder="Enter libraries (e.g., requests, pandas, numpy)"
                                [activeColor]="activeColor"
                            ></app-custom-input>
                        </div>
                        <div class="code-editor-section">
                            <app-code-editor
                                [pythonCode]="pythonCode"
                                (pythonCodeChange)="onPythonCodeChange($event)"
                                (errorChange)="onCodeErrorChange($event)"
                            ></app-code-editor>
                        </div>
                    </div>
                </form>
            </div>
        </div>
    `,
    styles: [
        `
            @use '../../../styles/node-panel-mixins.scss' as mixins;

            .panel-container {
                display: flex;
                flex-direction: column;
                height: 100%;
                min-height: 0;
            }

            .panel-content {
                @include mixins.panel-content;
                height: 100%;
                min-height: 0;
                display: flex;
                flex-direction: column;
            }

            .section-header {
                @include mixins.section-header;
            }

            .form-container {
                @include mixins.form-container;
                height: 100%;
                min-height: 0;
                display: flex;
                flex-direction: column;
            }

            .form-layout {
                height: 100%;
                min-height: 0;

                &.expanded {
                    display: flex;
                    gap: 1rem;
                    height: 100%;
                }

                &.collapsed {
                    display: flex;
                    flex-direction: column;
                }
            }

            .form-fields {
                display: flex;
                flex-direction: column;
                
                .expanded & {
                    flex: 0 0 400px;
                    max-width: 400px;
                    height: 100%;
                    overflow-y: auto;
                }
            }

            .btn-primary {
                @include mixins.primary-button;
            }

            .btn-secondary {
                @include mixins.secondary-button;
            }

            .code-editor-section {
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 8px;
                overflow: hidden;
                display: flex;
                flex-direction: column;

                .expanded & {
                    flex: 1;
                    height: 100%;
                    min-height: 0;
                }

                .collapsed & {
                    height: 300px;
                }
            }

            .webhook-url-display {
                font-size: 13px;
                color: rgba(255, 255, 255, 0.65);
                word-break: break-all;
                display: flex;
                align-items: center;
                gap: 12px;
                margin-top: 6px;
                margin-bottom: 16px;
            }

            .webhook-url-text {
                flex: 1;
            }

            .webhook-url-placeholder {
                color: rgba(255, 255, 255, 0.5);
            }

            .webhook-url-error {
                color: #ef4444;
            }

            .copy-button {
                border: 1px solid rgba(255, 255, 255, 0.15);
                background: transparent;
                color: rgba(255, 255, 255, 0.8);
                padding: 4px 8px;
                border-radius: 4px;
                font-size: 12px;
                cursor: pointer;
                transition: border-color 0.2s ease, color 0.2s ease;
                display: flex;
                align-items: center;
            }

            .copy-button:hover:not(:disabled) {
                border-color: var(--active-color, #685fff);
                color: white;
            }

            .copy-button:disabled {
                opacity: 0.5;
                cursor: not-allowed;
            }

            .copy-icon {
                position: relative;
                width: 14px;
                height: 10px;
                display: inline-block;
                margin-right: 6px;
            }

            .copy-icon::before,
            .copy-icon::after {
                content: '';
                position: absolute;
                width: 12px;
                height: 12px;
                border: 1px solid currentColor;
                border-radius: 2px;
                background: transparent;
            }

            .copy-icon::before {
                top: 0;
                left: 0;
            }

            .copy-icon::after {
                top: -3px;
                left: 3px;
                opacity: 0.7;
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class WebhookTriggerNodePanelComponent extends BaseSidePanel<WebhookTriggerNodeModel> {
    public readonly isExpanded = input<boolean>(false);

    pythonCode: string = '';
    initialPythonCode: string = '';
    codeEditorHasError: boolean = false;
    tunnelUrl: string = '';
    tunnelErrorMessage: string = '';
    webhookUrlBase: string = '';
    webhookUrlDisplay: string = '';

    private readonly destroyRef = inject(DestroyRef);

    constructor(
        private webhookTriggerNodeService: WebhookTriggerNodeService,
        private cdr: ChangeDetectorRef,
        private clipboard: Clipboard
    ) {
        super();
        this.webhookTriggerNodeService.getTunnelUrl().subscribe({
            next: (response) => {
                if (response?.status === 'success' && response.tunnel_url) {
                    this.tunnelUrl = response.tunnel_url;
                    this.webhookUrlBase = this.normalizeWebhookBase(response.tunnel_url);
                    this.tunnelErrorMessage = '';
                    this.updateWebhookUrlDisplay(this.form?.get('webhookName')?.value);
                } else {
                    this.tunnelErrorMessage = 'set your tunnel in .env configurations';
                    this.webhookUrlBase = '';
                    this.updateWebhookUrlDisplay(this.form?.get('webhookName')?.value);
                }
                this.cdr.markForCheck();
            },
            error: () => {
                this.tunnelErrorMessage = 'set your tunnel in .env configurations';
                this.webhookUrlBase = '';
                this.updateWebhookUrlDisplay(this.form?.get('webhookName')?.value);
                this.cdr.markForCheck();
            },
        });
    }

    get activeColor(): string {
        return this.node().color || '#685fff';
    }

    onPythonCodeChange(code: string): void {
        this.pythonCode = code;
    }

    onCodeErrorChange(hasError: boolean): void {
        this.codeEditorHasError = hasError;
    }

    initializeForm(): FormGroup {
        const form = this.fb.group({
            node_name: [this.node().node_name, this.createNodeNameValidators()],
            libraries: [this.node().data.python_code.libraries?.join(', ') || ''],
            webhookName: [
                this.extractWebhookName(this.node().data.webhook_trigger_path || ''),
                [Validators.pattern(WEBHOOK_NAME_PATTERN)],
            ],
        });
        form
            .get('webhookName')
            ?.valueChanges.pipe(
                startWith(form.get('webhookName')?.value ?? ''),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((value: string | null) => {
                this.updateWebhookUrlDisplay(value ?? '');
                this.cdr.markForCheck();
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
                webhook_trigger_path: (this.form.value.webhookName || '').trim(),
                python_code: {
                    name: this.node().data.python_code.name || 'Python Code',
                    code: this.pythonCode,
                    entrypoint: 'main',
                    libraries: librariesArray,
                }
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

    private extractWebhookName(path: string): string {
        if (!path) {
            return '';
        }
        const webhooksDelimiter = '/webhooks/';
        if (path.includes(webhooksDelimiter)) {
            const [, name] = path.split(webhooksDelimiter);
            return name || '';
        }
        const lastSlashIndex = path.lastIndexOf('/');
        if (lastSlashIndex === -1) {
            return path;
        }
        return path.substring(lastSlashIndex + 1);
    }

    private updateWebhookUrlDisplay(webhookNameValue?: string | null): void {
        const control = this.form?.get('webhookName');
        if (control && control.invalid) {
            this.webhookUrlDisplay = '';
            return;
        }
        const webhookName = (webhookNameValue ?? control?.value ?? '').trim();
        if (!this.webhookUrlBase) {
            this.webhookUrlDisplay = '';
            return;
        }
        this.webhookUrlDisplay = `${this.webhookUrlBase}${webhookName}`;
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
        if (!this.webhookUrlDisplay) {
            return;
        }
        this.clipboard.copy(this.webhookUrlDisplay);
    }
}
