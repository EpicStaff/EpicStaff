import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { NgIf } from '@angular/common';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    ButtonComponent,
    CustomInputComponent,
    HelpTooltipComponent,
    ValidationErrorsComponent,
} from '@shared/components';
import { catchError, EMPTY, Observable, tap } from 'rxjs';

import { ElevenLabsRealtimeConfig } from '../../../../shared/models/realtime-voice/elevenlabs-realtime-config.model';
import { GeminiRealtimeConfig } from '../../../../shared/models/realtime-voice/gemini-realtime-config.model';
import { OpenAIRealtimeConfig } from '../../../../shared/models/realtime-voice/openai-realtime-config.model';
import { ElevenLabsRealtimeConfigStorageService } from '../../services/llms/elevenlabs-realtime-config-storage.service';
import { GeminiRealtimeConfigStorageService } from '../../services/llms/gemini-realtime-config-storage.service';
import { OpenAIRealtimeConfigStorageService } from '../../services/llms/openai-realtime-config-storage.service';

export type RealtimeProvider = 'openai' | 'elevenlabs' | 'gemini';

export interface RealtimeConfigDialogData {
    action: 'create' | 'update';
    provider: RealtimeProvider;
    config: OpenAIRealtimeConfig | ElevenLabsRealtimeConfig | GeminiRealtimeConfig | null;
}

@Component({
    selector: 'app-realtime-config-dialog',
    templateUrl: './realtime-config-dialog.component.html',
    styleUrls: ['./realtime-config-dialog.component.scss'],
    imports: [
        ReactiveFormsModule,
        CustomInputComponent,
        ButtonComponent,
        ValidationErrorsComponent,
        HelpTooltipComponent,
        NgIf,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RealtimeConfigDialogComponent {
    private readonly fb = inject(FormBuilder);
    private readonly dialogRef = inject(DialogRef);
    private readonly openaiStorage = inject(OpenAIRealtimeConfigStorageService);
    private readonly elevenLabsStorage = inject(ElevenLabsRealtimeConfigStorageService);
    private readonly geminiStorage = inject(GeminiRealtimeConfigStorageService);
    private readonly destroyRef = inject(DestroyRef);
    readonly data = inject<RealtimeConfigDialogData>(DIALOG_DATA);

    isSubmitting = signal(false);
    errorMessage = signal<string | null>(null);
    selectedProvider = signal<RealtimeProvider>(this.data.provider ?? 'openai');

    readonly providers: { key: RealtimeProvider; label: string }[] = [
        { key: 'openai', label: 'OpenAI' },
        { key: 'elevenlabs', label: 'ElevenLabs' },
        { key: 'gemini', label: 'Gemini' },
    ];

    openaiForm = this.fb.nonNullable.group({
        custom_name: [
            (this.data.provider === 'openai' ? (this.data.config as OpenAIRealtimeConfig)?.custom_name : null) ?? '',
            Validators.required,
        ],
        api_key: [(this.data.provider === 'openai' ? (this.data.config as OpenAIRealtimeConfig)?.api_key : null) ?? ''],
        model_name: [
            (this.data.provider === 'openai' ? (this.data.config as OpenAIRealtimeConfig)?.model_name : null) ??
                'gpt-realtime-1.5',
            Validators.required,
        ],
        transcription_model_name: [
            (this.data.provider === 'openai'
                ? (this.data.config as OpenAIRealtimeConfig)?.transcription_model_name
                : null) ?? 'whisper-1',
        ],
        transcription_api_key: [
            (this.data.provider === 'openai'
                ? (this.data.config as OpenAIRealtimeConfig)?.transcription_api_key
                : null) ?? '',
        ],
        voice_recognition_prompt: [
            (this.data.provider === 'openai'
                ? (this.data.config as OpenAIRealtimeConfig)?.voice_recognition_prompt
                : null) ?? '',
        ],
    });

    elevenLabsForm = this.fb.nonNullable.group({
        custom_name: [
            (this.data.provider === 'elevenlabs'
                ? (this.data.config as ElevenLabsRealtimeConfig)?.custom_name
                : null) ?? '',
            Validators.required,
        ],
        api_key: [
            (this.data.provider === 'elevenlabs' ? (this.data.config as ElevenLabsRealtimeConfig)?.api_key : null) ??
                '',
        ],
        model_name: [
            (this.data.provider === 'elevenlabs' ? (this.data.config as ElevenLabsRealtimeConfig)?.model_name : null) ??
                'eleven_turbo_v2_5',
            Validators.required,
        ],
        language: [
            (this.data.provider === 'elevenlabs' ? (this.data.config as ElevenLabsRealtimeConfig)?.language : null) ??
                '',
        ],
    });

    geminiForm = this.fb.nonNullable.group({
        custom_name: [
            (this.data.provider === 'gemini' ? (this.data.config as GeminiRealtimeConfig)?.custom_name : null) ?? '',
            Validators.required,
        ],
        api_key: [(this.data.provider === 'gemini' ? (this.data.config as GeminiRealtimeConfig)?.api_key : null) ?? ''],
        model_name: [
            (this.data.provider === 'gemini' ? (this.data.config as GeminiRealtimeConfig)?.model_name : null) ??
                'gemini-3.1-flash-live-preview',
            Validators.required,
        ],
        voice_recognition_prompt: [
            (this.data.provider === 'gemini'
                ? (this.data.config as GeminiRealtimeConfig)?.voice_recognition_prompt
                : null) ?? '',
        ],
    });

    private readonly _keyboard$ = this.dialogRef.keydownEvents
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe((e: KeyboardEvent) => {
            if ((e.ctrlKey || e.metaKey) && e.code === 'KeyS') {
                e.preventDefault();
                this.onSubmit();
            }
        });

    selectProvider(provider: RealtimeProvider): void {
        if (this.data.action === 'update') return;
        this.selectedProvider.set(provider);
        this.errorMessage.set(null);
    }

    onSubmit(): void {
        const provider = this.selectedProvider();
        const activeForm =
            provider === 'openai' ? this.openaiForm : provider === 'elevenlabs' ? this.elevenLabsForm : this.geminiForm;

        if (activeForm.invalid) {
            activeForm.markAllAsTouched();
            return;
        }

        this.isSubmitting.set(true);
        const v = activeForm.getRawValue();

        let obs: Observable<unknown>;
        if (provider === 'openai') {
            obs =
                this.data.action === 'create'
                    ? this.openaiStorage.createConfig(v)
                    : this.openaiStorage.updateConfig({ ...v, id: (this.data.config as OpenAIRealtimeConfig)!.id });
        } else if (provider === 'elevenlabs') {
            obs =
                this.data.action === 'create'
                    ? this.elevenLabsStorage.createConfig(v)
                    : this.elevenLabsStorage.updateConfig({
                          ...v,
                          id: (this.data.config as ElevenLabsRealtimeConfig)!.id,
                      });
        } else {
            obs =
                this.data.action === 'create'
                    ? this.geminiStorage.createConfig(v)
                    : this.geminiStorage.updateConfig({ ...v, id: (this.data.config as GeminiRealtimeConfig)!.id });
        }

        obs.pipe(
            tap(() => this.dialogRef.close(true)),
            catchError(() => {
                this.errorMessage.set('Failed to save configuration.');
                this.isSubmitting.set(false);
                return EMPTY;
            }),
            takeUntilDestroyed(this.destroyRef)
        ).subscribe();
    }

    onCancel(): void {
        this.dialogRef.close(null);
    }
}
