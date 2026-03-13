import { ChangeDetectionStrategy, Component, forwardRef, input, model, output } from "@angular/core";
import { ControlValueAccessor, NG_VALUE_ACCESSOR } from "@angular/forms";
import { NgClass } from "@angular/common";
import { TooltipComponent } from "../tooltip/tooltip.component";

export interface SegmentedOption<T = unknown> {
    label: string;
    value: T;
}

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
    imports: [
        NgClass,
        TooltipComponent
    ],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class RadioButtonComponent<T> implements ControlValueAccessor {
    icon = input<string>('help_outline');
    label = input<string>('');
    required = input<boolean>(false);
    tooltipText = input<string>('');

    mod = input<'default' | 'small'>('default');
    options = input.required<SegmentedOption<T>[]>();
    disabled = input(false);

    value = model<T | null>(null);
    valueChange = output<T>();

    private onChange: (value: T) => void = () => {};
    private onTouched: () => void = () => {};

    writeValue(value: T | null): void {
        this.value.set(value);
    }

    registerOnChange(fn: (value: T) => void): void {
        this.onChange = fn;
    }

    registerOnTouched(fn: () => void): void {
        this.onTouched = fn;
    }

    setDisabledState(isDisabled: boolean): void {}

    select(option: SegmentedOption<T>) {
        if (this.disabled()) return;

        this.value.set(option.value);

        this.onChange(option.value);
        this.onTouched();

        this.valueChange.emit(option.value);
    }
}
