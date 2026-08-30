import { CommonModule } from '@angular/common';
import { Component, EventEmitter, input, model, Output } from '@angular/core';
import { FormsModule, ReactiveFormsModule } from '@angular/forms';
import { ClickOutsideDirective } from '@shared/directives';
import { RealtimeVoice } from '@shared/services';

import { TooltipComponent } from '../tooltip/tooltip.component';

@Component({
    selector: 'app-voice-selector',
    imports: [CommonModule, FormsModule, ReactiveFormsModule, ClickOutsideDirective, TooltipComponent],
    templateUrl: './voice-selector.component.html',
    styleUrls: ['./voice-selector.component.scss'],
})
export class VoiceSelectorComponent {
    voices = input<RealtimeVoice[]>([]);
    disabled = input<boolean>(false);
    icon = input<string>('help_outline');
    label = input<string>('');
    required = input<boolean>(false);
    tooltipText = input<string>('');
    selectedVoice = model<string>('alloy');

    @Output() voiceChange = new EventEmitter<string>();

    isOpen = false;

    toggleDropdown(): void {
        if (!this.disabled()) {
            this.isOpen = !this.isOpen;
        }
    }

    selectVoice(voiceId: string): void {
        this.selectedVoice.set(voiceId);
        this.voiceChange.emit(voiceId);
        this.isOpen = false;
    }

    getSelectedVoiceName(): string {
        const selected = this.voices().find((voice) => voice.id === this.selectedVoice());
        return selected ? selected.name : 'Select a voice';
    }
}
