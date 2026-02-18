import {
    Component,
    ChangeDetectionStrategy,
    input,
    output,
    model,
    signal, computed, forwardRef,
} from '@angular/core';
import {ControlValueAccessor, FormsModule, NG_VALUE_ACCESSOR} from "@angular/forms";
import {NgClass} from "@angular/common";
import {TooltipComponent} from "../tooltip/tooltip.component";

@Component({
    selector: 'app-input-number',
    standalone: true,
    templateUrl: './input-number.component.html',
    styleUrls: ['./input-number.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [
        FormsModule,
        NgClass,
        TooltipComponent
    ],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => InputNumberComponent),
            multi: true,
        },
    ],
})
export class InputNumberComponent implements ControlValueAccessor {
    icon = input<string>('help_outline');
    label = input<string>('');
    required = input<boolean>(false);
    tooltipText = input<string>('');

    mod = input<'default' | 'small'>('default');
    placeholder = input<string>('Type here');
    invalid = input<boolean>(false);
    min = input<number | null>(null);
    max = input<number | null>(null);
    stepSize = input<number>(1);
    value = model<number | null>(null);
    changed = output<number | null>();

    hovered = signal<boolean>(false);

    isOutOfRange = computed(() => {
        const value = this.value();
        const min = this.min();
        const max = this.max();

        if (value === null) return false;
        if (min !== null && value < min) return true;
        if (max !== null && value > max) return true;

        return false;
    });

    isInvalid = computed(() => {
        return this.invalid() || this.isOutOfRange();
    });

    onChange: (value: number | null) => void = () => {};
    onTouched: () => void = () => {};
    isDisabled = signal(false);

    onInputChange(value: number) {
        if (value === null || value === undefined) {
            this.updateValue(null);
            return;
        }

        let num = Number(value);
        if (Number.isNaN(num)) return;

        this.updateValue(num);
    }

    onStep(direction: 1 | -1 = 1) {
        const current = Number(this.value()) || 0;
        let next = current + this.stepSize() * direction;

        this.updateValue(next);
    }

    canStepUp(): boolean {
        const value = this.value();
        const max = this.max();

        if (value === null) {
            return max === null || this.stepSize() <= max;
        }

        return max === null || value < max;
    }

    canStepDown(): boolean {
        const value = this.value();
        const min = this.min();

        if (value === null) {
            return min === null || -this.stepSize() >= min;
        }

        return min === null || value > min;
    }

    onKeyDown(event: KeyboardEvent) {
        const allowedKeys = [
            'Backspace', 'Tab', 'ArrowLeft', 'ArrowRight', 'Delete', 'Home', 'End'
        ];
        if (allowedKeys.includes(event.key)) return;

        if (!/^\d$/.test(event.key)) {
            event.preventDefault();
        }
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
