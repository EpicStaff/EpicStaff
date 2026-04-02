import { DialogRef } from '@angular/cdk/dialog';
import { NgIf } from '@angular/common';
import {
    AfterViewInit,
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    ElementRef,
    ViewChild,
} from '@angular/core';
import { FormBuilder, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { Router } from '@angular/router';
// RxJS imports
import { forkJoin, Observable, of, switchMap } from 'rxjs';

import { ToastService } from '../../../../services/notifications/toast.service';
import { AppIconComponent } from '../../../../shared/components/app-icon/app-icon.component';
import { ButtonComponent } from '../../../../shared/components/buttons/button/button.component';
import { EmbeddingModel } from '../../../settings-dialog/models/embeddings/embedding.model';
import { CreateEmbeddingConfigRequest } from '../../../settings-dialog/models/embeddings/embedding-config.model';
import { GetLlmModelRequest } from '../../../settings-dialog/models/llms/LLM.model';
import { CreateLLMConfigRequest } from '../../../settings-dialog/models/llms/LLM_config.model';
import { CreateRealtimeModelConfigRequest } from '../../../settings-dialog/models/realtime-voice/realtime-llm-config.model';
import { RealtimeModel } from '../../../settings-dialog/models/realtime-voice/realtime-model.model';
import { EmbeddingConfigsService } from '../../../settings-dialog/services/embeddings/embedding_configs.service';
import { EmbeddingModelsService } from '../../../settings-dialog/services/embeddings/embeddings.service';
import { RealtimeModelConfigsService } from '../../../settings-dialog/services/realtime-llms/real-time-model-config.service';
import { RealtimeModelsService } from '../../../settings-dialog/services/realtime-llms/real-time-models.service';
import {
    CreateTranscriptionConfigRequest,
    GetRealtimeTranscriptionModelRequest,
} from '../../../transcription/models/transcription-config.model';
import { TranscriptionConfigsService } from '../../../transcription/services/transcription-config.service';
import { LLM_Config_Service } from '../../services/llms/llm-config.service';
import { LLM_Models_Service } from '../../services/llms/llm-models.service';

@Component({
    selector: 'app-quickstart-tab',
    standalone: true,
    imports: [NgIf, ReactiveFormsModule, AppIconComponent, ButtonComponent],
    template: `
        <div class="quick-start-container">
            <div class="quick-start-header">
                <h3 class="title">Quickstart</h3>
                <p class="subtitle">Quickly configure your environment with OpenAI</p>
            </div>

            <form [formGroup]="quickStartForm">
                <div class="form-group">
                    <div class="provider-label">
                        <label for="apiKey" class="api-key-label">
                            <div class="openai-logo">
                                <app-icon
                                    icon="llm-providers-logos/openai-logo"
                                    [size]="'24px'"
                                    ariaLabel="OpenAI Logo"
                                ></app-icon>
                            </div>
                            Please provide an OpenAI API Key
                        </label>
                    </div>

                    <div class="input-with-icon">
                        <input
                            #apiKeyInput
                            [type]="showApiKey ? 'text' : 'password'"
                            id="apiKey"
                            formControlName="apiKey"
                            placeholder="Enter OpenAI API key"
                            class="text-input"
                            autocomplete="off"
                            autocorrect="off"
                            autocapitalize="off"
                            spellcheck="false"
                            data-lpignore="true"
                            data-form-type="other"
                        />
                        <button type="button" class="eye-button" (click)="toggleApiKeyVisibility()">
                            <svg
                                *ngIf="showApiKey"
                                width="16"
                                height="16"
                                viewBox="0 0 24 24"
                                fill="none"
                                xmlns="http://www.w3.org/2000/svg"
                            >
                                <path
                                    d="M2 12C2 12 5 5 12 5C19 5 22 12 22 12C22 12 19 19 12 19C5 19 2 12 2 12Z"
                                    stroke="currentColor"
                                    stroke-width="2"
                                    stroke-linecap="round"
                                    stroke-linejoin="round"
                                />
                                <path
                                    d="M12 15C13.6569 15 15 13.6569 15 12C15 10.3431 13.6569 9 12 9C10.3431 9 9 10.3431 9 12C9 13.6569 10.3431 15 12 15Z"
                                    stroke="currentColor"
                                    stroke-width="2"
                                    stroke-linecap="round"
                                    stroke-linejoin="round"
                                />
                                <path
                                    d="M3 3L21 21"
                                    stroke="currentColor"
                                    stroke-width="2"
                                    stroke-linecap="round"
                                    stroke-linejoin="round"
                                />
                            </svg>
                            <svg
                                *ngIf="!showApiKey"
                                width="16"
                                height="16"
                                viewBox="0 0 24 24"
                                fill="none"
                                xmlns="http://www.w3.org/2000/svg"
                            >
                                <path
                                    d="M2 12C2 12 5 5 12 5C19 5 22 12 22 12C22 12 19 19 12 19C5 19 2 12 2 12Z"
                                    stroke="currentColor"
                                    stroke-width="2"
                                    stroke-linecap="round"
                                    stroke-linejoin="round"
                                />
                                <path
                                    d="M12 15C13.6569 15 15 13.6569 15 12C15 10.3431 13.6569 9 12 9C10.3431 9 9 10.3431 9 12C9 13.6569 10.3431 15 12 15Z"
                                    stroke="currentColor"
                                    stroke-width="2"
                                    stroke-linecap="round"
                                    stroke-linejoin="round"
                                />
                            </svg>
                        </button>
                    </div>
                    <div class="api-key-description">
                        <p>This API key will be used to quickly auto create:</p>
                        <ul class="description-list">
                            <li><span class="bullet">•</span> Models and tools configurations</li>
                            <li><span class="bullet">•</span> Realtime configs</li>
                            <li><span class="bullet">•</span> Embeddings configs</li>
                            <li><span class="bullet">•</span> Model defaults for projects</li>
                            <li><span class="bullet">•</span> Model defaults for agents</li>
                            <li><span class="bullet">•</span> Model defaults for tools</li>
                        </ul>
                    </div>
                </div>
            </form>

            <div class="dialog-footer">
                <app-button type="secondary" (click)="onCancel()"> Cancel </app-button>
                <app-button type="primary" [disabled]="!quickStartForm.get('apiKey')?.value" (click)="onQuickStart()">
                    <div *ngIf="isSaving" class="loader-container">
                        <svg class="spinner" viewBox="0 0 50 50">
                            <circle class="path" cx="25" cy="25" r="20" fill="none" stroke-width="5"></circle>
                        </svg>
                    </div>
                    Start Building
                </app-button>
            </div>
        </div>
    `,
    styles: [
        `
            .quick-start-container {
                display: flex;
                flex-direction: column;
                height: 100%;
                padding: 20px;
            }

            .quick-start-header {
                margin-bottom: 24px;
            }

            .title {
                font-size: 20px;
                font-weight: 400;
                color: var(--color-text-primary);
                margin-bottom: 8px;
            }

            .subtitle {
                font-size: 14px;
                color: var(--color-text-secondary);
            }

            .form-group {
                margin-bottom: 24px;
            }

            .provider-label {
                display: flex;
                margin-bottom: 12px;
                font-size: 14px;
                color: var(--color-text-primary);
            }

            .api-key-label {
                display: flex;
                align-items: center;
                gap: 8px;
            }

            .openai-logo {
                display: flex;
                align-items: center;
            }

            .input-with-icon {
                position: relative;
                margin-bottom: 16px;
            }

            .text-input {
                width: 100%;
                padding: 12px 40px 12px 12px;
                border: 1px solid var(--color-input-border);
                border-radius: 8px;
                background-color: var(--color-input-background);
                color: var(--color-text-primary);
                font-size: 14px;
                line-height: 20px;
                transition:
                    border-color 0.2s ease,
                    box-shadow 0.2s ease;
            }

            .text-input::placeholder {
                color: var(--color-input-text-placeholder);
            }

            .text-input:focus {
                outline: none;
                border-color: var(--accent-color);
                box-shadow: 0 0 0 2px rgba(104, 95, 255, 0.15);
            }

            .eye-button {
                position: absolute;
                right: 12px;
                top: 50%;
                transform: translateY(-50%);
                background: transparent;
                border: none;
                cursor: pointer;
                padding: 0;
                display: flex;
                align-items: center;
                justify-content: center;
                color: var(--color-text-tertiary);
            }

            .eye-button:hover {
                color: var(--color-text-secondary);
            }

            .api-key-description {
                font-size: 13px;
                color: var(--color-text-secondary);
                margin-top: 8px;
            }

            .description-list {
                list-style-type: none;
                padding-left: 8px;
                margin-top: 8px;
            }

            .description-list li {
                margin-bottom: 4px;
                display: flex;
                align-items: flex-start;
            }

            .bullet {
                margin-right: 8px;
                color: var(--accent-color);
            }

            .dialog-footer {
                display: flex;
                justify-content: flex-end;
                gap: 12px;
                margin-top: auto;
                padding-top: 16px;
            }

            .loader-container {
                display: flex;
                align-items: center;
                justify-content: center;
                margin-right: 8px;
            }

            .spinner {
                width: 20px;
                height: 20px;
                animation: rotate 2s linear infinite;
            }

            .path {
                stroke: white;
                stroke-linecap: round;
                animation: dash 1.5s ease-in-out infinite;
            }

            @keyframes rotate {
                100% {
                    transform: rotate(360deg);
                }
            }

            @keyframes dash {
                0% {
                    stroke-dasharray: 1, 150;
                    stroke-dashoffset: 0;
                }
                50% {
                    stroke-dasharray: 90, 150;
                    stroke-dashoffset: -35;
                }
                100% {
                    stroke-dasharray: 90, 150;
                    stroke-dashoffset: -124;
                }
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class QuickstartTabComponent implements AfterViewInit {
    @ViewChild('apiKeyInput') apiKeyInput!: ElementRef<HTMLInputElement>;

    public quickStartForm: FormGroup;
    public showApiKey = false;
    public isSaving = false;

    private openAIProviderId = 1;

    private llmModelName = 'gpt-4o-mini';
    private embeddingModelName = 'text-embedding-3-small';
    private realtimeModelName = 'gpt-4o-mini-realtime-preview-2024-12-17';

    constructor(
        private dialogRef: DialogRef<string>,
        private cdr: ChangeDetectorRef,
        private router: Router,
        private llmConfigService: LLM_Config_Service,
        private embeddingConfigsService: EmbeddingConfigsService,
        private realtimeModelConfigsService: RealtimeModelConfigsService,
        private llmModelsService: LLM_Models_Service,
        private embeddingModelsService: EmbeddingModelsService,
        private realtimeModelsService: RealtimeModelsService,
        private toastService: ToastService,
        private transcriptionConfigsService: TranscriptionConfigsService,
        private fb: FormBuilder
    ) {
        this.quickStartForm = this.fb.group({
            apiKey: [''],
        });
    }

    ngAfterViewInit(): void {
        setTimeout(() => {
            if (this.apiKeyInput) {
                this.apiKeyInput.nativeElement.focus();
                this.cdr.markForCheck();
            }
        });
    }

    public toggleApiKeyVisibility(): void {
        this.showApiKey = !this.showApiKey;
        this.cdr.markForCheck();
    }

    public onQuickStart(): void {
        const apiKey = this.quickStartForm.get('apiKey')?.value;
        if (apiKey) {
            this.createQuickStartConfigs(apiKey);
        }
    }

    public onCancel(): void {
        this.dialogRef.close();
    }

    private createQuickStartConfigs(apiKey: string): void {
        this.isSaving = true;
        this.cdr.markForCheck();

        forkJoin({
            llmModels: this.llmModelsService.getLLMModels(),
            embeddingModels: this.embeddingModelsService.getEmbeddingModels(),
            realtimeModels: this.realtimeModelsService.getAllModels(),
            realtimeTranscriptionModels: this.realtimeModelsService.getAllModels(),
        })
            .pipe(
                switchMap((modelResults) => {
                    // Find LLM model by name - "gpt-4o-mini"
                    const llmModel: GetLlmModelRequest | undefined =
                        modelResults.llmModels.find((model) => model.name === this.llmModelName) ||
                        modelResults.llmModels.find((model) => model.llm_provider === this.openAIProviderId);

                    // Find embedding model by name - "text-embedding-3-small"
                    const embeddingModel: EmbeddingModel | undefined =
                        modelResults.embeddingModels.find((model) => model.name === this.embeddingModelName) ||
                        modelResults.embeddingModels.find(
                            (model) => model.embedding_provider === this.openAIProviderId
                        );

                    // Find realtime model by name - "gpt-4o-mini-realtime-preview-2024-12-17"
                    const realtimeModel: RealtimeModel | undefined =
                        modelResults.realtimeModels.find((model) => model.name === this.realtimeModelName) ||
                        modelResults.realtimeModels.find((model) => model.provider === this.openAIProviderId);

                    // Find transcription model that matches OpenAI
                    const transcriptionModel: GetRealtimeTranscriptionModelRequest | undefined =
                        modelResults.realtimeTranscriptionModels.find(
                            (model) => model.provider === this.openAIProviderId
                        );

                    // Now fetch existing configurations to find unique names
                    return forkJoin({
                        llmConfigs: this.llmConfigService.getConfigsByProviderId(this.openAIProviderId),
                        embeddingConfigs: this.embeddingConfigsService.getEmbeddingConfigsByProviderId(
                            this.openAIProviderId
                        ),
                        realtimeConfigs: this.realtimeModelConfigsService.getConfigsByProviderId(this.openAIProviderId),
                        transcriptionConfigs: this.transcriptionConfigsService.getTranscriptionConfigsByProviderId(
                            this.openAIProviderId
                        ),
                        models: of({
                            llm: llmModel,
                            embedding: embeddingModel,
                            realtime: realtimeModel,
                            transcription: transcriptionModel,
                        }),
                    });
                })
            )
            .subscribe({
                next: (results) => {
                    const models = results.models;

                    const configsToCreate: Array<{
                        type: string;
                        observable: Observable<unknown>;
                    }> = [];
                    const missingModels: string[] = [];

                    const getUniqueCustomName = (
                        configType: string,
                        existingConfigs: { custom_name?: string }[]
                    ): string => {
                        let baseCustomName = 'quickstart';
                        let customName = baseCustomName;
                        let counter = 2;

                        let nameExists = existingConfigs.some((config) => config.custom_name === customName);

                        while (nameExists) {
                            customName = `${baseCustomName}${counter}`;
                            nameExists = existingConfigs.some((config) => config.custom_name === customName);
                            counter++;
                        }

                        return customName;
                    };

                    if (models.llm) {
                        const llmCustomName = getUniqueCustomName('LLM', results.llmConfigs);
                        const llmConfig: CreateLLMConfigRequest = {
                            model: models.llm.id,
                            custom_name: llmCustomName,
                            api_key: apiKey,
                            is_visible: true,
                        };
                        configsToCreate.push({
                            type: 'LLM',
                            observable: this.llmConfigService.createConfig(llmConfig),
                        });
                    } else {
                        missingModels.push('LLM');
                    }

                    if (models.embedding) {
                        const embeddingCustomName = getUniqueCustomName('Embedding', results.embeddingConfigs);
                        const embeddingConfig: CreateEmbeddingConfigRequest = {
                            model: models.embedding.id,
                            custom_name: embeddingCustomName,
                            api_key: apiKey,
                            task_type: 'retrieval_document',
                            is_visible: true,
                        };
                        configsToCreate.push({
                            type: 'Embedding',
                            observable: this.embeddingConfigsService.createEmbeddingConfig(embeddingConfig),
                        });
                    } else {
                        missingModels.push('Embedding');
                    }

                    if (models.realtime) {
                        const realtimeCustomName = getUniqueCustomName('Realtime', results.realtimeConfigs);
                        const realtimeConfig: CreateRealtimeModelConfigRequest = {
                            realtime_model: models.realtime.id,
                            api_key: apiKey,
                            custom_name: realtimeCustomName,
                        };
                        configsToCreate.push({
                            type: 'Realtime',
                            observable: this.realtimeModelConfigsService.createConfig(realtimeConfig),
                        });
                    } else {
                        missingModels.push('Realtime');
                    }

                    if (models.transcription) {
                        const transcriptionCustomName = getUniqueCustomName(
                            'Transcription',
                            results.transcriptionConfigs
                        );
                        const transcriptionConfig: CreateTranscriptionConfigRequest = {
                            realtime_transcription_model: models.transcription.id,
                            api_key: apiKey,
                            custom_name: transcriptionCustomName,
                        };
                        configsToCreate.push({
                            type: 'Transcription',
                            observable: this.transcriptionConfigsService.createTranscriptionConfig(transcriptionConfig),
                        });
                    } else {
                        missingModels.push('Transcription');
                    }

                    if (configsToCreate.length === 0) {
                        this.isSaving = false;
                        this.cdr.markForCheck();

                        this.toastService.warning(`No available models found for OpenAI: ${missingModels.join(', ')}`);
                        return;
                    }

                    forkJoin(configsToCreate.map((item) => item.observable)).subscribe({
                        next: () => {
                            this.isSaving = false;
                            this.cdr.markForCheck();

                            if (missingModels.length > 0) {
                                this.toastService.info(
                                    `Some models not available for OpenAI: ${missingModels.join(', ')}`
                                );
                            }

                            this.toastService.success(`QuickStart setup completed`, 5000, 'top-center');

                            this.dialogRef.close('quickstart-complete');
                        },
                        error: (error) => {
                            this.isSaving = false;
                            this.cdr.markForCheck();

                            console.error('Error creating QuickStart configurations:', error);
                            this.toastService.error('Failed to create QuickStart configurations');
                        },
                    });
                },
                error: (error) => {
                    this.isSaving = false;
                    this.cdr.markForCheck();

                    console.error('Error fetching models or checking existing configurations:', error);
                    this.toastService.error('Failed to set up QuickStart configurations');
                },
            });
    }
}
