import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, FormGroup, FormsModule, ReactiveFormsModule } from '@angular/forms';
import { RadioButtonComponent, SelectComponent, SelectItem } from '@shared/components';
import { finalize } from 'rxjs';

import {
    PartialUpdateRealtimeAgentDefinitionRequest,
    RealtimeAgentDefinition,
} from '../../../../../../features/agent-definitions/models/realtime-agent-definition.model';
import { RealtimeAgentDefinitionsApiService } from '../../../../../../features/agent-definitions/services/realtime-agent-definitions-api.service';
import { ElevenLabsRealtimeConfigStorageService } from '../../../../../../features/configure-models/services/llms/elevenlabs-realtime-config-storage.service';
import { GeminiRealtimeConfigStorageService } from '../../../../../../features/configure-models/services/llms/gemini-realtime-config-storage.service';
import { OpenAIRealtimeConfigStorageService } from '../../../../../../features/configure-models/services/llms/openai-realtime-config-storage.service';
import { ToastService } from '../../../../../../services/notifications/toast.service';
import { HelpTooltipComponent } from '../../../../../../shared/components/help-tooltip/help-tooltip.component';
import { VoiceSelectorComponent } from '../../../../../../shared/components/voice-selector/voice-selector.component';
import { AVAILABLE_LANGUAGES } from '../../../../../../shared/constants/languages-selector.constants';
import { AVAILABLE_VOICES } from '../../../../../../shared/constants/realtime-voice.constants';
import { LanguageSelectorComponent } from '../realtime-settings-dialog/language-selector/language-selector.component';

export type RealtimeProvider = 'openai' | 'elevenlabs' | 'gemini';

export interface AgentDefinitionRealtimeSettingsDialogData {
    definitionId: number;
    definitionName: string;
    realtime: RealtimeAgentDefinition;
}

@Component({
    selector: 'app-agent-definition-realtime-settings-dialog',
    standalone: true,
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [
        CommonModule,
        FormsModule,
        ReactiveFormsModule,
        LanguageSelectorComponent,
        VoiceSelectorComponent,
        HelpTooltipComponent,
        SelectComponent,
        RadioButtonComponent,
    ],
    templateUrl: './agent-definition-realtime-settings-dialog.component.html',
    styleUrls: ['./agent-definition-realtime-settings-dialog.component.scss'],
})
export class AgentDefinitionRealtimeSettingsDialogComponent implements OnInit {
    private readonly dialogRef = inject<DialogRef<RealtimeAgentDefinition>>(DialogRef);
    public readonly data = inject<AgentDefinitionRealtimeSettingsDialogData>(DIALOG_DATA);
    private readonly realtimeApi = inject(RealtimeAgentDefinitionsApiService);
    private readonly fb = inject(FormBuilder);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly openaiStorage = inject(OpenAIRealtimeConfigStorageService);
    private readonly elevenLabsStorage = inject(ElevenLabsRealtimeConfigStorageService);
    private readonly geminiStorage = inject(GeminiRealtimeConfigStorageService);

    settingsForm = signal<FormGroup | null>(null);
    submitting = signal(false);
    errorMessage = signal<string | null>(null);

    readonly activeProvider = signal<RealtimeProvider | null>(null);

    readonly openaiConfigItems = computed<SelectItem[]>(() => [
        { name: '— None —', value: null },
        ...this.openaiStorage.configs().map((c) => ({ name: c.custom_name, value: c.id })),
    ]);
    readonly elevenLabsConfigItems = computed<SelectItem[]>(() => [
        { name: '— None —', value: null },
        ...this.elevenLabsStorage.configs().map((c) => ({ name: c.custom_name, value: c.id })),
    ]);
    readonly geminiConfigItems = computed<SelectItem[]>(() => [
        { name: '— None —', value: null },
        ...this.geminiStorage.configs().map((c) => ({ name: c.custom_name, value: c.id })),
    ]);

    readonly isElevenLabs = computed(() => this.activeProvider() === 'elevenlabs');

    languages = AVAILABLE_LANGUAGES;
    voices = AVAILABLE_VOICES;

    readonly providers: SelectItem<RealtimeProvider>[] = [
        { value: 'openai', name: 'OpenAI' },
        { value: 'elevenlabs', name: 'ElevenLabs' },
        { value: 'gemini', name: 'Gemini' },
    ];

    ngOnInit(): void {
        const rt = this.data.realtime;

        if (rt.openai_config != null) this.activeProvider.set('openai');
        else if (rt.elevenlabs_config != null) this.activeProvider.set('elevenlabs');
        else if (rt.gemini_config != null) this.activeProvider.set('gemini');
        else this.activeProvider.set('openai');

        this.settingsForm.set(
            this.fb.group({
                voice: [rt.voice],
                wakeword: [rt.wake_word],
                stopword: [rt.stop_prompt],
                preferredLanguage: [rt.language],
                voice_recognition_prompt: [rt.voice_recognition_prompt],
                openai_config: [rt.openai_config],
                elevenlabs_config: [rt.elevenlabs_config],
                gemini_config: [rt.gemini_config],
            })
        );

        this.openaiStorage.getAllConfigs().pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
        this.elevenLabsStorage.getAllConfigs().pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
        this.geminiStorage.getAllConfigs().pipe(takeUntilDestroyed(this.destroyRef)).subscribe();

        this.dialogRef.keydownEvents.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((event: KeyboardEvent) => {
            if ((event.ctrlKey || event.metaKey) && event.code === 'KeyS') {
                event.preventDefault();
                this.onConfirm();
            }
        });
    }

    onProviderSelect(provider: unknown): void {
        this.activeProvider.set(provider as RealtimeProvider);
        if (provider === 'elevenlabs') this.settingsForm()?.patchValue({ voice: '' });
    }

    onLanguageChange(langId: string | null): void {
        this.settingsForm()?.patchValue({ preferredLanguage: langId });
    }

    onVoiceChange(voiceId: string): void {
        this.settingsForm()?.patchValue({ voice: voiceId });
    }

    onCancel(): void {
        this.dialogRef.close();
    }

    onConfirm(): void {
        if (this.submitting()) return;

        const form = this.settingsForm();
        if (!form) return;

        this.submitting.set(true);
        this.errorMessage.set(null);

        const v = form.value;
        const provider = this.activeProvider();
        const body: PartialUpdateRealtimeAgentDefinitionRequest = {
            voice: v.voice,
            wake_word: v.wakeword,
            stop_prompt: v.stopword,
            language: v.preferredLanguage,
            voice_recognition_prompt: v.voice_recognition_prompt,
            openai_config: provider === 'openai' ? v.openai_config : null,
            elevenlabs_config: provider === 'elevenlabs' ? v.elevenlabs_config : null,
            gemini_config: provider === 'gemini' ? v.gemini_config : null,
        };

        this.realtimeApi
            .partialUpdate(this.data.definitionId, body)
            .pipe(finalize(() => this.submitting.set(false)))
            .subscribe({
                next: (updated) => {
                    this.toastService.success('Realtime settings updated successfully');
                    this.dialogRef.close(updated);
                },
                error: () => {
                    this.errorMessage.set('Failed to update settings. Please try again.');
                    this.toastService.error('Failed to update settings. Please try again.');
                },
            });
    }
}
