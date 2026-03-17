import { Component, Inject, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import {
    FormBuilder,
    FormGroup,
    FormsModule,
    ReactiveFormsModule,
    Validators,
} from '@angular/forms';
import { Dialog, DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ChatsService } from '../../../../services/chats.service';
import { LanguageSelectorComponent } from './language-selector/language-selector.component';
import { VoiceSelectorComponent } from './voice-selector/voice-selector.component';
import { AVAILABLE_LANGUAGES } from '../../../../../../shared/constants/languages-selector.constants';
import { AVAILABLE_VOICES } from '../../../../../../shared/constants/realtime-voice.constants';
import { RealtimeAgentService } from '../../../../../../features/staff/services/realtime-agent.service';
import { finalize } from 'rxjs';
import { HelpTooltipComponent } from '../../../../../../shared/components/help-tooltip/help-tooltip.component';

import {
    RealtimeAgent,
    UpdateRealtimeAgentRequest,
} from '../../../../../../features/staff/models/realtime-agent.model';
import { ToastService } from '../../../../../../services/notifications/toast.service';
import {
    FullAgent,
    PartialAgent,
} from '../../../../../../features/staff/services/full-agent.service';
import {
    Agent,
    PartialUpdateAgentRequest,
    RealtimeAgentConfig,
} from '../../../../../../features/staff/models/agent.model';
import { AgentsService } from '../../../../../../features/staff/services/staff.service';
import { TranscriptionConfigsService } from '../../../../../../features/transcription/services/transcription-config.service';
import {
    EnhancedTranscriptionConfig,
    GetTranscriptionConfigRequest,
} from '../../../../../../features/transcription/models/transcription-config.model';
import { TranscriptionConfigSelectorComponent } from './transcription-model-selector/transcription-config-selector.component';
import { AddTranscriptionConfigDialogComponent } from './add-transcription-dialog/add-transcription-dialog.component';
import { buildToolIdsArray } from '../../../../../../shared/utils/tool-ids-builder.util';

@Component({
    selector: 'app-realtime-settings-dialog',
    standalone: true,
    imports: [
        CommonModule,
        FormsModule,
        ReactiveFormsModule,
        LanguageSelectorComponent,
        VoiceSelectorComponent,
        TranscriptionConfigSelectorComponent,
        HelpTooltipComponent,
    ],
    templateUrl: './realtime-settings-dialog.component.html',
    styleUrls: ['./realtime-settings-dialog.component.scss'],
})
export class RealtimeSettingsDialogComponent implements OnInit {
    settingsForm!: FormGroup;
    submitting = false;
    errorMessage: string | null = null;
    transcriptionConfigs: EnhancedTranscriptionConfig[] = [];
    loadingConfigs = false;

    // Language options from constants
    languages = AVAILABLE_LANGUAGES;

    // Voice options from constants
    voices = AVAILABLE_VOICES;

    constructor(
        private dialogRef: DialogRef<PartialAgent>,
        @Inject(DIALOG_DATA) public data: { agent: FullAgent },
        private agentsService: AgentsService,
        private transcriptionConfigsService: TranscriptionConfigsService,
        private fb: FormBuilder,
        private toastService: ToastService,
        private dialog: Dialog
    ) {}

    ngOnInit(): void {
        this.loadTranscriptionConfigs();

        this.settingsForm = this.fb.group({
            voice: [this.data.agent.realtime_agent.voice, Validators.required],
            threshold: [
                Number(this.data.agent.search_configs?.naive?.similarity_threshold ?? 0.2),
                [Validators.required, Validators.min(0), Validators.max(1)],
            ],
            searchLimit: [
                this.data.agent.search_configs.naive.search_limit,
                [Validators.required, Validators.min(0), Validators.max(1000)],
            ],
            wakeword: [this.data.agent.realtime_agent.wake_word],
            stopword: [this.data.agent.realtime_agent.stop_prompt],
            preferredLanguage: [this.data.agent.realtime_agent.language],
            voice_recognition_prompt: [
                this.data.agent.realtime_agent.voice_recognition_prompt,
            ],
            realtime_transcription_config: [
                this.data.agent.realtime_agent.realtime_transcription_config,
            ],
        });
    }

    loadTranscriptionConfigs(): void {
        this.loadingConfigs = true;
        this.transcriptionConfigsService
            .getEnhancedTranscriptionConfigs()
            .pipe(
                finalize(() => {
                    this.loadingConfigs = false;
                })
            )
            .subscribe({
                next: (configs) => {
                    this.transcriptionConfigs = configs;
                },
                error: (error) => {
                    console.error(
                        'Error loading transcription configs:',
                        error
                    );
                    this.toastService.error(
                        'Failed to load transcription configurations.'
                    );
                },
            });
    }

    onTranscriptionConfigChange(configId: number | null): void {
        this.settingsForm.patchValue({
            realtime_transcription_config: configId,
        });
    }

    openCreateTranscriptionConfigDialog(): void {
        const dialogRef = this.dialog.open(
            AddTranscriptionConfigDialogComponent,
            {
                data: {},
                width: '500px',
            }
        );

        dialogRef.closed.subscribe((result: any) => {
            if (result) {
                // Reload the configs to include the newly created one
                this.loadTranscriptionConfigs();

                // After a short delay to ensure the configs are loaded, select the new config
                setTimeout(() => {
                    this.onTranscriptionConfigChange(result.id);
                }, 300);
            }
        });
    }

    deleteTranscriptionConfig(configId: number): void {
        this.settingsForm.patchValue({ realtime_transcription_config: null });

        this.transcriptionConfigsService
            .deleteTranscriptionConfig(configId)
            .subscribe({
                next: () => {
                    this.toastService.success(
                        'Transcription config deleted successfully'
                    );

                    this.transcriptionConfigs =
                        this.transcriptionConfigs.filter(
                            (c) => c.id !== configId
                        );
                },
                error: (error) => {
                    console.error(
                        'Error deleting transcription config:',
                        error
                    );
                    this.toastService.error(
                        'Failed to delete transcription config'
                    );
                },
            });
    }

    onLanguageChange(langId: string | null): void {
        this.settingsForm.patchValue({ preferredLanguage: langId });
    }

    onVoiceChange(voiceId: string): void {
        this.settingsForm.patchValue({ voice: voiceId });
    }

    onCancel(): void {
        this.dialogRef.close();
    }

    onConfirm(): void {
        if (this.settingsForm.valid) {
            this.submitting = true;
            this.errorMessage = null;

            // Get form values
            const formValues = this.settingsForm.value;

            // Prepare the data for API request
            const realtimeAgentData: RealtimeAgentConfig = {
                wake_word: formValues.wakeword,
                stop_prompt: formValues.stopword,
                language: formValues.preferredLanguage,
                voice: formValues.voice,
                voice_recognition_prompt: formValues.voice_recognition_prompt,
                realtime_transcription_config:
                    formValues.realtime_transcription_config,
                realtime_config: this.data.agent.realtime_agent.realtime_config,
            };

            const searchConfigsData = {
                naive: {
                    similarity_threshold: formValues.threshold.toString(),
                    search_limit: formValues.searchLimit,
                }
            }

            const getToolIds = (tools: any[]) => {
                const configured_tool: number[] = [];
                const python_code_tool: number[] = [];

                tools.forEach(({ data, unique_name }) => {
                    const parts = unique_name.split(':');
                    if (parts[0] === 'configured-tool') {
                        configured_tool.push(data.id);
                    } else {
                        python_code_tool.push(data.id);
                    }
                });

                return { configured_tool, python_code_tool };
            };

            const { configured_tool, python_code_tool } = getToolIds(
                this.data.agent.tools
            );

            // Build tool_ids array for settings update
            const settingsToolIds = buildToolIdsArray(
                configured_tool,
                python_code_tool
            );

            const updatedAgent: PartialUpdateAgentRequest = {
                id: this.data.agent.id,
                role: this.data.agent.role,
                goal: this.data.agent.goal,
                backstory: this.data.agent.backstory,
                realtime_agent: realtimeAgentData,
                search_configs: searchConfigsData,
                configured_tools: configured_tool,
                python_code_tools: python_code_tool,
                tool_ids: settingsToolIds,
            };

            // Send PATCH request to update the realtime agent
            this.agentsService
                .partialUpdateAgent(updatedAgent)
                .pipe(
                    finalize(() => {
                        this.submitting = false;
                    })
                )
                .subscribe({
                    next: (response) => {
                        console.log(
                            'Realtime agent updated successfully:',
                            response
                        );
                        this.toastService.success(
                            'Realtime agent settings updated successfully'
                        );

                        // Pass the updated agent back to the parent component
                        this.dialogRef.close(updatedAgent);
                    },
                    error: (error) => {
                        console.error('Error updating realtime agent:', error);
                        this.errorMessage =
                            'Failed to update settings. Please try again.';

                        this.toastService.error(
                            'Failed to update settings. Please try again.'
                        );
                    },
                });
        }
    }
}
