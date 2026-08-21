import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, Output } from '@angular/core';
import { FormsModule, ReactiveFormsModule } from '@angular/forms';

import { Voice } from '../../../../../../../shared/constants/realtime-voice.constants';
import { ClickOutsideDirective } from '../../../../../../../shared/directives/click-outside.directive';

@Component({
    selector: 'app-voice-selector',
    standalone: true,
    imports: [CommonModule, FormsModule, ReactiveFormsModule, ClickOutsideDirective],
    templateUrl: './voice-selector.component.html',
    styleUrls: ['./voice-selector.component.scss'],
})
export class VoiceSelectorComponent {
    @Input() selectedVoice: string = 'alloy';
    @Input() voices: Voice[] = [];
    @Input() label: string = 'Voice';
    @Input() disabled: boolean = false;

    @Output() voiceChange = new EventEmitter<string>();

    isOpen = false;

    toggleDropdown(): void {
        if (!this.disabled) {
            this.isOpen = !this.isOpen;
        }
    }

    selectVoice(voiceId: string): void {
        this.selectedVoice = voiceId;
        this.voiceChange.emit(voiceId);
        this.isOpen = false;
    }

    getSelectedVoiceName(): string {
        const selected = this.voices.find((voice) => voice.id === this.selectedVoice);
        return selected ? selected.name : 'Select a voice';
    }
}
