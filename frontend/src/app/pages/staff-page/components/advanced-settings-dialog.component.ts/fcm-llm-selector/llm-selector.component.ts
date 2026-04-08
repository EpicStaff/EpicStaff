import { CommonModule } from '@angular/common';
import { Component, EventEmitter, forwardRef, Input, OnChanges, Output, SimpleChanges } from '@angular/core';
import { ControlValueAccessor, FormsModule, NG_VALUE_ACCESSOR, ReactiveFormsModule } from '@angular/forms';

import { FullLLMConfig } from '../../../../../features/settings-dialog/services/llms/full-llm-config.service';
import { AppSvgIconComponent } from '../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { ClickOutsideDirective } from '../../../../../shared/directives/click-outside.directive';

@Component({
    selector: 'app-llm-selector',
    standalone: true,
    imports: [CommonModule, FormsModule, ReactiveFormsModule, ClickOutsideDirective, AppSvgIconComponent],
    templateUrl: './llm-selector.component.html',
    styleUrls: ['./llm-selector.component.scss'],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => LlmSelectorComponent),
            multi: true,
        },
    ],
})
export class LlmSelectorComponent implements ControlValueAccessor, OnChanges {
    @Input() llmConfigs: FullLLMConfig[] = [];
    @Input() label: string = '';
    @Input() placeholder: string = 'Select an LLM configuration';
    @Input() disabled: boolean = false;
    @Input() loading: boolean = false;
    @Input() selectedLlmId: number | null = null;

    @Output() llmChange = new EventEmitter<number | null>();

    isOpen = false;
    value: number | null = null;
    onChange: (value: number | null) => void = () => {};
    onTouched = () => {};

    get selectedConfig(): FullLLMConfig | undefined {
        return this.llmConfigs.find((config) => config.id === this.value);
    }

    ngOnChanges(changes: SimpleChanges): void {
        if (changes['selectedLlmId'] && this.selectedLlmId !== undefined) {
            this.value = this.selectedLlmId;
        }
    }

    toggleDropdown(): void {
        if (!this.disabled && !this.loading) {
            this.isOpen = !this.isOpen;
            this.onTouched();
        }
    }

    selectLlm(config: FullLLMConfig | null): void {
        const llmId = config?.id || null;
        this.value = llmId;
        this.llmChange.emit(llmId);
        this.onChange(llmId);
        this.onTouched();
        this.isOpen = false;
    }

    writeValue(value: number | null): void {
        this.value = value;
    }

    registerOnChange(fn: (value: number | null) => void): void {
        this.onChange = fn;
    }

    registerOnTouched(fn: () => void): void {
        this.onTouched = fn;
    }

    setDisabledState(isDisabled: boolean): void {
        this.disabled = isDisabled;
    }
}