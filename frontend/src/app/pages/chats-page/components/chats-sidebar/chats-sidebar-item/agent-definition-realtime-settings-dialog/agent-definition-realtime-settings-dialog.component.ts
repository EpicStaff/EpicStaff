import { Dialog, DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { Component, DestroyRef, Inject, inject, OnInit } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, FormGroup, FormsModule, ReactiveFormsModule } from '@angular/forms';
import { EnhancedTranscriptionConfig } from '@shared/models';
import { RealtimeModelConfigsService, TranscriptionConfigsService } from '@shared/services';
import { finalize } from 'rxjs';

import {
    PartialUpdateRealtimeAgentDefinitionRequest,
    RealtimeAgentDefinition,
} from '../../../../../../features/agent-definitions/models/realtime-agent-definition.model';
import { RealtimeAgentDefinitionsApiService } from '../../../../../../features/agent-definitions/services/realtime-agent-definitions-api.service';
import { ToastService } from '../../../../../../services/notifications/toast.service';
import { HelpTooltipComponent } from '../../../../../../shared/components/help-tooltip/help-tooltip.component';
import { AVAILABLE_LANGUAGES } from '../../../../../../shared/constants/languages-selector.constants';
import { AVAILABLE_VOICES } from '../../../../../../shared/constants/realtime-voice.constants';
import { AddTranscriptionConfigDialogComponent } from '../realtime-settings-dialog/add-transcription-dialog/add-transcription-dialog.component';
import { LanguageSelectorComponent } from '../realtime-settings-dialog/language-selector/language-selector.component';
import { TranscriptionConfigSelectorComponent } from '../realtime-settings-dialog/transcription-model-selector/transcription-config-selector.component';
import { VoiceSelectorComponent } from '../realtime-settings-dialog/voice-selector/voice-selector.component';

export interface AgentDefinitionRealtimeSettingsDialogData {
    definitionId: number;
    definitionName: string;
    realtime: RealtimeAgentDefinition;
}

@Component({
    selector: 'app-agent-definition-realtime-settings-dialog',
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
    templateUrl: './agent-definition-realtime-settings-dialog.component.html',
    styleUrls: ['./agent-definition-realtime-settings-dialog.component.scss'],
})
export class AgentDefinitionRealtimeSettingsDialogComponent implements OnInit {
    settingsForm!: FormGroup;
    submitting = false;
    errorMessage: string | null = null;
    transcriptionConfigs: EnhancedTranscriptionConfig[] = [];
    loadingConfigs = false;
    isElevenLabs = false;

    languages = AVAILABLE_LANGUAGES;
    voices = AVAILABLE_VOICES;

    private readonly destroyRef = inject(DestroyRef);

    constructor(
        private dialogRef: DialogRef<RealtimeAgentDefinition>,
        @Inject(DIALOG_DATA) public data: AgentDefinitionRealtimeSettingsDialogData,
        private realtimeApi: RealtimeAgentDefinitionsApiService,
        private transcriptionConfigsService: TranscriptionConfigsService,
        private realtimeModelConfigsService: RealtimeModelConfigsService,
        private fb: FormBuilder,
        private toastService: ToastService,
        private dialog: Dialog
    ) {}

    ngOnInit(): void {
        this.loadTranscriptionConfigs();
        this.loadRealtimeConfig();

        const rt = this.data.realtime;
        this.settingsForm = this.fb.group({
            voice: [rt.voice],
            wakeword: [rt.wake_word],
            stopword: [rt.stop_prompt],
            preferredLanguage: [rt.language],
            voice_recognition_prompt: [rt.voice_recognition_prompt],
            realtime_transcription_config: [rt.realtime_transcription_config],
        });

        this.dialogRef.keydownEvents.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((event: KeyboardEvent) => {
            if ((event.ctrlKey || event.metaKey) && event.code === 'KeyS') {
                event.preventDefault();
                this.onConfirm();
            }
        });
    }

    loadRealtimeConfig(): void {
        const configId = this.data.realtime.realtime_config;
        if (configId == null) return;
        this.realtimeModelConfigsService
            .getConfigById(configId)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (config) => {
                    this.isElevenLabs = config.provider_name === 'elevenlabs';
                },
                error: () => {
                    // Non-critical — voice dropdown remains as default
                },
            });
    }

    loadTranscriptionConfigs(): void {
        this.loadingConfigs = true;
        this.transcriptionConfigsService
            .getEnhancedTranscriptionConfigs()
            .pipe(finalize(() => (this.loadingConfigs = false)))
            .subscribe({
                next: (configs) => (this.transcriptionConfigs = configs),
                error: () => this.toastService.error('Failed to load transcription configurations.'),
            });
    }

    onTranscriptionConfigChange(configId: number | null): void {
        this.settingsForm.patchValue({ realtime_transcription_config: configId });
    }

    openCreateTranscriptionConfigDialog(): void {
        const dialogRef = this.dialog.open(AddTranscriptionConfigDialogComponent, { data: {}, width: '500px' });
        dialogRef.closed.subscribe((result: unknown) => {
            if (!result) return;
            this.loadTranscriptionConfigs();
            setTimeout(() => this.onTranscriptionConfigChange((result as { id: number }).id), 300);
        });
    }

    editTranscriptionConfig(configId: number): void {
        const editConfig = this.transcriptionConfigs.find((c) => c.id === configId);
        if (!editConfig) return;

        const dialogRef = this.dialog.open(AddTranscriptionConfigDialogComponent, {
            data: { editConfig },
            width: '500px',
        });
        dialogRef.closed.subscribe((result: unknown) => {
            if (!result) return;
            const updated = result as { id: number };
            this.loadTranscriptionConfigs();
            const currentSelected = this.settingsForm.get('realtime_transcription_config')?.value;
            if (currentSelected === updated.id) {
                setTimeout(() => this.onTranscriptionConfigChange(updated.id), 300);
            }
        });
    }

    deleteTranscriptionConfig(configId: number): void {
        this.settingsForm.patchValue({ realtime_transcription_config: null });
        this.transcriptionConfigsService.deleteTranscriptionConfig(configId).subscribe({
            next: () => {
                this.toastService.success('Transcription config deleted successfully');
                this.transcriptionConfigs = this.transcriptionConfigs.filter((c) => c.id !== configId);
            },
            error: () => this.toastService.error('Failed to delete transcription config'),
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
        if (this.submitting) return;
        this.submitting = true;
        this.errorMessage = null;

        const v = this.settingsForm.value;
        const body: PartialUpdateRealtimeAgentDefinitionRequest = {
            voice: v.voice,
            wake_word: v.wakeword,
            stop_prompt: v.stopword,
            language: v.preferredLanguage,
            voice_recognition_prompt: v.voice_recognition_prompt,
            realtime_transcription_config: v.realtime_transcription_config,
            realtime_config: this.data.realtime.realtime_config,
        };

        this.realtimeApi
            .partialUpdate(this.data.definitionId, body)
            .pipe(finalize(() => (this.submitting = false)))
            .subscribe({
                next: (updated) => {
                    this.toastService.success('Realtime settings updated successfully');
                    this.dialogRef.close(updated);
                },
                error: () => {
                    this.errorMessage = 'Failed to update settings. Please try again.';
                    this.toastService.error('Failed to update settings. Please try again.');
                },
            });
    }
}
