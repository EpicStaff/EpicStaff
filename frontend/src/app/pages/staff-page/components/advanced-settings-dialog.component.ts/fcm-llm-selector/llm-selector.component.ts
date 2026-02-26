import {
  Component,
  EventEmitter,
  Input,
  Output,
  OnChanges,
  SimpleChanges,
  forwardRef,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import {
  FormsModule,
  ReactiveFormsModule,
  ControlValueAccessor,
  NG_VALUE_ACCESSOR,
} from '@angular/forms';
import { ClickOutsideDirective } from '../../../../../shared/directives/click-outside.directive';
import { FullLLMConfig } from '../../../../../features/settings-dialog/services/llms/full-llm-config.service';

@Component({
  selector: 'app-llm-selector',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    ReactiveFormsModule,
    ClickOutsideDirective,
  ],
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
  @Input() llmConfigs: any[] = [];
  @Input() label: string = '';
  @Input() placeholder: string = 'Select an LLM configuration';
  @Input() disabled: boolean = false;
  @Input() loading: boolean = false;
  @Input() selectedLlmId: number | null = null;

  @Output() llmChange = new EventEmitter<number | null>();

  isOpen = false;
  value: number | null = null;
  onChange = (_: any) => {};
  onTouched = () => {};

  get selectedConfig(): any | undefined {
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

  registerOnChange(fn: any): void {
    this.onChange = fn;
  }

  registerOnTouched(fn: any): void {
    this.onTouched = fn;
  }

  setDisabledState(isDisabled: boolean): void {
    this.disabled = isDisabled;
  }
}
