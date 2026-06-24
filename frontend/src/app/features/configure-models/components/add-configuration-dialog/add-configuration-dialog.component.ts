import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { NgIf } from '@angular/common';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    ButtonComponent,
    CustomInputComponent,
    HelpTooltipComponent,
    IconButtonComponent,
    InputNumberComponent,
    JsonEditorFormFieldComponent,
    KeyValueListComponent,
    SliderWithStepperComponent,
    ValidationErrorsComponent,
} from '@shared/components';
import { LLMModel, LLMProvider, ModelTypes } from '@shared/models';
import { catchError, EMPTY, Observable, tap } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { LlmConfigStorageService } from '../../../../shared/services/llms/llm-config-storage.service';
import { ElevenLabsRealtimeConfigStorageService } from '../../services/llms/elevenlabs-realtime-config-storage.service';
import { GeminiRealtimeConfigStorageService } from '../../services/llms/gemini-realtime-config-storage.service';
import { OpenAIRealtimeConfigStorageService } from '../../services/llms/openai-realtime-config-storage.service';
import { LlmModelSelectorComponent } from '../llm-model-selector/llm-model-selector.component';
import { RealtimeProvider } from '../realtime-config-dialog/realtime-config-dialog.component';

export type ConfigTab = 'llm' | 'realtime';

@Component({
    selector: 'app-add-configuration-dialog',
    templateUrl: './add-configuration-dialog.component.html',
    styleUrls: ['./add-configuration-dialog.component.scss'],
    imports: [
        ReactiveFormsModule,
        NgIf,
        IconButtonComponent,
        HelpTooltipComponent,
        ButtonComponent,
        CustomInputComponent,
        ValidationErrorsComponent,
        KeyValueListComponent,
        SliderWithStepperComponent,
        InputNumberComponent,
        JsonEditorFormFieldComponent,
        LlmModelSelectorComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AddConfigurationDialogComponent implements OnInit {
    private readonly fb = inject(FormBuilder);
    private readonly destroyRef = inject(DestroyRef);
    private readonly llmStorage = inject(LlmConfigStorageService);
    private readonly openaiStorage = inject(OpenAIRealtimeConfigStorageService);
    private readonly elevenLabsStorage = inject(ElevenLabsRealtimeConfigStorageService);
    private readonly geminiStorage = inject(GeminiRealtimeConfigStorageService);
    private readonly toast = inject(ToastService);
    readonly dialogRef = inject(DialogRef);
    readonly data = inject<{ initialTab?: ConfigTab }>(DIALOG_DATA, { optional: true });

    activeTab = signal<ConfigTab>(this.data?.initialTab ?? 'llm');
    selectedProvider = signal<RealtimeProvider>('openai');
    isSubmitting = signal(false);
    errorMessage = signal<string | null>(null);

    readonly realtimeProviders: { key: RealtimeProvider; label: string }[] = [
        { key: 'openai', label: 'OpenAI' },
        { key: 'elevenlabs', label: 'ElevenLabs' },
        { key: 'gemini', label: 'Gemini' },
    ];

    llmForm!: FormGroup;

    openaiForm = this.fb.nonNullable.group({
        custom_name: ['', Validators.required],
        api_key: [''],
        model_name: ['gpt-realtime-1.5', Validators.required],
        transcription_model_name: ['whisper-1'],
        transcription_api_key: [''],
        voice_recognition_prompt: [''],
    });

    elevenLabsForm = this.fb.nonNullable.group({
        custom_name: ['', Validators.required],
        api_key: [''],
        model_name: ['eleven_turbo_v2_5', Validators.required],
        language: [''],
    });

    geminiForm = this.fb.nonNullable.group({
        custom_name: ['', Validators.required],
        api_key: [''],
        model_name: ['gemini-3.1-flash-live-preview', Validators.required],
        voice_recognition_prompt: [''],
    });

    protected readonly ModelTypes = ModelTypes;

    ngOnInit(): void {
        this.llmForm = this.fb.group({
            custom_name: ['', [Validators.required]],
            api_key: [''],
            model: [null, [Validators.required]],
            temperature: [0.5, [Validators.min(0), Validators.max(1)]],
            top_p: [1, [Validators.min(0.1)]],
            stop: [null],
            max_tokens: [4096, [Validators.min(500), Validators.max(2147483647)]],
            presence_penalty: [0],
            frequency_penalty: [0],
            logit_bias: [null],
            response_format: [null],
            seed: [null, [Validators.min(-2147483648), Validators.max(2147483647)]],
            headers: [{}],
            extra_headers: [{}],
            timeout: [120, [Validators.min(1), Validators.max(600)]],
            is_visible: [true],
        });

        this.dialogRef.keydownEvents.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((e: KeyboardEvent) => {
            if ((e.ctrlKey || e.metaKey) && e.code === 'KeyS') {
                e.preventDefault();
                this.onSubmit();
            }
        });
    }

    onModelChanged(data: { model: LLMModel; provider: LLMProvider }): void {
        const nameControl = this.llmForm.get('custom_name');
        if (nameControl && !nameControl.value) {
            nameControl.setValue(`${data.provider.name}/${data.model.name}`);
        }
    }

    selectProvider(provider: RealtimeProvider): void {
        this.selectedProvider.set(provider);
        this.errorMessage.set(null);
    }

    setActiveTab(tab: ConfigTab): void {
        this.activeTab.set(tab);
        this.errorMessage.set(null);
    }

    onSubmit(): void {
        if (this.activeTab() === 'llm') {
            this.submitLlm();
        } else {
            this.submitRealtime();
        }
    }

    private submitLlm(): void {
        if (this.llmForm.invalid || this.isSubmitting()) {
            this.llmForm.markAllAsTouched();
            return;
        }
        this.isSubmitting.set(true);
        this.llmStorage
            .createConfig(this.llmForm.value)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => {
                    this.isSubmitting.set(false);
                    this.toast.success('LLM configuration created successfully.');
                    this.dialogRef.close(true);
                },
                error: () => {
                    this.isSubmitting.set(false);
                    this.toast.error('Failed to create LLM configuration.');
                },
            });
    }

    private submitRealtime(): void {
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
            obs = this.openaiStorage.createConfig(v);
        } else if (provider === 'elevenlabs') {
            obs = this.elevenLabsStorage.createConfig(v);
        } else {
            obs = this.geminiStorage.createConfig(v);
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
