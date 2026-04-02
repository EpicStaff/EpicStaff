import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, Output } from '@angular/core';

import { EnhancedTranscriptionConfig } from '../../../../../../../features/transcription/models/transcription-config.model';
import { AppIconComponent } from '../../../../../../../shared/components/app-icon/app-icon.component';
import { ClickOutsideDirective } from '../../../../../../../shared/directives/click-outside.directive';

@Component({
    selector: 'app-transcription-config-selector',
    standalone: true,
    imports: [CommonModule, ClickOutsideDirective, AppIconComponent],
    templateUrl: './transcription-config-selector.component.html',
    styleUrls: ['./transcription-config-selector.component.scss'],
})
export class TranscriptionConfigSelectorComponent {
    @Input() label: string = '';
    @Input() configs: EnhancedTranscriptionConfig[] = [];
    @Input() selectedConfigId: number | null = null;
    @Input() disabled: boolean = false;
    @Input() loading: boolean = false;

    @Output() configChange = new EventEmitter<number | null>();
    @Output() createNew = new EventEmitter<void>();
    @Output() deleteConfig = new EventEmitter<number>();

    isOpen = false;

    toggleDropdown(): void {
        if (!this.disabled) {
            this.isOpen = !this.isOpen;
        }
    }

    selectConfig(configId: number | null): void {
        this.selectedConfigId = configId;
        this.configChange.emit(configId);
        this.isOpen = false;
    }

    onDeleteConfig(event: Event, configId: number): void {
        event.stopPropagation(); // Prevent dropdown from closing
        this.deleteConfig.emit(configId);
    }

    getSelectedConfigName(): string {
        if (this.selectedConfigId === null) {
            return 'None';
        }

        const selectedConfig = this.configs.find((config) => config.id === this.selectedConfigId);
        return selectedConfig ? `${selectedConfig.custom_name} (${selectedConfig.model_name})` : 'None';
    }

    onCreateNew(): void {
        this.createNew.emit();
        this.isOpen = false;
    }
}
