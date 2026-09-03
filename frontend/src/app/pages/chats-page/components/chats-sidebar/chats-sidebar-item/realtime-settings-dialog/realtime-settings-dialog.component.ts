import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, FormGroup, FormsModule, ReactiveFormsModule, Validators } from '@angular/forms';
import { RadioButtonComponent, SelectComponent, SelectItem } from '@shared/components';
import { DEFAULT_STEP_SIZE } from '@shared/constants';
import { finalize } from 'rxjs';

import { ElevenLabsRealtimeConfigStorageService } from '../../../../../../features/configure-models/services/llms/elevenlabs-realtime-config-storage.service';
import { GeminiRealtimeConfigStorageService } from '../../../../../../features/configure-models/services/llms/gemini-realtime-config-storage.service';
import { OpenAIRealtimeConfigStorageService } from '../../../../../../features/configure-models/services/llms/openai-realtime-config-storage.service';
import { PartialUpdateAgentRequest, RealtimeAgentConfig } from '../../../../../../features/staff/models/agent.model';
import { FullAgent, PartialAgent } from '../../../../../../features/staff/services/full-agent.service';
import { AgentsService } from '../../../../../../features/staff/services/staff.service';
import { ToastService } from '../../../../../../services/notifications/toast.service';
import { HelpTooltipComponent } from '../../../../../../shared/components/help-tooltip/help-tooltip.component';
import { SliderWithStepperComponent } from '../../../../../../shared/components/slider-with-stepper/slider-with-stepper.component';
import { VoiceSelectorComponent } from '../../../../../../shared/components/voice-selector/voice-selector.component';
import { RealtimeVoice, RealtimeVoicesService } from '../../../../../../shared/services/realtime-voices.service';
import { buildToolIdsArray } from '../../../../../../shared/utils/tool-ids-builder.util';

export type RealtimeProvider = 'openai' | 'elevenlabs' | 'gemini';
type ProviderConfigValue = number | { id: number } | null | undefined;

@Component({
    selector: 'app-realtime-settings-dialog',
    standalone: true,
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [
        CommonModule,
        FormsModule,
        ReactiveFormsModule,
        VoiceSelectorComponent,
        HelpTooltipComponent,
        SelectComponent,
        SliderWithStepperComponent,
        RadioButtonComponent,
    ],
    templateUrl: './realtime-settings-dialog.component.html',
    styleUrls: ['./realtime-settings-dialog.component.scss'],
})
export class RealtimeSettingsDialogComponent implements OnInit {
    protected readonly DEFAULT_STEP_SIZE = DEFAULT_STEP_SIZE;

    private readonly dialogRef = inject<DialogRef<PartialAgent>>(DialogRef);
    public readonly data = inject<{ agent: FullAgent }>(DIALOG_DATA);
    private readonly agentsService = inject(AgentsService);
    private readonly openaiStorage = inject(OpenAIRealtimeConfigStorageService);
    private readonly elevenLabsStorage = inject(ElevenLabsRealtimeConfigStorageService);
    private readonly geminiStorage = inject(GeminiRealtimeConfigStorageService);
    private readonly fb = inject(FormBuilder);
    private readonly toastService = inject(ToastService);
    private readonly voicesService = inject(RealtimeVoicesService);
    private readonly destroyRef = inject(DestroyRef);

    settingsForm!: FormGroup;
    submitting = false;
    errorMessage: string | null = null;

    private voicesMap = signal<Record<string, RealtimeVoice[]>>({});

    // Which provider is currently selected
    activeProvider = signal<RealtimeProvider | null>(null);

    availableVoices = computed<RealtimeVoice[]>(() => {
        const provider = this.activeProvider();
        if (!provider || provider === 'elevenlabs') return [];
        return this.voicesMap()[provider] ?? [];
    });

    // Config selects for each provider
    openaiConfigItems = computed<SelectItem[]>(() => [
        { name: '— None —', value: null },
        ...this.openaiStorage.configs().map((c) => ({ name: c.custom_name, value: c.id })),
    ]);
    elevenLabsConfigItems = computed<SelectItem[]>(() => [
        { name: '— None —', value: null },
        ...this.elevenLabsStorage.configs().map((c) => ({ name: c.custom_name, value: c.id })),
    ]);
    geminiConfigItems = computed<SelectItem[]>(() => [
        { name: '— None —', value: null },
        ...this.geminiStorage.configs().map((c) => ({ name: c.custom_name, value: c.id })),
    ]);

    isElevenLabs = computed(() => this.activeProvider() === 'elevenlabs');

    readonly providers: SelectItem<RealtimeProvider>[] = [
        { value: 'openai', name: 'OpenAI' },
        { value: 'elevenlabs', name: 'ElevenLabs' },
        { value: 'gemini', name: 'Gemini' },
    ];

    ngOnInit(): void {
        // Determine initial active provider from which FK is non-null
        const ra = this.data.agent.realtime_agent;
        const openaiConfigId = this.getProviderConfigId(ra.openai_config as ProviderConfigValue);
        const elevenLabsConfigId = this.getProviderConfigId(ra.elevenlabs_config as ProviderConfigValue);
        const geminiConfigId = this.getProviderConfigId(ra.gemini_config as ProviderConfigValue);

        if (openaiConfigId != null) this.activeProvider.set('openai');
        else if (elevenLabsConfigId != null) this.activeProvider.set('elevenlabs');
        else if (geminiConfigId != null) this.activeProvider.set('gemini');
        else this.activeProvider.set('openai');

        this.settingsForm = this.fb.group({
            voice: [ra.voice ?? ''],
            threshold: [
                Number(this.data.agent.search_configs?.naive?.similarity_threshold ?? 0.2),
                [Validators.required, Validators.min(0), Validators.max(1)],
            ],
            searchLimit: [
                this.data.agent.search_configs?.naive?.search_limit ?? 5,
                [Validators.required, Validators.min(0), Validators.max(1000)],
            ],
            wakeword: [ra.wake_word],
            stopword: [ra.stop_prompt],
            openai_config: [openaiConfigId],
            elevenlabs_config: [elevenLabsConfigId],
            gemini_config: [geminiConfigId],
        });

        this.openaiStorage.getAllConfigs().pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
        this.elevenLabsStorage.getAllConfigs().pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
        this.geminiStorage.getAllConfigs().pipe(takeUntilDestroyed(this.destroyRef)).subscribe();

        this.voicesService
            .getVoices()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((map) => {
                this.voicesMap.set(map);
            });

        this.dialogRef.keydownEvents.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((event: KeyboardEvent) => {
            if ((event.ctrlKey || event.metaKey) && event.code === 'KeyS') {
                event.preventDefault();
                this.onConfirm();
            }
        });
    }

    private getProviderConfigId(config: ProviderConfigValue): number | null {
        if (typeof config === 'number') return config;
        return config?.id ?? null;
    }

    onProviderSelect(provider: unknown): void {
        this.activeProvider.set(provider as RealtimeProvider);
        if (provider === 'elevenlabs') this.settingsForm.patchValue({ voice: '' });
    }

    onVoiceChange(voiceId: string): void {
        this.settingsForm.patchValue({ voice: voiceId });
    }

    onCancel(): void {
        this.dialogRef.close();
    }

    onConfirm(): void {
        if (!this.settingsForm.valid) {
            this.settingsForm.markAllAsTouched();
            return;
        }

        this.submitting = true;
        this.errorMessage = null;

        const formValues = this.settingsForm.value;

        const provider = this.activeProvider();
        const realtimeAgentData: RealtimeAgentConfig = {
            wake_word: formValues.wakeword,
            stop_prompt: formValues.stopword,
            language: formValues.preferredLanguage,
            voice: formValues.voice,
            openai_config: provider === 'openai' ? formValues.openai_config : null,
            elevenlabs_config: provider === 'elevenlabs' ? formValues.elevenlabs_config : null,
            gemini_config: provider === 'gemini' ? formValues.gemini_config : null,
            voice_recognition_prompt: formValues.voice_recognition_prompt,
            realtime_transcription_config: formValues.realtime_transcription_config,
            realtime_config: this.data.agent.realtime_agent.realtime_config,
        };

        const existingGraph = this.data.agent.search_configs?.graph;
        const searchConfigsData = {
            naive: {
                similarity_threshold: formValues.threshold.toString(),
                search_limit: formValues.searchLimit,
            },
            ...(existingGraph ? { graph: existingGraph } : {}),
        };

        const mcp_tool: number[] = [];
        const python_code_tool: number[] = [];
        this.data.agent.tools.forEach(({ data, unique_name }) => {
            const parts = unique_name.split(':');
            if (parts[0] === 'mcp-tool') {
                mcp_tool.push((data as { id: number }).id);
            } else {
                python_code_tool.push((data as { id: number }).id);
            }
        });

        const updatedAgent: PartialUpdateAgentRequest = {
            id: this.data.agent.id,
            role: this.data.agent.role,
            goal: this.data.agent.goal,
            backstory: this.data.agent.backstory,
            realtime_agent: realtimeAgentData,
            search_configs: searchConfigsData,
            python_code_tools: python_code_tool,
            tool_ids: buildToolIdsArray(python_code_tool, mcp_tool),
        };

        this.agentsService
            .partialUpdateAgent(updatedAgent)
            .pipe(
                finalize(() => {
                    this.submitting = false;
                })
            )
            .subscribe({
                next: () => {
                    this.toastService.success('Realtime agent settings updated successfully');
                    this.dialogRef.close(updatedAgent);
                },
                error: () => {
                    this.errorMessage = 'Failed to update settings. Please try again.';
                    this.toastService.error('Failed to update settings. Please try again.');
                },
            });
    }
}
