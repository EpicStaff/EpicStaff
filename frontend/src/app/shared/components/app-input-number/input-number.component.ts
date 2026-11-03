import { NgClass } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    ElementRef,
    forwardRef,
    input,
    model,
    output,
    signal,
    viewChild,
} from '@angular/core';
import {
    ControlValueAccessor,
    FormsModule,
    NG_VALIDATORS,
    NG_VALUE_ACCESSOR,
    ValidationErrors,
    Validator,
} from '@angular/forms';
import { MatTooltip } from '@angular/material/tooltip';
import { generateUuid } from '@shared/utils';

import { TooltipComponent } from '../tooltip/tooltip.component';

@Component({
    selector: 'app-input-number',
    templateUrl: './input-number.component.html',
    styleUrls: ['./input-number.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [FormsModule, NgClass, TooltipComponent, MatTooltip],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => InputNumberComponent),
            multi: true,
        },
        {
            provide: NG_VALIDATORS,
            useExisting: forwardRef(() => InputNumberComponent),
            multi: true,
        },
    ],
})
export class InputNumberComponent implements ControlValueAccessor, Validator {
    icon = input<string>('help_outline');
    label = input<string>('');
    required = input<boolean>(false);
    tooltipText = input<string>('');
    // accessible name for the field when it has no visible `label` (e.g. a plain text caption next to it)
    ariaLabel = input<string>('');
    alwaysShowSteps = input<true>();

    mod = input<'default' | 'small'>('default');
    placeholder = input<string>('Type here');
    invalid = input<boolean>(false);
    disabled = input<boolean>(false);
    min = input<number | null>(null);
    max = input<number | null>(null);
    warningMax = input<number | null>(null);
    warningMessage = input<string>('');
    errorMessage = input<string>('');
    stepSize = input<number>(1);
    /** Lets the user type a decimal point; by default only whole numbers can be typed. */
    allowDecimal = input<boolean>(false);
    value = model<number | null>(null);
    changed = output<number | null>();

    readonly nativeInput = viewChild<ElementRef<HTMLInputElement>>('nativeInput');

    hovered = signal<boolean>(false);
    // Keyboard focus anywhere in the field (input or a step button) shows the steps, so Tab can reach them.
    protected readonly focusWithin = signal(false);
    protected readonly stepsShown = computed(() => this.hovered() || this.focusWithin() || !!this.alwaysShowSteps());
    // The browser holds text it cannot parse as a number (e.g. "1.2.3" or a pasted "1,5") and reports it as empty.
    private readonly hasBadInput = signal(false);

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
        return this.invalid() || this.isOutOfRange() || this.hasBadInput();
    });

    isAboveWarning = computed(() => {
        const value = this.value();
        const warning = this.warningMax();
        if (value === null || warning === null) return false;
        if (value <= warning) return false;
        if (this.isInvalid()) return false;
        return true;
    });

    /** The error, else the warning, shown under the input; the input points at it via aria-describedby. */
    protected message = computed(() => {
        if (this.isInvalid() && this.errorMessage()) return this.errorMessage();
        if (this.isAboveWarning() && this.warningMessage()) return this.warningMessage();
        return '';
    });
    protected readonly messageId = `input-number-message-${generateUuid()}`;
    /** Shown as the input's tooltip. */
    protected readonly fieldName = computed(() => this.label() || this.ariaLabel() || this.placeholder());

    onChange: (value: number | null) => void = () => {};
    onTouched: () => void = () => {};
    private onValidatorChange: () => void = () => {};
    private controlDisabled = signal(false);
    isDisabled = computed(() => this.disabled() || this.controlDisabled());

    onInputChange(value: number) {
        // Only decimal fields accept typed separators, so only they can end up with malformed text.
        // Report it as an error instead of passing the empty value on, which would silently clear the field.
        if (this.allowDecimal() && this.nativeInput()?.nativeElement.validity.badInput) {
            this.hasBadInput.set(true);
            this.onValidatorChange();
            return;
        }
        this.hasBadInput.set(false);

        if (value === null || value === undefined) {
            this.updateValue(null);
            return;
        }

        let num = Number(value);
        if (Number.isNaN(num)) return;

        this.updateValue(num);
    }

    onStep(direction: 1 | -1 = 1) {
        if (this.isDisabled()) return;
        const current = Number(this.value()) || 0;
        let next = current + this.stepSize() * direction;

        const min = this.min();
        const max = this.max();
        if (min !== null && next < min) next = min;
        if (max !== null && next > max) next = max;

        // Already at the bound: nothing changed, so nothing is emitted and the form stays pristine.
        if (next === this.value()) return;
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
        const allowedKeys = ['Backspace', 'Tab', 'ArrowLeft', 'ArrowRight', 'Delete', 'Home', 'End'];
        if (allowedKeys.includes(event.key)) return;
        // Steps from the input itself, as a native number field does.
        if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
            event.preventDefault();
            this.onStep(event.key === 'ArrowUp' ? 1 : -1);
            return;
        }
        if (this.allowDecimal() && event.key === '.') return;

        if (!/^\d$/.test(event.key)) {
            event.preventDefault();
        }
    }

    protected onFocusOut(event: FocusEvent): void {
        const wrapper = event.currentTarget as HTMLElement;
        if (!wrapper.contains(event.relatedTarget as Node | null)) this.focusWithin.set(false);
    }

    private updateValue(value: number | null) {
        this.value.set(value);
        this.changed.emit(value);
        this.onChange(value);
    }

    writeValue(value: number | null): void {
        this.hasBadInput.set(false);
        this.value.set(value);
    }

    validate(): ValidationErrors | null {
        return this.hasBadInput() ? { invalidNumber: true } : null;
    }

    registerOnValidatorChange(fn: () => void): void {
        this.onValidatorChange = fn;
    }

    registerOnChange(fn: (value: number | null) => void): void {
        this.onChange = fn;
    }

    registerOnTouched(fn: () => void): void {
        this.onTouched = fn;
    }

    setDisabledState(isDisabled: boolean): void {
        this.controlDisabled.set(isDisabled);
    }
}
