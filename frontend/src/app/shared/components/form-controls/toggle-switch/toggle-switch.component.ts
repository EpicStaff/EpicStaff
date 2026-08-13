import {
    ChangeDetectionStrategy,
    Component,
    computed,
    EventEmitter,
    forwardRef,
    Input,
    input,
    Output,
    signal,
} from '@angular/core';
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
    disabled = input<boolean>(false);

    private checkedState = signal(false);

    // Kept as a plain @Input()/@Output() pair for external API compatibility
    // (banana-in-a-box, formControlName's ControlValueAccessor writeValue,
    // etc.) — internally backed by a signal so the template updates
    // reliably under OnPush regardless of markForCheck timing.
    @Input()
    set checked(value: boolean) {
        this.checkedState.set(value);
    }
    get checked(): boolean {
        return this.checkedState();
    }
    @Output() checkedChange = new EventEmitter<boolean>();

    private onChange: (value: boolean) => void = () => {};
    private onTouched = () => {};
    private formDisabled = signal(false);

    isDisabled = computed(() => this.disabled() || this.formDisabled());

    onToggle() {
        if (this.isDisabled()) return;
        const next = !this.checkedState();
        this.checkedState.set(next);
        this.checkedChange.emit(next);
        this.onChange(next);
        this.onTouched();
    }

    writeValue(value: boolean): void {
        this.checkedState.set(value);
    }

    registerOnChange(fn: (value: boolean) => void): void {
        this.onChange = fn;
    }

    registerOnTouched(fn: () => void): void {
        this.onTouched = fn;
    }

    setDisabledState(isDisabled: boolean): void {
        this.formDisabled.set(isDisabled);
    }
}
