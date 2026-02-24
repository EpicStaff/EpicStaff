import {
    ChangeDetectionStrategy,
    Component,
    ElementRef,
    ViewContainerRef,
    ViewChild,
    signal,
    input,
    model, output, computed, inject
} from '@angular/core';

import { TemplatePortal } from '@angular/cdk/portal';
import { NgClass } from "@angular/common";
import { Overlay, OverlayPositionBuilder, OverlayRef, OverlayModule } from "@angular/cdk/overlay";
import { ControlValueAccessor, NG_VALUE_ACCESSOR } from "@angular/forms";
import { TooltipComponent } from "../tooltip/tooltip.component";

export interface SelectItem {
    name: string;
    tip?: string;
    value: unknown;
    group?: string;
}

@Component({
    selector: 'app-select',
    imports: [NgClass, TooltipComponent, OverlayModule],
    templateUrl: './select.component.html',
    styleUrls: ['./select.component.scss'],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: SelectComponent,
            multi: true
        }
    ],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class SelectComponent implements ControlValueAccessor {
    icon = input<string>('help_outline');
    label = input<string>('');
    required = input<boolean>(false);
    tooltipText = input<string>('');
    mod = input<'default' | 'small'>('default');
    items = input<SelectItem[]>([]);
    placeholder = input<string>('Select option');
    invalid = input<boolean>(false);

    open = signal(false);
    isDisabled = signal(false);

    selectedValue = model<unknown | null>(null);
    selectedItem = computed(() => {
        const value = this.selectedValue();
        if (value === undefined || value === null) return null;

        return this.items().find(i => i.value === value) ?? null;
    });

    changed = output<any>();

    private onChange: (value: unknown) => void = () => {};
    private onTouched: () => void = () => {};

    @ViewChild('triggerBtn') triggerBtn!: ElementRef<HTMLButtonElement>;
    @ViewChild('dropdownTemplate') dropdownTemplate!: any;

    private overlayRef!: OverlayRef;

    private overlay = inject(Overlay);
    private overlayPositionBuilder = inject(OverlayPositionBuilder);
    private vcr = inject(ViewContainerRef);

    toggle() {
        this.open() ? this.close() : this.openDropdown();
    }

    openDropdown() {
        if (!this.overlayRef) {
            const positionStrategy = this.overlayPositionBuilder
                .flexibleConnectedTo(this.triggerBtn)
                .withPositions([{
                    originX: 'start',
                    originY: 'bottom',
                    overlayX: 'start',
                    overlayY: 'top',
                    offsetY: 4
                }])
                .withPush(true);

            this.overlayRef = this.overlay.create({
                positionStrategy,
                scrollStrategy: this.overlay.scrollStrategies.reposition(),
                hasBackdrop: true,
                backdropClass: 'transparent-backdrop',
                width: this.triggerBtn.nativeElement.offsetWidth
            });

            this.overlayRef.backdropClick().subscribe(() => this.close());
        }

        const portal = new TemplatePortal(this.dropdownTemplate, this.vcr);
        this.overlayRef.attach(portal);
        this.open.set(true);
    }

    close() {
        if (this.overlayRef) {
            this.overlayRef.detach();
        }
        this.onTouched();
        this.open.set(false);
    }

    select(item: SelectItem) {
        if (this.isDisabled()) return;
        this.onChange(item.value);
        this.onTouched();

        this.selectedValue.set(item.value);
        this.changed.emit(item.value);
        this.close();
    }

    writeValue(value: unknown): void {
        this.selectedValue.set(value);
    }

    registerOnChange(fn: (value: unknown) => void): void {
        this.onChange = fn;
    }

    registerOnTouched(fn: () => void): void {
        this.onTouched = fn;
    }

    setDisabledState(isDisabled: boolean): void {
        this.isDisabled.set(isDisabled);
    }
}
