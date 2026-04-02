import { ChangeDetectionStrategy, Component, forwardRef, input, model } from '@angular/core';
import { ControlValueAccessor, FormControl, NG_VALUE_ACCESSOR, ReactiveFormsModule } from '@angular/forms';
import { AppIconComponent, CustomInputComponent, TooltipComponent } from '@shared/components';

@Component({
    selector: 'app-listbox',
    templateUrl: './listbox.component.html',
    styleUrls: ['./listbox.component.scss'],
    imports: [TooltipComponent, CustomInputComponent, AppIconComponent, ReactiveFormsModule],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => ListboxComponent),
            multi: true,
        },
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ListboxComponent implements ControlValueAccessor {
    icon = input<string>('help_outline');
    label = input<string>('');
    required = input<boolean>(false);
    tooltipText = input<string>('');
    inputPlaceholder = input<string>('Type here...');

    private onChange: (value: string[]) => void = () => {};
    private onTouched: () => void = () => {};
    private isDisabled = false;

    value = model<string[]>([]);

    inputControl: FormControl = new FormControl('');

    onAdd() {
        const raw = this.inputControl.value?.trim();
        if (!raw || this.isDisabled) return;

        const next = [...this.value(), raw];
        this.updateValue(next);

        this.inputControl.reset('');
    }

    onRemove(index: number) {
        if (this.isDisabled) return;

        const next = this.value().filter((_, i) => i !== index);
        this.updateValue(next);
    }

    private updateValue(next: string[]) {
        this.value.set(next);
        this.onChange(next);
    }

    writeValue(value: string[] | null): void {
        this.value.set(value ?? []);
    }

    registerOnChange(fn: (value: string[]) => void): void {
        this.onChange = fn;
    }

    registerOnTouched(fn: () => void): void {
        this.onTouched = fn;
    }

    setDisabledState(isDisabled: boolean): void {
        this.isDisabled = isDisabled;
    }
}
