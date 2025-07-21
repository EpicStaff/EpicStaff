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
import { RangeSliderComponent } from '../../../chats-content/chat/chat-header/range-slider/range-slider.component';
import { LanguageSelectorComponent } from './language-selector/language-selector.component';
import { VoiceSelectorComponent } from './voice-selector/voice-selector.component';
import { AVAILABLE_LANGUAGES } from '../../../../../../shared/constants/languages-selector.constants';
import { AVAILABLE_VOICES } from '../../../../../../shared/constants/realtime-voice.constants';
import { RealtimeAgentService } from '../../../../../../services/realtime-agent.service';
import { finalize } from 'rxjs';
import { HelpTooltipComponent } from '../../../../../../shared/components/help-tooltip/help-tooltip.component';

import {
  RealtimeAgent,
  UpdateRealtimeAgentRequest,
} from '../../../../../../shared/models/realtime-agent.model';
import { ToastService } from '../../../../../../services/notifications/toast.service';
import { FullAgent } from '../../../../../../services/full-agent.service';
import {
  Agent,
  RealtimeAgentConfig,
} from '../../../../../../shared/models/agent.model';
import { AgentsService } from '../../../../../../services/staff.service';
import { TranscriptionConfigsService } from '../../../../../../services/transcription-config.service';
import {
  EnhancedTranscriptionConfig,
  GetTranscriptionConfigRequest,
} from '../../../../../../shared/models/transcription-config.model';
import { TranscriptionConfigSelectorComponent } from './transcription-model-selector/transcription-config-selector.component';
import { AddTranscriptionConfigDialogComponent } from './add-transcription-dialog/add-transcription-dialog.component';

@Component({
  selector: 'app-realtime-settings-dialog',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    ReactiveFormsModule,
    RangeSliderComponent,
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
    private dialogRef: DialogRef<FullAgent>,
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
        parseFloat(this.data.agent.realtime_agent.distance_threshold),
        [Validators.required, Validators.min(0), Validators.max(1)],
      ],
      searchLimit: [
        this.data.agent.realtime_agent.search_limit,
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
          console.error('Error loading transcription configs:', error);
          this.toastService.error(
            'Failed to load transcription configurations.'
          );
        },
      });
  }

  onTranscriptionConfigChange(configId: number | null): void {
    this.settingsForm.patchValue({ realtime_transcription_config: configId });
  }

  openCreateTranscriptionConfigDialog(): void {
    const dialogRef = this.dialog.open(AddTranscriptionConfigDialogComponent, {
      data: {},
      width: '500px',
    });

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
  onThresholdChange(value: number): void {
    this.settingsForm.patchValue({ threshold: value });
  }

  onSearchLimitChange(value: number): void {
    this.settingsForm.patchValue({ searchLimit: value });
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
        distance_threshold: formValues.threshold.toString(),
        search_limit: formValues.searchLimit,
        wake_word: formValues.wakeword,
        stop_prompt: formValues.stopword,
        language: formValues.preferredLanguage,
        voice: formValues.voice,
        voice_recognition_prompt: formValues.voice_recognition_prompt,
        realtime_transcription_config: formValues.realtime_transcription_config,
        realtime_config: this.data.agent.realtime_agent.realtime_config,
      };
      const updatedAgent = {
        ...this.data.agent,
        realtime_agent: realtimeAgentData,
      };

      // Send PUT request to update the realtime agent
      this.agentsService
        .updateAgent(updatedAgent as any)
        .pipe(
          finalize(() => {
            this.submitting = false;
          })
        )
        .subscribe({
          next: (response) => {
            console.log('Realtime agent updated successfully:', response);
            this.toastService.success(
              'Realtime agent settings updated successfully'
            );

            // Pass the updated agent back to the parent component
            this.dialogRef.close(updatedAgent);
          },
          error: (error) => {
            console.error('Error updating realtime agent:', error);
            this.errorMessage = 'Failed to update settings. Please try again.';

            this.toastService.error(
              'Failed to update settings. Please try again.'
            );
          },
        });
    }
  }
}
