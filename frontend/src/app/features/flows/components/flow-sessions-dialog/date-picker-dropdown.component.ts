import { CommonModule } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    ElementRef,
    EventEmitter,
    HostListener,
    Input,
    OnChanges,
    Output,
    SimpleChanges,
} from '@angular/core';
import { FormsModule } from '@angular/forms';

import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { DatePickerComponent } from '../../../../shared/components/date-picker/date-picker.component';
import { DateRangeFilter } from '../../services/flows-sessions.service';

@Component({
    selector: 'app-created-at-filter-dropdown',
    standalone: true,
    imports: [CommonModule, FormsModule, AppSvgIconComponent, DatePickerComponent],
    templateUrl: './date-picker-dropdown.component.html',
    styleUrls: ['./date-picker-dropdown.component.scss'],
    changeDetection: ChangeDetectionStrategy.Default,
})
export class DatePickerDropdownComponent implements OnChanges {
    @Input() value: DateRangeFilter | null = null;
    @Output() valueChange = new EventEmitter<DateRangeFilter | null>();

    public open = false;
    public fromStr = '';
    public toStr = '';
    public error = '';

    constructor(private host: ElementRef<HTMLElement>) {}

    public get hasValue(): boolean {
        return !!(this.value && (this.value.after || this.value.before));
    }

    public ngOnChanges(changes: SimpleChanges): void {
        if (changes['value']) {
            this.fromStr = this.value?.after ? this.isoToDisplay(this.value.after) : '';
            this.toStr = this.value?.before ? this.isoToDisplay(this.value.before) : '';
        }
    }

    @HostListener('document:click', ['$event'])
    public onDocumentClick(event: MouseEvent): void {
        if (!this.open) return;
        const target = event.target as HTMLElement;
        if (this.host.nativeElement.contains(target)) return;
        if (target.closest('.cdk-overlay-container')) return;
        this.close();
    }

    public toggle(event: Event): void {
        event.stopPropagation();
        this.open = !this.open;
    }

    public close(): void {
        this.open = false;
        this.error = '';
    }

    public apply(): void {
        const fromDate = this.fromStr ? this.parse(this.fromStr) : null;
        const toDate = this.toStr ? this.parse(this.toStr) : null;

        if (this.fromStr && !fromDate) {
            this.error = 'Invalid "From" date';
            return;
        }

        if (this.toStr && !toDate) {
            this.error = 'Invalid "To" date';
            return;
        }

        if (fromDate && toDate && fromDate.getTime() > toDate.getTime()) {
            this.error = '"From" must be before "To"';
            return;
        }

        if (!fromDate && !toDate) {
            this.clear();
            return;
        }

        this.error = '';
        this.valueChange.emit({
            after: fromDate ? this.startOfDayIso(fromDate) : null,
            before: toDate ? this.endOfDayIso(toDate) : null,
        });
        this.close();
    }

    public clear(): void {
        this.fromStr = '';
        this.toStr = '';
        this.error = '';
        this.valueChange.emit(null);
        this.close();
    }

    private parse(value: string): Date | null {
        const m = value.match(/^(\d{2})\.(\d{2})\.(\d{4})$/);
        if (!m) return null;
        const d = parseInt(m[1], 10);
        const mo = parseInt(m[2], 10) - 1;
        const y = parseInt(m[3], 10);
        const date = new Date(y, mo, d);
        if (date.getFullYear() !== y || date.getMonth() !== mo || date.getDate() !== d) return null;
        return date;
    }

    private startOfDayIso(d: Date): string {
        return new Date(d.getFullYear(), d.getMonth(), d.getDate(), 0, 0, 0, 0).toISOString();
    }

    private endOfDayIso(d: Date): string {
        return new Date(d.getFullYear(), d.getMonth(), d.getDate(), 23, 59, 59, 999).toISOString();
    }

    private isoToDisplay(iso: string): string {
        const d = new Date(iso);
        const day = String(d.getDate()).padStart(2, '0');
        const mo = String(d.getMonth() + 1).padStart(2, '0');
        return `${day}.${mo}.${d.getFullYear()}`;
    }
}
