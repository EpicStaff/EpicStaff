import { ChangeDetectionStrategy, Component, computed, effect, forwardRef, input, model, signal } from '@angular/core';
import {
    AbstractControl,
    ControlValueAccessor,
    FormControl,
    NG_VALUE_ACCESSOR,
    ReactiveFormsModule,
    ValidationErrors,
} from '@angular/forms';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { ValidationErrorsComponent } from '../app-validation-errors/validation-errors.component';
import { CheckboxComponent } from '../checkbox/checkbox.component';
import { CustomInputComponent } from '../form-input/form-input.component';
import { TooltipComponent } from '../tooltip/tooltip.component';

@Component({
    selector: 'app-chips-input',
    templateUrl: './chips-input.component.html',
    styleUrls: ['./chips-input.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [
        TooltipComponent,
        CustomInputComponent,
        ReactiveFormsModule,
        ValidationErrorsComponent,
        AppSvgIconComponent,
        CheckboxComponent,
    ],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => ChipsInputComponent),
            multi: true,
        },
    ],
})
export class ChipsInputComponent implements ControlValueAccessor {
    icon = input<string>('help_outline');
    label = input<string>('');
    required = input<boolean>(false);
    tooltipText = input<string>('');
    inputPlaceholder = input<string>('Type here...');
    separatorPlaceholder = input<string>('Add comma separated values...');
    minItemLength = input<number | null>(null);
    maxItemLength = input<number | null>(null);
    showSeparatorToggle = input(false);
    separatorLabel = input('Split by comma');

    private onChange: (value: string[]) => void = () => {};
    private onTouched: () => void = () => {};
    private isDisabled = false;

    value = model<string[]>([]);
    inputControl = new FormControl<string>('', []);
    separatorEnabled = signal(false);
    activePlaceholder = computed(() =>
        this.separatorEnabled() ? this.separatorPlaceholder() : this.inputPlaceholder()
    );

    constructor() {
        effect(() => {
            const min = this.minItemLength();
            const max = this.maxItemLength();
            const useSeparator = this.separatorEnabled();

            const validators = [];

            if (min !== null || max !== null) {
                validators.push(
                    useSeparator ? this.separatedItemsValidator(',', min, max) : this.itemValidator(min, max)
                );
            }

            this.inputControl.setValidators(validators);
            this.inputControl.updateValueAndValidity();
        });
    }

    private itemValidator(min: number | null, max: number | null) {
        return (control: AbstractControl): ValidationErrors | null => {
            const value = control.value?.trim();
            if (!value) return null;
            if (min !== null && value.length < min)
                return { minlength: { requiredLength: min, actualLength: value.length } };
            if (max !== null && value.length > max)
                return { maxlength: { requiredLength: max, actualLength: value.length } };
            return null;
        };
    }

    private separatedItemsValidator(sep: string, min: number | null, max: number | null) {
        return (control: AbstractControl): ValidationErrors | null => {
            const raw = control.value?.trim();
            if (!raw) return null;

            const items = raw
                .split(sep)
                .map((s: string) => s.trim())
                .filter(Boolean);
            for (const item of items) {
                if (min !== null && item.length < min)
                    return { minlength: { requiredLength: min, actualLength: item.length } };
                if (max !== null && item.length > max)
                    return { maxlength: { requiredLength: max, actualLength: item.length } };
            }
            return null;
        };
    }

    onAdd() {
        const raw = this.inputControl.value?.trim();
        if (!raw || this.isDisabled || this.inputControl.invalid) return;

        const items = this.separatorEnabled()
            ? raw
                  .split(',')
                  .map((s) => s.trim())
                  .filter(Boolean)
            : [raw];

        const next = [...this.value(), ...items];
        this.updateValue(next);

        this.inputControl.reset('');
    }

    onKeydown(event: KeyboardEvent) {
        if (event.key === 'Enter') {
            event.preventDefault();
            this.onAdd();
        }
    }

    onRemove(index: number) {
        if (this.isDisabled) return;

        const next = this.value().filter((_, i) => i !== index);
        this.updateValue(next);
    }

    private updateValue(next: string[]) {
        this.value.set(next);
        this.onChange(next);
    }

    writeValue(value: string[] | null): void {
        this.value.set(value ?? []);
    }

    registerOnChange(fn: (value: string[]) => void): void {
        this.onChange = fn;
    }

    registerOnTouched(fn: () => void): void {
        this.onTouched = fn;
    }

    setDisabledState(isDisabled: boolean): void {
        this.isDisabled = isDisabled;
    }
}
