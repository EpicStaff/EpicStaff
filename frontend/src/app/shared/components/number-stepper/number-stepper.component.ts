import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, forwardRef, input, model, output, signal } from '@angular/core';
import { ControlValueAccessor, FormControl, FormsModule, NG_VALUE_ACCESSOR } from '@angular/forms';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { TooltipComponent } from '../tooltip/tooltip.component';

export type StepperSize = 'sm' | 'md' | 'lg';

@Component({
    selector: 'app-number-stepper',
    standalone: true,
    imports: [CommonModule, FormsModule, AppSvgIconComponent, TooltipComponent],
    templateUrl: './number-stepper.component.html',
    styleUrls: ['./number-stepper.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => NumberStepperComponent),
            multi: true,
        },
    ],
})

//TODO can be replaced with app-input-number
export class NumberStepperComponent implements ControlValueAccessor {
    label = input<string>('');
    tooltipText = input<string>('');
    placeholder = input<string>('0');
    min = input<number | null>(null);
    max = input<number | null>(null);
    step = input<number>(1);
    size = input<StepperSize>('md');
    control = input<FormControl | null>(null);
    integer = input<boolean>(false);

    value = model<number | null>(null);
    changed = output<number | null>();

    onChange: (value: number | null) => void = () => {};
    onTouched: () => void = () => {};
    isDisabled = signal(false);
    hovered = signal(false);

    hasError = computed(() => {
        const val = this.value();
        const minVal = this.min();
        const maxVal = this.max();

        if (val !== null) {
            if (minVal !== null && val < minVal) return true;
            if (maxVal !== null && val > maxVal) return true;
        }

        const ctrl = this.control();
        if (!ctrl) return false;

        if (ctrl.hasError('required')) return true;

        return false;
    });

    errorMessage = computed(() => {
        if (!this.hasError()) return '';

        const val = this.value();
        const minVal = this.min();
        const maxVal = this.max();

        if (val !== null && minVal !== null && val < minVal) {
            return `Minimum value is ${minVal}`;
        }
        if (val !== null && maxVal !== null && val > maxVal) {
            return `Maximum value is ${maxVal}`;
        }

        const ctrl = this.control();
        if (!ctrl) return 'Invalid value';

        const errors = ctrl.errors;
        if (!errors) return 'Invalid value';

        if (errors['required']) return 'This field is required';
        if (errors['min']) {
            const min = errors['min'].min;
            return `Minimum value is ${min}`;
        }
        if (errors['max']) {
            const max = errors['max'].max;
            return `Maximum value is ${max}`;
        }
        return 'Invalid value';
    });

    displayValue = computed(() => {
        const val = this.value();
        if (val === null || val === undefined) return '';
        if (this.integer()) {
            const maxVal = this.max() ?? Number.MAX_SAFE_INTEGER;
            return String(Math.min(Math.round(val), maxVal));
        }
        return val.toString();
    });

    canStepDown = computed(() => {
        const val = this.value();
        const minVal = this.min();
        if (val === null) return true;
        if (minVal === null) return true;
        return val > minVal;
    });

    canStepUp = computed(() => {
        const val = this.value();
        const maxVal = this.max();
        if (val === null) return true;
        if (maxVal === null) return true;
        return val < maxVal;
    });

    stepIconSize = computed(() => {
        switch (this.size()) {
            case 'lg':
                return '14px';
            case 'md':
                return '12px';
            default:
                return '11px';
        }
    });

    onKeyDown(event: KeyboardEvent) {
        const allowedKeys = [
            'Backspace',
            'Delete',
            'Tab',
            'Escape',
            'Enter',
            'Home',
            'End',
            'ArrowLeft',
            'ArrowRight',
            'ArrowUp',
            'ArrowDown',
        ];

        if (allowedKeys.includes(event.key)) {
            return;
        }

        if ((event.ctrlKey || event.metaKey) && ['a', 'c', 'v', 'x', 'z'].includes(event.key.toLowerCase())) {
            return;
        }

        const minVal = this.min();
        const allowNegative = minVal === null || minVal < 0;
        const target = event.target as HTMLInputElement;
        const currentValue = target.value;
        const cursorPos = target.selectionStart || 0;

        if (event.key === '-' && allowNegative && cursorPos === 0 && !currentValue.includes('-')) {
            return;
        }

        if (event.key === '.' && !this.integer() && !currentValue.includes('.')) {
            return;
        }

        const isDigit = /^[0-9]$/.test(event.key);
        if (!isDigit) {
            event.preventDefault();
        }
    }

    onBlur(): void {
        if (this.integer()) {
            const minVal = this.min();
            const maxVal = this.max() ?? Number.MAX_SAFE_INTEGER;
            const val = this.value();
            if (val === null || (minVal !== null && val < minVal)) {
                this.updateValue(minVal ?? 0);
            } else if (val > maxVal) {
                this.updateValue(maxVal);
            }
        }
        this.onTouched();
    }

    onInputChange(event: Event) {
        const target = event.target as HTMLInputElement;
        let newValue: number | null;
        if (target.value === '') {
            newValue = null;
        } else if (this.integer()) {
            const parsed = parseInt(target.value, 10);
            const maxVal = this.max() ?? Number.MAX_SAFE_INTEGER;
            newValue = isNaN(parsed) ? null : Math.min(parsed, maxVal);
        } else {
            newValue = parseFloat(target.value);
        }
        this.updateValue(newValue);
        // In integer mode, force the DOM to show the clamped/sanitized value.
        // OnPush skips re-rendering when the signal value hasn't changed (e.g., value
        // was already at max from the previous keystroke), so the raw typed string
        // would remain visible without this direct DOM update.
        if (this.integer()) {
            const expected = newValue === null ? '' : String(newValue);
            if (target.value !== expected) {
                target.value = expected;
            }
        }
    }

    onStepDown() {
        const current = this.value() ?? this.min() ?? 0;
        const minVal = this.min();
        let newValue = current - this.step();
        if (minVal !== null && newValue < minVal) {
            newValue = minVal;
        }
        this.updateValue(newValue);
    }

    onStepUp() {
        const current = this.value() ?? this.min() ?? 0;
        const maxVal = this.max();
        let newValue = current + this.step();
        if (maxVal !== null && newValue > maxVal) {
            newValue = maxVal;
        }
        this.updateValue(newValue);
    }

    private updateValue(value: number | null) {
        this.value.set(value);
        this.changed.emit(value);
        this.onChange(value);
    }

    writeValue(value: number | null): void {
        this.value.set(value);
    }

    registerOnChange(fn: (value: number | null) => void): void {
        this.onChange = fn;
    }

    registerOnTouched(fn: () => void): void {
        this.onTouched = fn;
    }

    setDisabledState(isDisabled: boolean): void {
        this.isDisabled.set(isDisabled);
    }
}
