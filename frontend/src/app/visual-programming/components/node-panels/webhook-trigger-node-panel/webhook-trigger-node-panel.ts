import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    DestroyRef,
    inject,
    input,
    signal,
} from '@angular/core';
import { FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { WebhookTriggerNodeModel } from '../../../core/models/node.model';
import { BaseSidePanel } from '../../../core/models/node-panel.abstract';
import { CustomInputComponent } from '../../../../shared/components/form-input/form-input.component';
import { CodeEditorComponent } from '../../../../user-settings-page/tools/custom-tool-editor/code-editor/code-editor.component';
import { CommonModule } from '@angular/common';
import { WebhookService } from '../../../../pages/flows-page/components/flow-visual-programming/services/webhook.service';
import { Clipboard, ClipboardModule } from '@angular/cdk/clipboard';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { startWith } from 'rxjs';
import { WebhookStatus } from '../../../../pages/flows-page/components/flow-visual-programming/models/webhook.model';

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
                    <div
                        class="form-layout"
                        [class.expanded]="isExpanded()"
                        [class.collapsed]="!isExpanded()"
                        [class.code-editor-fullwidth]="isCodeEditorFullWidth()"
                    >
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
                                    <span
                                        class="webhook-url-text"
                                        [style.color]="activeColor"
                                    >
                                        {{ url }}
                                    </span>
                                    <button
                                        type="button"
                                        class="copy-button"
                                        (click)="copyWebhookUrl()"
                                        [disabled]="!url"
                                        aria-label="Copy webhook URL"
                                    >
                                        <span
                                            class="copy-icon"
                                            aria-hidden="true"
                                        ></span>
                                        <span>Copy</span>
                                    </button>
                                } @else {
                                    @if (tunnelErrorMessage) {
                                        <div class="webhook-url-error">
                                            {{ tunnelErrorMessage }}
                                        </div>
                                    } @else {
                                        <div class="webhook-url-placeholder">
                                            Fetching tunnel URL...
                                        </div>
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
                        @if (isExpanded()) {
                            <div class="code-editor-wrapper">
                                <button
                                    type="button"
                                    class="toggle-icon-button"
                                    (click)="toggleCodeEditorFullWidth()"
                                    [attr.aria-label]="
                                        isCodeEditorFullWidth()
                                            ? 'Collapse code editor'
                                            : 'Expand code editor'
                                    "
                                >
                                    <svg
                                        width="9"
                                        height="22"
                                        viewBox="0 0 9 22"
                                        fill="none"
                                        xmlns="http://www.w3.org/2000/svg"
                                        [style.transform]="
                                            isCodeEditorFullWidth()
                                                ? 'scaleX(1)'
                                                : 'scaleX(-1)'
                                        "
                                    >
                                        <path
                                            d="M7.16602 21.0001L1.16602 11.0001L7.16602 1.00012"
                                            stroke="currentColor"
                                            stroke-width="2"
                                            stroke-linecap="round"
                                        />
                                    </svg>
                                </button>
                                <div class="code-editor-section">
                                    <app-code-editor
                                        [pythonCode]="pythonCode"
                                        (pythonCodeChange)="
                                            onPythonCodeChange($event)
                                        "
                                        (errorChange)="
                                            onCodeErrorChange($event)
                                        "
                                    ></app-code-editor>
                                </div>
                            </div>
                        } @else {
                            <div class="code-editor-section">
                                <app-code-editor
                                    [pythonCode]="pythonCode"
                                    (pythonCodeChange)="
                                        onPythonCodeChange($event)
                                    "
                                    (errorChange)="onCodeErrorChange($event)"
                                ></app-code-editor>
                            </div>
                        }
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
                width: 100%;
                overflow: hidden;

                &.expanded {
                    display: flex;
                    gap: 1rem;
                    height: 100%;
                    width: 100%;

                    &.code-editor-fullwidth {
                        .form-fields {
                            display: none;
                        }

                        .code-editor-wrapper {
                            width: 100%;
                        }

                        .toggle-icon-button {
                            position: absolute;
                            left: 0;
                            top: 50%;
                            transform: translateY(-50%);
                            z-index: 10;
                            border-width: 1px 1px 1px 0px;
                            border-radius: 0 8px 8px 0;
                        }
                    }
                }

                &.collapsed {
                    display: flex;
                    flex-direction: column;
                    gap: 1rem;
                }
            }

            .form-fields {
                display: flex;
                flex-direction: column;
                gap: 1rem;

                .expanded & {
                    flex: 0 0 400px;
                    max-width: 400px;
                    height: 100%;
                    overflow-y: auto;
                }
            }

            .code-editor-wrapper {
                display: flex;
                align-items: center;
                gap: 0;
                height: 100%;
                position: relative;
                flex: 1;
                min-height: 0;
                min-width: 0;
                transition: all 0.5s cubic-bezier(0.34, 1.56, 0.64, 1);

                .toggle-icon-button {
                    flex-shrink: 0;
                    width: 28px;
                    height: 66px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    border-width: 1px 0px 1px 1px;
                    border-style: solid;
                    border-color: #2c2c2e;
                    background: #1e1e1e;
                    cursor: pointer;
                    border-radius: 8px 0 0 8px;
                    transition: all 0.2s ease;
                    padding: 0;
                    color: #d9d9d999;

                    svg {
                        transition: transform 0.3s ease;
                    }

                    &:hover:not(:disabled) {
                        color: #d9d9d9;
                        background: #2c2c2e;
                    }

                    &:active:not(:disabled) {
                        color: #d9d9d9;
                    }

                    &:disabled {
                        cursor: not-allowed;
                        opacity: 0.5;
                    }
                }

                app-code-editor {
                    min-width: 0;
                }
            }

            .btn-primary {
                @include mixins.primary-button;
            }

            .btn-secondary {
                @include mixins.secondary-button;
            }

            .code-editor-section {
                border: 1px solid
                    var(--color-divider-subtle, rgba(255, 255, 255, 0.1));
                overflow: hidden;
                display: flex;
                flex-direction: column;

                .expanded & {
                    flex: 1;
                    height: 100%;
                    min-height: 0;
                    border-radius: 0 8px 8px 0;
                    transition: all 0.5s cubic-bezier(0.34, 1.56, 0.64, 1);
                    transform: scaleX(0.3) translateX(-50px);
                    opacity: 0;
                }

                .collapsed & {
                    height: 300px;
                    border-radius: 8px;
                }

                .form-layout.expanded:not(.code-editor-fullwidth) & {
                    transform: scaleX(1) translateX(0);
                    opacity: 1;
                }

                .form-layout.expanded.code-editor-fullwidth & {
                    transform: scaleX(1) translateX(0);
                    opacity: 1;
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
                transition:
                    border-color 0.2s ease,
                    color 0.2s ease;
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
    public readonly isCodeEditorFullWidth = signal<boolean>(true);

    pythonCode: string = '';
    initialPythonCode: string = '';
    codeEditorHasError: boolean = false;
    tunnelUrl: string = '';
    tunnelErrorMessage: string = '';
    webhookUrlBase: string = '';
    webhookUrlDisplay: string = '';

    private readonly destroyRef = inject(DestroyRef);

    constructor(
        private webhookService: WebhookService,
        private cdr: ChangeDetectorRef,
        private clipboard: Clipboard,
    ) {
        super();
        this.webhookService.getTunnel().subscribe({
            next: (response) => {
                if (
                    response?.status === WebhookStatus.SUCCESS &&
                    response.tunnel_url
                ) {
                    this.tunnelUrl = response.tunnel_url;
                    this.webhookUrlBase = this.normalizeWebhookBase(
                        response.tunnel_url,
                    );
                    this.tunnelErrorMessage = '';
                    this.updateWebhookUrlDisplay(
                        this.form?.get('webhookName')?.value,
                    );
                } else {
                    this.tunnelErrorMessage =
                        'set your tunnel in .env configurations';
                    this.webhookUrlBase = '';
                    this.updateWebhookUrlDisplay(
                        this.form?.get('webhookName')?.value,
                    );
                }
                this.cdr.markForCheck();
            },
            error: () => {
                this.tunnelErrorMessage =
                    'set your tunnel in .env configurations';
                this.webhookUrlBase = '';
                this.updateWebhookUrlDisplay(
                    this.form?.get('webhookName')?.value,
                );
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
            libraries: [
                this.node().data.python_code.libraries?.join(', ') || '',
            ],
            webhookName: [
                this.extractWebhookName(
                    this.node().data.webhook_trigger_path || '',
                ),
                [Validators.pattern(WEBHOOK_NAME_PATTERN)],
            ],
        });
        form.get('webhookName')
            ?.valueChanges.pipe(
                startWith(form.get('webhookName')?.value ?? ''),
                takeUntilDestroyed(this.destroyRef),
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
                webhook_trigger_path: (
                    this.form.value.webhookName || ''
                ).trim(),
                python_code: {
                    name: this.node().data.python_code.name || 'Python Code',
                    code: this.pythonCode,
                    entrypoint: 'main',
                    libraries: librariesArray,
                },
            },
        };
    }

    private normalizeWebhookBase(tunnelUrl: string): string {
        if (!tunnelUrl) {
            return '';
        }
        const sanitized = tunnelUrl.endsWith('/')
            ? tunnelUrl.slice(0, -1)
            : tunnelUrl;
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

    toggleCodeEditorFullWidth(): void {
        this.isCodeEditorFullWidth.update((value) => !value);
    }
}
