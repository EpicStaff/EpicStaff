import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    computed,
    EventEmitter,
    forwardRef,
    inject,
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

    @Input() checked = false;
    @Output() checkedChange = new EventEmitter<boolean>();

    private readonly cdr = inject(ChangeDetectorRef);

    private onChange: (value: boolean) => void = () => {};
    private onTouched = () => {};
    private formDisabled = signal(false);

    isDisabled = computed(() => this.disabled() || this.formDisabled());

    onToggle() {
        if (this.isDisabled()) return;
        const next = !this.checked;
        this.checked = next;
        this.checkedChange.emit(next);
        this.onChange(next);
        this.onTouched();
        this.cdr.markForCheck();
    }

    writeValue(value: boolean): void {
        this.checked = value;
        this.cdr.markForCheck();
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
