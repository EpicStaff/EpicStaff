import { ChangeDetectionStrategy, Component, forwardRef, input, model, output } from '@angular/core';
import { ControlValueAccessor, NG_VALUE_ACCESSOR } from '@angular/forms';

@Component({
    selector: 'app-checkbox',
    templateUrl: './checkbox.component.html',
    styleUrls: ['./checkbox.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => CheckboxComponent),
            multi: true,
        },
    ],
})
export class CheckboxComponent implements ControlValueAccessor {
    indeterminate = input<boolean>(false);
    checked = model<boolean>(false);
    color = input<'primary' | 'secondary'>('primary');
    disabled = input<boolean>(false);
    /** The box's accessible name, where no visible label sits next to it (a table's row checkbox). */
    ariaLabel = input<string | null>(null);

    changed = output<boolean>();

    private onChange: (value: boolean) => void = () => {};
    private onTouched = () => {};

    toggleCheckbox(event: Event): void {
        const input = event.target as HTMLInputElement;
        this.checked.set(input.checked);

        this.onChange(this.checked());
        this.onTouched();
        this.changed.emit(this.checked());
        // A listener may set `checked` back (a "-" box that clears instead of ticking). The browser
        // already ticked the box, and `[checked]` won't rewrite a value it last rendered, so match it here.
        input.checked = this.checked();
    }

    writeValue(value: boolean): void {
        this.checked.set(value);
    }

    registerOnChange(fn: (value: boolean) => void): void {
        this.onChange = fn;
    }

    registerOnTouched(fn: () => void): void {
        this.onTouched = fn;
    }

    setDisabledState(isDisabled: boolean): void {
        void isDisabled;
    }
}
