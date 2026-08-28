import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { ButtonComponent, IconButtonComponent, SelectItem, TabButtonComponent } from '@shared/components';
import { FullLLMConfigService, RealtimeVoice, RealtimeVoicesService } from '@shared/services';

import {
    AdvancedTabComponent,
    ExecutionTabComponent,
    GeneralTabComponent,
    RealtimeProvider,
    Tab,
    TabId,
    VoiceTabComponent,
} from '../../../../../../../shared/components/create-agent-form-dialog/tabs';
import { ElevenLabsRealtimeConfigStorageService } from '../../../../../../configure-models/services/llms/elevenlabs-realtime-config-storage.service';
import { GeminiRealtimeConfigStorageService } from '../../../../../../configure-models/services/llms/gemini-realtime-config-storage.service';
import { OpenAIRealtimeConfigStorageService } from '../../../../../../configure-models/services/llms/openai-realtime-config-storage.service';
import { AGENT_TOOL_DEFAULTS } from '../../../../../models/agent-definition.model';

export interface AgentAdditionalSettingsData {
    fcm_llm_config: number | null;
    openai_config: number | null;
    elevenlabs_config: number | null;
    gemini_config: number | null;
    voice: string | null;
    max_iter: number | null;
    max_rpm: number | null;
    max_execution_time: number | null;
    max_retry_limit: number | null;
    cache: boolean | null;
    max_tool_calls: number | null;
    tool_timeout: number | null;
    max_consecutive_failures: number | null;
    schema_max_retries: number | null;
}

export interface AgentAdditionalSettingsResult {
    fcm_llm_config: number | null;
    openai_config: number | null;
    elevenlabs_config: number | null;
    gemini_config: number | null;
    voice: string;
    max_iter: number;
    max_rpm: number;
    max_execution_time: number;
    max_retry_limit: number;
    cache: boolean;
    max_tool_calls: number;
    tool_timeout: number;
    max_consecutive_failures: number;
    schema_max_retries: number;
}

@Component({
    selector: 'app-agent-additional-settings-dialog',
    imports: [
        ReactiveFormsModule,
        IconButtonComponent,
        ButtonComponent,
        TabButtonComponent,
        GeneralTabComponent,
        ExecutionTabComponent,
        AdvancedTabComponent,
        VoiceTabComponent,
    ],
    templateUrl: './agent-additional-settings-dialog.component.html',
    styleUrls: ['./agent-additional-settings-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AgentAdditionalSettingsDialogComponent implements OnInit {
    private readonly fb = inject(FormBuilder);
    private readonly destroyRef = inject(DestroyRef);
    private readonly fullLlmConfigService = inject(FullLLMConfigService);
    private readonly openaiStorage = inject(OpenAIRealtimeConfigStorageService);
    private readonly elevenLabsStorage = inject(ElevenLabsRealtimeConfigStorageService);
    private readonly geminiStorage = inject(GeminiRealtimeConfigStorageService);
    private readonly voicesService = inject(RealtimeVoicesService);
    private readonly data = inject<AgentAdditionalSettingsData>(DIALOG_DATA);

    readonly dialogRef = inject<DialogRef<AgentAdditionalSettingsResult | undefined>>(DialogRef);

    readonly activeTab = signal<TabId>(TabId.GENERAL);
    readonly loadingLLMs = signal<boolean>(true);
    readonly combinedLLMs = this.fullLlmConfigService.fullConfigs;
    readonly voicesMap = signal<Record<string, RealtimeVoice[]>>({});

    readonly tabs: Tab[] = [
        { id: TabId.GENERAL, label: 'General' },
        { id: TabId.VOICE, label: 'Voice' },
        { id: TabId.EXECUTION, label: 'Execution' },
        { id: TabId.ADVANCED, label: 'Advanced' },
    ];

    readonly activeProvider = signal<RealtimeProvider | null>(this.initialProvider());

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

    readonly form: FormGroup = this.fb.group({
        fcm_llm_config: [this.data.fcm_llm_config],
        openai_config: [this.data.openai_config],
        elevenlabs_config: [this.data.elevenlabs_config],
        gemini_config: [this.data.gemini_config],
        voice: [this.data.voice ?? 'alloy'],
        max_iter: [this.data.max_iter ?? 10, [Validators.min(1), Validators.max(30)]],
        max_rpm: [this.data.max_rpm ?? 10, [Validators.min(1), Validators.max(30)]],
        max_execution_time: [this.data.max_execution_time ?? 60, [Validators.min(1), Validators.max(600)]],
        max_retry_limit: [this.data.max_retry_limit ?? 3, [Validators.min(0), Validators.max(10)]],
        schema_max_retries: [
            this.data.schema_max_retries ?? AGENT_TOOL_DEFAULTS.schema_max_retries,
            [Validators.min(0), Validators.max(20)],
        ],
        max_tool_calls: [
            this.data.max_tool_calls ?? AGENT_TOOL_DEFAULTS.max_tool_calls,
            [Validators.min(1), Validators.max(100)],
        ],
        tool_timeout: [
            this.data.tool_timeout ?? AGENT_TOOL_DEFAULTS.tool_timeout,
            [Validators.min(1), Validators.max(600)],
        ],
        max_consecutive_failures: [
            this.data.max_consecutive_failures ?? AGENT_TOOL_DEFAULTS.max_consecutive_failures,
            [Validators.min(1), Validators.max(20)],
        ],
        // Cache is not implemented on the backend runtime yet — shown but disabled.
        cache: [{ value: this.data.cache ?? false, disabled: true }],
    });

    ngOnInit(): void {
        this.fullLlmConfigService
            .getFullLLMConfigs()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => this.loadingLLMs.set(false),
                error: () => this.loadingLLMs.set(false),
            });

        this.voicesService
            .getVoices()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((map) => {
                this.voicesMap.set(map);
            });

        this.openaiStorage.getAllConfigs().pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
        this.elevenLabsStorage.getAllConfigs().pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
        this.geminiStorage.getAllConfigs().pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
    }

    onProviderSelect(provider: RealtimeProvider): void {
        this.activeProvider.set(provider);
        // ElevenLabs uses a free-form voice id — clear so the user re-enters it.
        if (provider === 'elevenlabs') this.form.patchValue({ voice: '' });
    }

    save(): void {
        if (this.form.invalid) return;

        const provider = this.activeProvider();
        const v = this.form.getRawValue();
        this.dialogRef.close({
            ...v,
            voice: v.voice ?? '',
            openai_config: provider === 'openai' ? v.openai_config : null,
            elevenlabs_config: provider === 'elevenlabs' ? v.elevenlabs_config : null,
            gemini_config: provider === 'gemini' ? v.gemini_config : null,
        } as AgentAdditionalSettingsResult);
    }

    private initialProvider(): RealtimeProvider {
        if (this.data.gemini_config != null) return 'gemini';
        if (this.data.elevenlabs_config != null) return 'elevenlabs';
        return 'openai';
    }

    protected readonly TabId = TabId;
}
