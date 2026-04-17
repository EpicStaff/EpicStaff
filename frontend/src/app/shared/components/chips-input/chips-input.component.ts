import { ChangeDetectionStrategy, Component, effect, forwardRef, input, model } from '@angular/core';
import { ControlValueAccessor, FormControl, NG_VALUE_ACCESSOR, ReactiveFormsModule, Validators } from '@angular/forms';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { ValidationErrorsComponent } from '../app-validation-errors/validation-errors.component';
import { CustomInputComponent } from '../form-input/form-input.component';
import { TooltipComponent } from '../tooltip/tooltip.component';

@Component({
    selector: 'app-chips-input',
    templateUrl: './chips-input.component.html',
    styleUrls: ['./chips-input.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [
        TooltipComponent,
        CustomInputComponent,
        ReactiveFormsModule,
        ValidationErrorsComponent,
        AppSvgIconComponent,
    ],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => ChipsInputComponent),
            multi: true,
        },
    ],
})
export class ChipsInputComponent implements ControlValueAccessor {
    icon = input<string>('help_outline');
    label = input<string>('');
    required = input<boolean>(false);
    tooltipText = input<string>('');
    inputPlaceholder = input<string>('Type here...');
    minItemLength = input<number | null>(null);
    maxItemLength = input<number | null>(null);

    private onChange: (value: string[]) => void = () => {};
    private onTouched: () => void = () => {};
    private isDisabled = false;

    value = model<string[]>([]);
    inputControl = new FormControl<string>('', []);

    constructor() {
        effect(() => {
            const min = this.minItemLength();
            const max = this.maxItemLength();

            const validators = [];

            if (min !== null) validators.push(Validators.minLength(min));
            if (max !== null) validators.push(Validators.maxLength(max));

            this.inputControl.setValidators(validators);
            this.inputControl.updateValueAndValidity();
        });
    }

    onAdd() {
        const raw = this.inputControl.value?.trim();
        if (!raw || this.isDisabled || this.inputControl.invalid) return;

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
