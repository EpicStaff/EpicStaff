import { Overlay, OverlayModule, OverlayPositionBuilder, OverlayRef } from '@angular/cdk/overlay';
import { TemplatePortal } from '@angular/cdk/portal';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    ElementRef,
    forwardRef,
    inject,
    input,
    signal,
    ViewChild,
    ViewContainerRef,
} from '@angular/core';
import { ControlValueAccessor, FormsModule, NG_VALUE_ACCESSOR } from '@angular/forms';

import { TooltipComponent } from '../tooltip/tooltip.component';

/** 24-hour time slots: 00:00 → 00:30 → … → 23:30 */
function generateHourSlots(): string[] {
    const slots: string[] = [];
    for (let h = 0; h < 24; h++) {
        for (let m = 0; m < 60; m += 30) {
            slots.push(`${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`);
        }
    }
    return slots;
}

const HOUR_SLOTS = generateHourSlots();

/** Parse a stored value ("14:30" or legacy "02:30 PM") into a 24-hour "HH:MM" string. */
function parseValue(value: string): string | null {
    if (!value) return null;
    // Primary: 24-hour "HH:mm"
    const h24 = value.match(/^(\d{1,2}):(\d{2})$/);
    if (h24) {
        const h = parseInt(h24[1], 10);
        if (h > 23) return null;
        return `${String(h).padStart(2, '0')}:${h24[2]}`;
    }
    // Legacy: AM/PM format
    const ampm = value.match(/^(\d{1,2}):(\d{2})\s*(AM|PM)$/i);
    if (ampm) {
        let h = parseInt(ampm[1], 10);
        const m = ampm[2];
        const meridiem = ampm[3].toUpperCase();
        if (meridiem === 'PM' && h !== 12) h += 12;
        else if (meridiem === 'AM' && h === 12) h = 0;
        return `${String(h).padStart(2, '0')}:${m}`;
    }
    return null;
}

@Component({
    selector: 'app-time-picker',
    standalone: true,
    imports: [FormsModule, OverlayModule, TooltipComponent],
    templateUrl: './time-picker.component.html',
    styleUrls: ['./time-picker.component.scss'],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => TimePickerComponent),
            multi: true,
        },
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TimePickerComponent implements ControlValueAccessor {
    label = input<string>('');
    placeholder = input<string>('hh:mm');
    tooltipText = input<string>('');
    activeColor = input<string>('');
    errorMessage = input<string>('');
    required = input<boolean>(false);

    /** The hh:mm portion typed or selected (no meridiem). */
    timeInput = signal<string>('');
    isOpen = signal<boolean>(false);
    isDisabled = signal<boolean>(false);

    /** Full formatted value shown in the trigger and emitted to the form. */
    displayValue = computed<string>(() => this.timeInput());

    filteredSlots = computed<string[]>(() => {
        const val = this.timeInput().trim();
        if (!val || HOUR_SLOTS.includes(val)) return HOUR_SLOTS;
        const filtered = HOUR_SLOTS.filter((s) => s.startsWith(val));
        return filtered.length > 0 ? filtered : HOUR_SLOTS;
    });

    @ViewChild('triggerEl') triggerEl!: ElementRef<HTMLDivElement>;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    @ViewChild('dropdownTemplate') dropdownTemplate!: any;
    @ViewChild('timeInputEl') private timeInputEl?: ElementRef<HTMLInputElement>;

    private overlayRef: OverlayRef | null = null;
    private overlay = inject(Overlay);
    private overlayPositionBuilder = inject(OverlayPositionBuilder);
    private vcr = inject(ViewContainerRef);

    private onChange: (v: string) => void = () => {};
    private onTouched: () => void = () => {};

    onFocus(): void {
        this.openDropdown();
    }

    onEnterKey(): void {
        if (this.isOpen()) {
            this.close();
        }
    }

    onTimeInput(raw: string): void {
        const el = this.timeInputEl?.nativeElement;
        const rawCaret = el?.selectionStart ?? null;

        const digits = raw.replace(/\D/g, '').slice(0, 4);
        const formatted = digits.length >= 3 ? `${digits.slice(0, 2)}:${digits.slice(2)}` : digits;

        const changed = formatted !== this.timeInput();
        this.timeInput.set(formatted);
        this.onInput();

        if (changed && rawCaret !== null && el) {
            const digitsBeforeCaret = raw.slice(0, rawCaret).replace(/\D/g, '').length;
            const newCaret =
                formatted.length < 3
                    ? Math.min(digitsBeforeCaret, formatted.length)
                    : digitsBeforeCaret <= 2
                      ? digitsBeforeCaret
                      : Math.min(digitsBeforeCaret + 1, formatted.length);
            setTimeout(() => el.setSelectionRange(newCaret, newCaret));
        }
    }

    onInput(): void {
        this.onChange(this.displayValue());
        if (!this.isOpen()) {
            this.openDropdown();
        }
    }

    selectSlot(slot: string): void {
        this.timeInput.set(slot);
        this.onChange(this.displayValue());
        this.onTouched();
        this.close();
    }

    openDropdown(): void {
        if (this.isOpen() || this.isDisabled()) return;

        const positionStrategy = this.overlayPositionBuilder
            .flexibleConnectedTo(this.triggerEl)
            .withPositions([
                {
                    originX: 'start',
                    originY: 'bottom',
                    overlayX: 'start',
                    overlayY: 'top',
                    offsetY: 4,
                },
                {
                    originX: 'start',
                    originY: 'top',
                    overlayX: 'start',
                    overlayY: 'bottom',
                    offsetY: -4,
                },
            ])
            .withPush(false);

        this.overlayRef = this.overlay.create({
            positionStrategy,
            scrollStrategy: this.overlay.scrollStrategies.reposition(),
            hasBackdrop: true,
            backdropClass: 'transparent-backdrop',
            width: this.triggerEl.nativeElement.offsetWidth,
        });

        this.overlayRef.backdropClick().subscribe(() => this.close());

        const portal = new TemplatePortal(this.dropdownTemplate, this.vcr);
        this.overlayRef.attach(portal);
        this.isOpen.set(true);
        this.timeInputEl?.nativeElement.focus();
    }

    close(): void {
        if (this.overlayRef) {
            this.overlayRef.dispose();
            this.overlayRef = null;
        }
        this.onTouched();
        this.isOpen.set(false);
    }

    // ControlValueAccessor
    writeValue(value: string): void {
        this.timeInput.set(parseValue(value) ?? '');
    }

    registerOnChange(fn: (v: string) => void): void {
        this.onChange = fn;
    }

    registerOnTouched(fn: () => void): void {
        this.onTouched = fn;
    }

    setDisabledState(isDisabled: boolean): void {
        this.isDisabled.set(isDisabled);
    }
}
