import { ChangeDetectionStrategy, Component, EventEmitter, forwardRef, Input, input, Output } from '@angular/core';
import { ControlValueAccessor, NG_VALUE_ACCESSOR } from '@angular/forms';

import { TooltipComponent } from '../../tooltip/tooltip.component';

@Component({
    selector: 'app-toggle-switch',
    standalone: true,
    templateUrl: './toggle-switch.component.html',
    styleUrls: ['./toggle-switch.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => ToggleSwitchComponent),
            multi: true,
        },
    ],
    imports: [TooltipComponent],
})
export class ToggleSwitchComponent implements ControlValueAccessor {
    icon = input<string>('help_outline');
    label = input<string>('');
    required = input<boolean>(false);
    tooltipText = input<string>('');

    @Input() checked = false;
    @Output() checkedChange = new EventEmitter<boolean>();

    private onChange: (value: boolean) => void = () => {};
    private onTouched = () => {};
    private isDisabled = false;

    onToggle() {
        if (this.isDisabled) return;
        this.checked = !this.checked;
        this.checkedChange.emit(this.checked);
        this.onChange(this.checked);
        this.onTouched();
    }

    writeValue(value: boolean): void {
        this.checked = value;
    }

    registerOnChange(fn: (value: boolean) => void): void {
        this.onChange = fn;
    }

    registerOnTouched(fn: () => void): void {
        this.onTouched = fn;
    }

    setDisabledState(isDisabled: boolean): void {
        this.isDisabled = isDisabled;
    }
}
