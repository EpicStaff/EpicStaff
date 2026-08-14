import { CommonModule } from '@angular/common';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    EventEmitter,
    Input,
    OnChanges,
    Output,
    SimpleChanges,
} from '@angular/core';
import { FormsModule } from '@angular/forms';

import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { ClickOutsideDirective } from '../../../../shared/directives/click-outside.directive';
import { DurationFilter, DurationOperator } from '../../services/flows-sessions.service';

@Component({
    selector: 'app-duration-filter-dropdown',
    standalone: true,
    imports: [CommonModule, FormsModule, ClickOutsideDirective, AppSvgIconComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
    templateUrl: './duration-filter-dropdown.component.html',
    styleUrls: ['./duration-filter-dropdown.component.scss'],
})
export class DurationFilterDropdownComponent implements OnChanges {
    @Input() value: DurationFilter | null = null;
    @Output() valueChange = new EventEmitter<DurationFilter | null>();

    public selectedOperator: DurationOperator = 'lessThan';
    public selectedUnit: 's' | 'min' | 'h' = 'min';
    public open = false;
    public val1: number | null = null;
    public val2: number | null = null;

    public readonly units: { value: 's' | 'min' | 'h'; label: string }[] = [
        { value: 's', label: 's' },
        { value: 'min', label: 'min' },
        { value: 'h', label: 'h' },
    ];

    public readonly operators: { value: DurationOperator; label: string }[] = [
        { value: 'lessThan', label: '< Less' },
        { value: 'between', label: '<< Between' },
        { value: 'greaterThan', label: '> More' },
        { value: 'equal', label: '= Equal' },
    ];

    get label(): string {
        if (!this.value) return 'Duration';

        const { operator, value, value2 } = this.value;
        if (operator === 'between' && value2 != null) {
            return `${this.formatDuration(value)} – ${this.formatDuration(value2)}`;
        }
        const symbols: Record<DurationOperator, string> = {
            lessThan: '<',
            greaterThan: '>',
            equal: '=',
            between: '<<',
        };
        return `${symbols[operator]} ${this.formatDuration(value)}`;
    }

    constructor(private cdr: ChangeDetectorRef) {}

    public ngOnChanges(changes: SimpleChanges): void {
        if (changes['value'] && this.value) {
            this.selectedOperator = this.value.operator;
            const { unit, val } = this.detectUnit(this.value.value);
            this.selectedUnit = unit;
            this.val1 = val;
            this.val2 = this.value.value2 != null ? this.toUnit(this.value.value2, unit) : null;
        }
    }

    public toggle(event: Event): void {
        event?.stopPropagation();
        this.open = !this.open;
        this.cdr.markForCheck();
    }

    public close(): void {
        this.open = false;
        this.cdr.markForCheck();
    }

    public selectOperator(operator: DurationOperator): void {
        this.selectedOperator = operator;
        this.cdr.markForCheck();
    }

    public selectUnit(unit: 's' | 'min' | 'h'): void {
        this.selectedUnit = unit;
        this.cdr.markForCheck();
    }

    public apply(): void {
        if (this.val1 === null) return;
        if (this.selectedOperator === 'between' && this.val2 === null) return;

        const factor = this.unitFactor();
        const filter: DurationFilter = {
            operator: this.selectedOperator,
            value: Math.floor(this.val1 * factor),
            ...(this.selectedOperator === 'between' && this.val2 !== null
                ? { value2: Math.floor(this.val2 * factor) }
                : {}),
        };
        this.valueChange.emit(filter);
        this.close();
    }

    public clear(): void {
        this.val1 = null;
        this.val2 = null;
        this.selectedOperator = 'lessThan';
        this.selectedUnit = 'min';
        this.valueChange.emit(null);
        this.close();
    }

    private unitFactor(): number {
        if (this.selectedUnit === 'min') return 60;
        if (this.selectedUnit === 'h') return 3600;
        return 1;
    }

    private detectUnit(seconds: number): { unit: 's' | 'min' | 'h'; val: number } {
        if (seconds >= 3600 && seconds % 3600 === 0) return { unit: 'h', val: seconds / 3600 };
        if (seconds >= 60 && seconds % 60 === 0) return { unit: 'min', val: seconds / 60 };
        return { unit: 's', val: seconds };
    }

    private toUnit(seconds: number, unit: 's' | 'min' | 'h'): number {
        if (unit === 'min') return seconds / 60;
        if (unit === 'h') return seconds / 3600;
        return seconds;
    }

    private formatDuration(seconds: number): string {
        if (seconds < 60) return `${seconds}s`;
        const minutes = Math.floor(seconds / 60);
        const remainingSeconds = seconds % 60;
        if (minutes < 60) {
            return remainingSeconds > 0 ? `${minutes}m ${remainingSeconds}s` : `${minutes}m`;
        }
        const hours = Math.floor(minutes / 60);
        const remainingMinutes = minutes % 60;
        return remainingMinutes > 0 ? `${hours}h ${remainingMinutes}m` : `${hours}h`;
    }
}
