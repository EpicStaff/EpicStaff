import { HttpErrorResponse } from '@angular/common/http';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    inject,
    input,
    linkedSignal,
    OnInit,
    output,
    signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatTooltip } from '@angular/material/tooltip';
import {
    BinnedSecretNoteComponent,
    CustomInputComponent,
    HelpTooltipComponent,
    HintMessageComponent,
    SelectComponent,
    SelectItem,
    ValidationErrorsComponent,
} from '@shared/components';
import { ElevenLabsRealtimeConfig, GeminiRealtimeConfig, OpenAIRealtimeConfig } from '@shared/models';
import { SecretsStorageService } from '@shared/services';
import { extractHttpErrorMessage, isClientError, trackPickedSecrets } from '@shared/utils';
import { Observable } from 'rxjs';

import { ElevenLabsRealtimeConfigStorageService } from '../../services/llms/elevenlabs-realtime-config-storage.service';
import { GeminiRealtimeConfigStorageService } from '../../services/llms/gemini-realtime-config-storage.service';
import { OpenAIRealtimeConfigStorageService } from '../../services/llms/openai-realtime-config-storage.service';

export type RealtimeProvider = 'openai' | 'elevenlabs' | 'gemini';

export type RealtimeConfig = OpenAIRealtimeConfig | ElevenLabsRealtimeConfig | GeminiRealtimeConfig;

const PROVIDERS: { key: RealtimeProvider; label: string; defaultModel: string }[] = [
    { key: 'openai', label: 'OpenAI', defaultModel: 'gpt-realtime-1.5' },
    { key: 'elevenlabs', label: 'ElevenLabs', defaultModel: 'eleven_turbo_v2_5' },
    { key: 'gemini', label: 'Gemini', defaultModel: 'gemini-3.1-flash-live-preview' },
];

function defaultModel(provider: RealtimeProvider): string {
    return PROVIDERS.find((entry) => entry.key === provider)!.defaultModel;
}

function requiredText(value: string): FormControl<string> {
    return new FormControl(value, { nonNullable: true, validators: Validators.required });
}

function optionalText(value = ''): FormControl<string> {
    return new FormControl(value, { nonNullable: true });
}

/**
 * The fields of a voice (realtime) configuration for each provider, and saving them. Used by both the
 * edit dialog and the "Add Configuration" dialog, which own the header and the Cancel / Save buttons.
 */
@Component({
    selector: 'app-realtime-config-form',
    imports: [
        ReactiveFormsModule,
        BinnedSecretNoteComponent,
        CustomInputComponent,
        HelpTooltipComponent,
        HintMessageComponent,
        MatTooltip,
        SelectComponent,
        ValidationErrorsComponent,
    ],
    templateUrl: './realtime-config-form.component.html',
    styleUrls: ['./realtime-config-form.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RealtimeConfigFormComponent implements OnInit {
    /** The config to edit, read once on init; null creates a new one. Editing keeps the provider fixed. */
    readonly config = input<RealtimeConfig | null>(null);
    readonly provider = input<RealtimeProvider>('openai');
    readonly saved = output<void>();

    readonly isSubmitting = signal(false);
    /** Why the last save failed, for the host dialog's error banner; cleared when a save starts. */
    readonly errorMessage = signal<string | null>(null);
    protected readonly selectedProvider = linkedSignal(() => this.provider());
    protected readonly isEditMode = computed(() => this.config() !== null);
    protected readonly activeForm = computed(() => this.forms[this.selectedProvider()]);
    protected readonly modelPlaceholder = computed(() => defaultModel(this.selectedProvider()));
    /**
     * Each secret select's own items: a picked secret in the recycle bin keeps its option in that select only,
     * never offered as a new choice in another.
     */
    protected readonly apiKeyItems = computed<SelectItem[]>(() =>
        this.secretsStorageService.selectItems(this.pickedApiKeyIds[this.selectedProvider()]())
    );
    protected readonly transcriptionKeyItems = computed<SelectItem[]>(() =>
        this.secretsStorageService.selectItems(this.pickedTranscriptionKeyIds())
    );

    protected readonly providers = PROVIDERS;
    protected readonly openaiForm = new FormGroup({
        custom_name: requiredText(''),
        api_key_secret_id: new FormControl<number | null>(null),
        model_name: requiredText(defaultModel('openai')),
        base_url: optionalText(),
        transcription_model_name: optionalText('whisper-1'),
        transcription_api_key_secret_id: new FormControl<number | null>(null),
        voice_recognition_prompt: optionalText(),
    });
    protected readonly elevenLabsForm = new FormGroup({
        custom_name: requiredText(''),
        api_key_secret_id: new FormControl<number | null>(null),
        model_name: requiredText(defaultModel('elevenlabs')),
        language: optionalText(),
    });
    protected readonly geminiForm = new FormGroup({
        custom_name: requiredText(''),
        api_key_secret_id: new FormControl<number | null>(null),
        model_name: requiredText(defaultModel('gemini')),
        voice_recognition_prompt: optionalText(),
    });

    private readonly forms = {
        openai: this.openaiForm,
        elevenlabs: this.elevenLabsForm,
        gemini: this.geminiForm,
    };
    private readonly pickedApiKeyIds = {
        openai: signal<number[]>([]),
        elevenlabs: signal<number[]>([]),
        gemini: signal<number[]>([]),
    };
    private readonly pickedTranscriptionKeyIds = signal<number[]>([]);
    private readonly openaiStorage = inject(OpenAIRealtimeConfigStorageService);
    private readonly elevenLabsStorage = inject(ElevenLabsRealtimeConfigStorageService);
    private readonly geminiStorage = inject(GeminiRealtimeConfigStorageService);
    private readonly secretsStorageService = inject(SecretsStorageService);
    private readonly destroyRef = inject(DestroyRef);

    ngOnInit(): void {
        const config = this.config();
        if (config) {
            // A null field keeps the form's default, as a new config would get. Typed as a plain FormGroup:
            // the config carries extra fields (id, authorship) that patchValue ignores but the typed form rejects.
            const form: FormGroup = this.activeForm();
            form.patchValue(Object.fromEntries(Object.entries(config).filter(([, value]) => value !== null)));
        }

        for (const provider of PROVIDERS) {
            trackPickedSecrets(
                this.forms[provider.key],
                ['api_key_secret_id'],
                this.pickedApiKeyIds[provider.key],
                this.destroyRef
            );
        }
        trackPickedSecrets(
            this.openaiForm,
            ['transcription_api_key_secret_id'],
            this.pickedTranscriptionKeyIds,
            this.destroyRef
        );

        this.secretsStorageService
            .getSecrets()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({ error: () => {} });
    }

    /** Validates the active provider's form and creates or updates the config; emits `saved` on success. */
    submit(): void {
        if (this.isSubmitting()) return;
        const form = this.activeForm();
        if (form.invalid) {
            form.markAllAsTouched();
            return;
        }

        this.isSubmitting.set(true);
        this.errorMessage.set(null);
        this.save()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => {
                    this.isSubmitting.set(false);
                    this.saved.emit();
                },
                error: (error: HttpErrorResponse) => {
                    this.isSubmitting.set(false);
                    // A refusal (4xx) says what to fix, e.g. a missing Secrets "Use" permission; a server error does not.
                    const fallback = 'Failed to save configuration.';
                    this.errorMessage.set(isClientError(error) ? extractHttpErrorMessage(error, fallback) : fallback);
                },
            });
    }

    protected selectProvider(provider: RealtimeProvider): void {
        if (this.isEditMode()) return;
        this.selectedProvider.set(provider);
        this.errorMessage.set(null);
    }

    private save(): Observable<unknown> {
        const id = this.config()?.id;
        switch (this.selectedProvider()) {
            case 'openai': {
                const value = this.openaiForm.getRawValue();
                return id === undefined
                    ? this.openaiStorage.createConfig(value)
                    : this.openaiStorage.updateConfig({ ...value, id });
            }
            case 'elevenlabs': {
                const value = this.elevenLabsForm.getRawValue();
                return id === undefined
                    ? this.elevenLabsStorage.createConfig(value)
                    : this.elevenLabsStorage.updateConfig({ ...value, id });
            }
            case 'gemini': {
                const value = this.geminiForm.getRawValue();
                return id === undefined
                    ? this.geminiStorage.createConfig(value)
                    : this.geminiStorage.updateConfig({ ...value, id });
            }
        }
    }
}
