import { ChangeDetectionStrategy, Component, computed, forwardRef, input, model, output, signal } from '@angular/core';
import { ControlValueAccessor, NG_VALUE_ACCESSOR } from '@angular/forms';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { TooltipComponent } from '../tooltip/tooltip.component';

type RadioOption<T = unknown> = {
    value: T;
    label?: string;
    name?: string;
    icon?: string;
    tooltip?: string;
};

@Component({
    selector: 'app-radio-button',
    templateUrl: './radio-button.component.html',
    styleUrls: ['./radio-button.component.scss'],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => RadioButtonComponent),
            multi: true,
        },
    ],
    imports: [TooltipComponent, AppSvgIconComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RadioButtonComponent implements ControlValueAccessor {
    icon = input<string>('help_outline');
    label = input<string>('');
    required = input<boolean>(false);
    tooltipText = input<string>('');

    mod = input<'default' | 'small' | 'segmented'>('default');
    options = input.required<RadioOption[]>();
    disabled = input(false);

    value = model<unknown | null>(null);
    valueChange = output<unknown>();

    private _disabled = signal(false);
    isDisabled = computed(() => this.disabled() || this._disabled());

    activeIndex = computed(() => {
        const idx = this.options().findIndex((o) => o.value === this.value());
        return idx === -1 ? 0 : idx;
    });

    sliderTransform = computed(() => `translateX(${this.activeIndex() * 100}%)`);

    private onChange: (value: unknown) => void = () => {};
    private onTouched: () => void = () => {};

    writeValue(value: unknown | null): void {
        this.value.set(value);
    }

    registerOnChange(fn: (value: unknown) => void): void {
        this.onChange = fn;
    }

    registerOnTouched(fn: () => void): void {
        this.onTouched = fn;
    }

    setDisabledState(isDisabled: boolean): void {
        this._disabled.set(isDisabled);
    }

    select(option: RadioOption): void {
        if (this.isDisabled()) return;

        this.value.set(option.value);
        this.onChange(option.value);
        this.onTouched();
        this.valueChange.emit(option.value);
    }
}
