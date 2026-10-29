import { ChangeDetectionStrategy, Component, computed, forwardRef, input, model, output, signal } from '@angular/core';
import { ControlValueAccessor, FormsModule, NG_VALUE_ACCESSOR } from '@angular/forms';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { ToggleSwitchComponent } from '../form-controls/toggle-switch/toggle-switch.component';
import { TooltipComponent } from '../tooltip/tooltip.component';

@Component({
    selector: 'app-slider-with-stepper',
    imports: [FormsModule, AppSvgIconComponent, TooltipComponent, ToggleSwitchComponent],
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
    icon = input<string>('help_outline');
    required = input<boolean>(false);
    label = input<string>('');
    tooltipText = input<string>('');
    min = input<number>(0);
    max = input<number>(100);
    step = input<number>(1);
    /** Digits kept after rounding; defaults to the precision of `step`. */
    decimals = input<number | undefined>(undefined);
    optional = input<boolean>(false);

    value = model<number | null>(null);
    changed = output<number | null>();

    onChange: (value: number | null) => void = () => {};
    onTouched: () => void = () => {};
    isDisabled = signal(false);

    private previousValue: number | null = null;

    enabled = computed(() => this.value() !== null);

    private precision = computed(() => this.decimals() ?? this.countFractionDigits(this.step()));

    displayValue = computed(() => {
        const val = this.value();
        if (val === null || val === undefined) return '0';
        return this.precision() > 0 ? val.toFixed(this.precision()) : val.toString();
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
        this.updateValue(this.roundToDecimals(newValue));
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

    onValueInputKeydown(event: Event) {
        (event.target as HTMLInputElement).blur();
    }

    onValueInputChange(event: Event) {
        const target = event.target as HTMLInputElement;
        const raw = target.value.trim();
        const parsed = parseFloat(raw);

        if (raw === '' || isNaN(parsed)) {
            target.value = this.displayValue();
            return;
        }

        const clamped = Math.min(this.max(), Math.max(this.min(), parsed));
        this.updateValue(this.roundToDecimals(clamped));
        target.value = this.displayValue();
        this.onTouched();
    }

    onToggle(checked: boolean) {
        if (checked) {
            const restored = this.previousValue ?? this.min();
            this.updateValue(this.roundToDecimals(restored));
        } else {
            this.previousValue = this.value();
            this.updateValue(null);
        }
    }

    private roundToDecimals(value: number): number {
        const factor = Math.pow(10, this.precision());
        return Math.round(value * factor) / factor;
    }

    private countFractionDigits(value: number): number {
        const fraction = value.toString().split('.')[1];
        return fraction ? fraction.length : 0;
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
