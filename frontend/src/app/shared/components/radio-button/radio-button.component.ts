import { ChangeDetectionStrategy, Component, forwardRef, input, model, output } from '@angular/core';
import { ControlValueAccessor, NG_VALUE_ACCESSOR } from '@angular/forms';

import { SelectItem } from '../select/select.component';
import { TooltipComponent } from '../tooltip/tooltip.component';

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
    imports: [TooltipComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RadioButtonComponent implements ControlValueAccessor {
    icon = input<string>('help_outline');
    label = input<string>('');
    required = input<boolean>(false);
    tooltipText = input<string>('');

    mod = input<'default' | 'small'>('default');
    options = input.required<SelectItem[]>();
    disabled = input(false);

    value = model<unknown | null>(null);
    valueChange = output<unknown>();

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
        void isDisabled;
    }

    select(option: SelectItem) {
        if (this.disabled()) return;

        this.value.set(option.value);

        this.onChange(option.value);
        this.onTouched();

        this.valueChange.emit(option.value);
    }
}
