import { Overlay, OverlayModule, OverlayPositionBuilder, OverlayRef } from '@angular/cdk/overlay';
import { TemplatePortal } from '@angular/cdk/portal';
import { CommonModule } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    ElementRef,
    EventEmitter,
    inject,
    Input,
    Output,
    TemplateRef,
    ViewChild,
    ViewContainerRef,
} from '@angular/core';
import { DateRangeFilter } from '@shared/models';

import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { DateRangePickerComponent } from '../../../../shared/components/date-range-picker/date-range-picker.component';

@Component({
    selector: 'app-created-at-filter-dropdown',
    standalone: true,
    imports: [CommonModule, OverlayModule, AppSvgIconComponent, DateRangePickerComponent],
    templateUrl: './date-picker-dropdown.component.html',
    styleUrls: ['./date-picker-dropdown.component.scss'],
    changeDetection: ChangeDetectionStrategy.Eager,
})
export class DatePickerDropdownComponent {
    @Input() value: DateRangeFilter | null = null;
    @Output() valueChange = new EventEmitter<DateRangeFilter | null>();

    @ViewChild('triggerEl') private triggerEl!: ElementRef<HTMLButtonElement>;
    @ViewChild('dropdownTemplate') private dropdownTemplate!: TemplateRef<unknown>;

    private overlayRef: OverlayRef | null = null;
    private overlay = inject(Overlay);
    private overlayPositionBuilder = inject(OverlayPositionBuilder);
    private vcr = inject(ViewContainerRef);

    public isOpen = false;

    public get hasValue(): boolean {
        return !!(this.value && (this.value.after || this.value.before));
    }

    public toggle(event: Event): void {
        event.stopPropagation();
        if (this.overlayRef) {
            this.close();
        } else {
            this.open();
        }
    }

    public close(): void {
        if (this.overlayRef) {
            this.overlayRef.dispose();
            this.overlayRef = null;
        }
        this.isOpen = false;
    }

    public onSelect(range: DateRangeFilter): void {
        this.valueChange.emit(range);
        this.close();
    }

    public clear(): void {
        this.valueChange.emit(null);
        this.close();
    }

    private open(): void {
        const positionStrategy = this.overlayPositionBuilder
            .flexibleConnectedTo(this.triggerEl)
            .withPositions([
                { originX: 'start', originY: 'bottom', overlayX: 'start', overlayY: 'top', offsetY: 20 },
                { originX: 'end', originY: 'bottom', overlayX: 'end', overlayY: 'top', offsetY: 20 },
                { originX: 'start', originY: 'top', overlayX: 'start', overlayY: 'bottom', offsetY: -4 },
            ])
            .withPush(true);

        this.overlayRef = this.overlay.create({
            positionStrategy,
            scrollStrategy: this.overlay.scrollStrategies.reposition(),
            hasBackdrop: true,
            backdropClass: 'transparent-backdrop',
        });

        this.overlayRef.backdropClick().subscribe(() => this.close());

        const portal = new TemplatePortal(this.dropdownTemplate, this.vcr);
        this.overlayRef.attach(portal);
        this.isOpen = true;
    }
}
