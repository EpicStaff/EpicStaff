import {ChangeDetectionStrategy, Component, forwardRef, input, model, output} from "@angular/core";
import {ControlValueAccessor, NG_VALUE_ACCESSOR} from "@angular/forms";

@Component({
    selector: "app-checkbox",
    templateUrl: "./checkbox.component.html",
    styleUrls: ["./checkbox.component.scss"],
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
    mod = input<'default' | 'multiselect'>('default');
    disabled = input<boolean>(false);

    changed = output<boolean>();

    variant = input<'default' | 'mainColor'>('default');

    private onChange = (_: boolean) => {};
    private onTouched = () => {};

    toggleCheckbox(event: Event): void {
        const input = event.target as HTMLInputElement;
        this.checked.set(input.checked);

        this.onChange(this.checked());
        this.onTouched();
        this.changed.emit(this.checked());
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

    setDisabledState(isDisabled: boolean): void {}
}
