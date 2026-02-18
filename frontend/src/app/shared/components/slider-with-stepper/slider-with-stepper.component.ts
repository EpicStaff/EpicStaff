import {
    Component,
    ChangeDetectionStrategy,
    input,
    output,
    model,
    signal,
    computed,
    forwardRef,
} from '@angular/core';
import { ControlValueAccessor, FormsModule, NG_VALUE_ACCESSOR } from '@angular/forms';
import { CommonModule } from '@angular/common';
import { FormFieldLabelComponent } from '../form-field-label/form-field-label.component';

@Component({
    selector: 'app-slider-with-stepper',
    standalone: true,
    imports: [CommonModule, FormsModule, FormFieldLabelComponent],
    templateUrl: './slider-with-stepper.component.html',
    styleUrls: ['./slider-with-stepper.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => SliderWithStepperComponent),
            multi: true,
        },
    ],
})
export class SliderWithStepperComponent implements ControlValueAccessor {
    label = input<string>('');
    tooltipText = input<string>('');
    min = input<number>(0);
    max = input<number>(100);
    step = input<number>(1);
    decimals = input<number>(0);

    value = model<number | null>(null);
    changed = output<number | null>();

    onChange: (value: number | null) => void = () => {};
    onTouched: () => void = () => {};
    isDisabled = signal(false);

    displayValue = computed(() => {
        const val = this.value();
        if (val === null || val === undefined) return '0';
        return this.decimals() > 0 ? val.toFixed(this.decimals()) : val.toString();
    });

    sliderPercentage = computed(() => {
        const val = this.value() ?? this.min();
        const minVal = this.min();
        const maxVal = this.max();
        return ((val - minVal) / (maxVal - minVal)) * 100;
    });

    onSliderChange(event: Event) {
        const target = event.target as HTMLInputElement;
        const newValue = parseFloat(target.value);
        this.updateValue(newValue);
    }

    onStepDown() {
        const current = this.value() ?? this.min();
        const newValue = Math.max(this.min(), current - this.step());
        this.updateValue(this.roundToDecimals(newValue));
    }

    onStepUp() {
        const current = this.value() ?? this.min();
        const newValue = Math.min(this.max(), current + this.step());
        this.updateValue(this.roundToDecimals(newValue));
    }

    private roundToDecimals(value: number): number {
        const factor = Math.pow(10, this.decimals());
        return Math.round(value * factor) / factor;
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

