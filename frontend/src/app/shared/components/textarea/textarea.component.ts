import { ChangeDetectionStrategy, Component, forwardRef, input, signal } from '@angular/core';
import { ControlValueAccessor, NG_VALUE_ACCESSOR } from '@angular/forms';

import { TooltipComponent } from '../tooltip/tooltip.component';

@Component({
    selector: 'app-textarea',
    imports: [TooltipComponent],
    templateUrl: './textarea.component.html',
    styleUrls: ['./textarea.component.scss'],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => TextareaComponent),
            multi: true,
        },
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TextareaComponent implements ControlValueAccessor {
    label = input<string>('');
    tooltipText = input<string>('');
    icon = input<string>('help_outline');
    placeholder = input<string>('Enter text...');
    rows = input<number>(3);
    required = input<boolean>(false);
    invalid = input<boolean>(false);
    disabled = input<boolean>(false);

    value = signal<string>('');

    private onChange: (value: string) => void = () => {};
    private onTouched: () => void = () => {};

    writeValue(value: string | null): void {
        this.value.set(value ?? '');
    }

    registerOnChange(fn: (value: string) => void): void {
        this.onChange = fn;
    }

    registerOnTouched(fn: () => void): void {
        this.onTouched = fn;
    }

    setDisabledState(isDisabled: boolean): void {
        void isDisabled;
    }

    handleInput(event: Event): void {
        const val = (event.target as HTMLTextAreaElement).value;
        this.value.set(val);
        this.onChange(val);
    }

    handleBlur(): void {
        this.onTouched();
    }
}
