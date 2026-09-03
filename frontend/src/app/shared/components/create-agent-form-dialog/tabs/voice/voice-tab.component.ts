import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { FormGroup, ReactiveFormsModule } from '@angular/forms';
import {
    CustomInputComponent,
    RadioButtonComponent,
    SelectComponent,
    SelectItem,
    VoiceSelectorComponent,
} from '@shared/components';
import { RealtimeVoice } from '@shared/services';

export type RealtimeProvider = 'openai' | 'elevenlabs' | 'gemini';

@Component({
    selector: 'app-voice-tab',
    imports: [
        CommonModule,
        ReactiveFormsModule,
        SelectComponent,
        VoiceSelectorComponent,
        RadioButtonComponent,
        CustomInputComponent,
    ],
    templateUrl: './voice-tab.component.html',
    styleUrls: ['../tab.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class VoiceTabComponent {
    form = input.required<FormGroup>();
    activeProvider = input<RealtimeProvider | null>(null);
    openaiConfigItems = input<SelectItem[]>([]);
    elevenLabsConfigItems = input<SelectItem[]>([]);
    geminiConfigItems = input<SelectItem[]>([]);
    voicesMap = input.required<Record<string, RealtimeVoice[]>>();

    providerChange = output<RealtimeProvider>();

    readonly providers: SelectItem<RealtimeProvider>[] = [
        { value: 'openai', name: 'OpenAI' },
        { value: 'elevenlabs', name: 'ElevenLabs' },
        { value: 'gemini', name: 'Gemini' },
    ];

    availableVoices = computed<RealtimeVoice[]>(() => {
        const provider = this.activeProvider();
        if (!provider || provider === 'elevenlabs') return [];
        return this.voicesMap()[provider] ?? [];
    });

    onProviderSelect(provider: unknown): void {
        this.providerChange.emit(provider as RealtimeProvider);
    }

    onVoiceChange(voiceId: string): void {
        this.form().patchValue({ voice: voiceId });
    }
}
